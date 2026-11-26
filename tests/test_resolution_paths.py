import json
from pathlib import Path

import pytest

from return_intelligence.agents.reason import ReasonClassificationAgent
from return_intelligence.agents.retention import RetentionRecommendationAgent
from return_intelligence.db.connection import transaction
from return_intelligence.db.fixtures import SCENARIOS
from return_intelligence.domain.errors import PolicyViolation, ValidationError
from return_intelligence.domain.resolution import resolution_path
from return_intelligence.integrations.strands_factory import _SPECIALIST_PROMPTS
from tests.fakes import make_fake_bedrock_provider


def _recommend(service, order_id, reason):
    return_id = service.start_return(order_id)["return_id"]
    recommendation = service.submit_reason(return_id, reason)["recommendation"]
    return return_id, recommendation


def _variants(recommendation):
    return {(option["sku"], option["size"], option["color"]) for option in recommendation["options"]}


def _on_hand(repo, sku, size, color):
    return repo.one("SELECT on_hand FROM inventory WHERE sku=? AND size=? AND color=?", (sku, size, color))["on_hand"]


# --- recommendation level (plan item 5) ---


def test_resolution_path_rules():
    assert resolution_path(["Missing Item/Wrong Item"], {"fulfillment_issue": "out_of_stock"}, 0) == "OUT_OF_STOCK"
    assert resolution_path(["Missing Item/Wrong Item"], {"fulfillment_issue": "missing_item"}, 1) == "MISSING_ITEM"
    assert resolution_path(["Missing Item/Wrong Item"], {"fulfillment_issue": "wrong_item"}, 1) == "SERVICE"
    assert resolution_path(["Delayed Shipping"], {}, 0) == "SERVICE"
    assert resolution_path(["Delayed Shipping"], {}, 1) == "NORMAL"


def test_late_and_too_small_offers_exchange_first(service):
    _, recommendation = _recommend(service, "SYN-O-SIZE-001", "They arrived late and are too small")
    assert recommendation["choices"] == ["EXCHANGE", "KEEP", "REFUND"]
    assert recommendation["resolution_path"] == "NORMAL"
    assert recommendation["recommended_action"] == "EXCHANGE"
    assert any(option["size"] == "9" for option in recommendation["options"])


def test_delivered_delay_only_has_no_options(service):
    _, recommendation = _recommend(service, "SYN-O-DELAY-001", "shipping is delayed")
    assert recommendation["choices"] == ["KEEP", "REFUND"] and recommendation["options"] == []
    assert recommendation["recommended_action"] == "KEEP"


def test_too_large_without_smaller_stock_never_offers_exchange(service):
    _, recommendation = _recommend(service, "SYN-O-SIZE-001", "too large")
    assert recommendation["choices"] == ["KEEP", "REFUND"] and recommendation["options"] == []


def test_wrong_colour_falls_back_to_same_size_similar_style(service, repo):
    with transaction(repo.db_path, True) as connection:
        connection.execute("UPDATE inventory SET reserved=on_hand WHERE sku='SYN-RUNNER-100' AND size='8' AND color='Red'")
    _, recommendation = _recommend(service, "SYN-O-COLOR-001", "wrong color")
    assert _variants(recommendation) == {("SYN-RUNNER-110", "8", "White")}
    assert recommendation["recommended_action"] == "EXCHANGE"


def test_dislike_options_are_in_the_customers_size(service):
    _, recommendation = _recommend(service, "SYN-O-SIZE-001", "I dislike these shoes")
    assert recommendation["options"]
    assert all(option["size"] == "8" for option in recommendation["options"])
    assert ("SYN-RUNNER-100", "8", "Blue") not in _variants(recommendation)


def test_missing_item_offers_reship_of_same_variant(service):
    _, recommendation = _recommend(service, "SYN-O-MISSING-001", "My item never arrived and is missing")
    assert recommendation["resolution_path"] == "MISSING_ITEM"
    assert recommendation["choices"] == ["RESHIP", "REFUND"] and recommendation["recommended_action"] == "RESHIP"
    assert _variants(recommendation) == {("SYN-RUNNER-110", "8", "White")}


def test_out_of_stock_offers_same_size_similar_styles(service):
    _, recommendation = _recommend(service, "SYN-O-OOS-001", "The shoes were out of stock and never shipped")
    assert recommendation["resolution_path"] == "OUT_OF_STOCK"
    assert recommendation["choices"] == ["RESHIP", "REFUND"]
    assert _variants(recommendation) == {("SYN-RUNNER-100", "8", "Red"), ("SYN-RUNNER-110", "8", "White")}


@pytest.mark.parametrize(
    ("order_id", "reason"),
    [("SYN-O-COLOR-001", "I received the wrong item"), ("SYN-O-MISSING-001", "shipping is delayed")],
)
def test_wrong_item_and_undelivered_delay_keep_service_path(service, order_id, reason):
    _, recommendation = _recommend(service, order_id, reason)
    assert recommendation["resolution_path"] == "SERVICE"
    assert recommendation["choices"] == ["SERVICE_RESOLUTION", "REFUND"] and recommendation["options"] == []


@pytest.mark.parametrize("key", [key for key, value in SCENARIOS.items() if "order_id" in value])
def test_refund_is_always_offered(service, key):
    _, recommendation = _recommend(service, SCENARIOS[key]["order_id"], SCENARIOS[key]["reason"])
    assert "REFUND" in recommendation["choices"]
    assert "EXCHANGE" not in recommendation["choices"] or recommendation["options"]


def test_bedrock_honours_preferred_exchange_over_model_pick(repo):
    provider = make_fake_bedrock_provider(
        {
            "retention": {
                "acknowledgement": "Sorry about the fit.",
                "reason_summary": "The pair is too small.",
                "recommended_action": "REFUND",
                "rationale": "A larger size is in stock.",
            }
        }
    )
    item = repo.get_order_item("SYN-O-SIZE-001")
    classification = ReasonClassificationAgent().classify("They arrived late and are too small")
    result = RetentionRecommendationAgent(repo, provider).recommend(item, classification)
    assert "Recommended next step: EXCHANGE" in result.explanation
    assert "Continue with Refund" in result.explanation
    key, prompt = provider._runtime.prompts[-1]
    assert key == "retention" and "preferred_action" in prompt and '"EXCHANGE"' in prompt
    assert "prefer EXCHANGE" in _SPECIALIST_PROMPTS["retention"]


# --- decision level (plan item 6) ---


def test_reship_missing_item_decrements_stock_and_needs_no_photos(service, repo):
    return_id, recommendation = _recommend(service, "SYN-O-MISSING-001", "My item never arrived and is missing")
    assert _on_hand(repo, "SYN-RUNNER-110", "8", "White") == 5
    result = service.record_decision(return_id, "RESHIP", recommendation["options"][0]["option_id"])
    assert result["state"] == "COMPLETED_SERVICE" and not result["photos_required"]
    assert _on_hand(repo, "SYN-RUNNER-110", "8", "White") == 4
    resolution = json.loads(service.get_customer_view(return_id)["service_resolution_json"])
    assert resolution["resolution"] == "RESHIP" and resolution["status"] == "RESHIP_RELEASED_DEMO"
    assert resolution["item"] == {"sku": "SYN-RUNNER-110", "size": "8", "color": "White"}
    with pytest.raises(PolicyViolation):
        service.submit_photos(return_id, "eligible_a_95")


def test_reship_requires_an_offered_option(service):
    return_id, _ = _recommend(service, "SYN-O-MISSING-001", "My item never arrived and is missing")
    with pytest.raises(ValidationError):
        service.record_decision(return_id, "RESHIP", "SYN-RUNNER-100|9|Blue|SYN-STORE-1")


def test_refund_on_out_of_stock_is_recorded_without_return(service):
    return_id, _ = _recommend(service, "SYN-O-OOS-001", "The shoes were out of stock and never shipped")
    result = service.record_decision(return_id, "REFUND")
    assert result["state"] == "COMPLETED_SERVICE"
    resolution = json.loads(service.get_customer_view(return_id)["service_resolution_json"])
    assert resolution["resolution"] == "REFUND_NOT_RECEIVED" and resolution["photos_required"] is False


@pytest.mark.parametrize(
    ("order_id", "reason", "decision"),
    [("SYN-O-DELAY-001", "shipping is delayed", "SERVICE_RESOLUTION"), ("SYN-O-SIZE-001", "too large", "EXCHANGE")],
)
def test_decision_that_was_not_offered_is_rejected(service, order_id, reason, decision):
    return_id, _ = _recommend(service, order_id, reason)
    with pytest.raises(ValidationError, match="not one of the offered choices"):
        service.record_decision(return_id, decision)
    assert service.get_customer_view(return_id)["state"] == "OPTIONS_READY"


def test_delivered_delay_refund_runs_the_normal_return_flow(service):
    return_id, _ = _recommend(service, "SYN-O-DELAY-001", "shipping is delayed")
    assert service.record_decision(return_id, "REFUND")["state"] == "AWAITING_PHOTOS"
    service.submit_photos(return_id, "eligible_a_95")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    service.route_return(return_id)
    artifact = service.generate_artifact(return_id)
    assert Path(artifact.local_path).exists()
    assert service.get_customer_view(return_id)["state"] == "COMPLETED_RETURN"


def test_late_and_too_small_exchange_completes(service):
    return_id, recommendation = _recommend(service, "SYN-O-SIZE-001", "They arrived late and are too small")
    option = next(option for option in recommendation["options"] if option["size"] == "9")
    service.record_decision(return_id, "EXCHANGE", option["option_id"])
    service.submit_photos(return_id, "eligible_a_95")
    service.select_fulfillment_mode(return_id, "SHIP")
    service.route_return(return_id)
    service.generate_artifact(return_id)
    assert service.complete_exchange(return_id)["state"] == "COMPLETED_EXCHANGE"
