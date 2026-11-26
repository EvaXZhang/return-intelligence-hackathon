import json
from pathlib import Path

import pytest

from return_intelligence.agents import fulfillment as fulfillment_module
from return_intelligence.services.customer_copy import (
    FORBIDDEN_CUSTOMER_TERMS,
    RETURN_METHOD_NOTE,
    compose_solution_email,
    customer_safe,
    is_customer_safe,
    recipient_for,
)
from tests.conftest import advance_to_photos
from tests.fakes import FakeLiveProvider

INTERNAL_PDF_TERMS = (b"Outlet", b"Warehouse", b"SYN-OUTLET", b"SYN-WH")
STAFF_FIELDS = (
    "categories",
    "detail_codes",
    "resolution_path",
    "recommended_action",
    "offered_options",
    "allowed_choices",
    "customer_message_id",
    "customer_final_decision",
    "selected_option",
    "decided_at",
)


def _messages(repo, return_id):
    return repo.all("SELECT * FROM customer_messages WHERE return_id=?", (return_id,))


def test_submit_reason_sends_one_mock_email(service, repo):
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    service.submit_reason(return_id, "The shoes are too small")
    messages = _messages(repo, return_id)
    assert len(messages) == 1
    message = messages[0]
    assert (message["channel"], message["status"], message["message_type"]) == ("EMAIL", "MOCK_SENT", "SOLUTION")
    assert message["recipient"] == "customer-syn-o-size-001@example.test" == recipient_for("SYN-O-SIZE-001")
    assert "SYN-RUNNER-100 · size 9 · Blue" in message["body"]
    assert "FREE" in message["body"] and RETURN_METHOD_NOTE in message["body"]
    assert "nothing was actually sent" in message["body"]
    assert is_customer_safe(message["subject"]) and is_customer_safe(message["body"])
    actions = [row["action"] for row in repo.activities(return_id)]
    assert actions.count("CUSTOMER_MESSAGE_MOCK_SENT") == 1


def test_email_omits_return_note_when_nothing_is_returned():
    recommendation = {
        "resolution_path": "MISSING_ITEM",
        "choices": ["RESHIP", "REFUND"],
        "recommended_action": "RESHIP",
        "options": [{"sku": "SYN-RUNNER-110", "size": "8", "color": "White"}],
        "explanation": "We can reship it.",
    }
    _, body = compose_solution_email("SYN-R-1", "SYN-O-MISSING-001", {"categories": []}, recommendation)
    assert RETURN_METHOD_NOTE not in body and "Reship the missing item" in body


def test_staff_copy_is_complete_before_and_after_the_decision(service):
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    service.submit_reason(return_id, "The shoes are too small")
    before = service.get_staff_view(return_id)["staff_solution"]
    assert set(STAFF_FIELDS) <= set(before)
    assert before["categories"] == ["Wrong Size"] and before["detail_codes"] == {"size_direction": "too_small"}
    assert before["recommended_action"] == "EXCHANGE" and before["resolution_path"] == "NORMAL"
    assert before["offered_options"] and all(option["destination_id"] for option in before["offered_options"])
    assert before["customer_message_id"] and before["customer_final_decision"] is None
    option = before["offered_options"][0]
    service.record_decision(return_id, "EXCHANGE", option["option_id"])
    after = service.get_staff_view(return_id)["staff_solution"]
    assert set(STAFF_FIELDS) <= set(after)
    assert after["customer_final_decision"] == "EXCHANGE" and after["decided_at"]
    assert after["selected_option"]["option_id"] == option["option_id"]


def test_customer_view_strips_staff_fields(service):
    return_id = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    service.submit_photos(return_id, "eligible_a_95")
    service.select_fulfillment_mode(return_id, "SHIP")
    service.route_return(return_id)
    customer = service.get_customer_view(return_id)
    assert customer["staff_solution_json"] is None and customer["staff_solution"] is None
    assert customer["seasonality_flag"] is None
    assert len(customer["messages"]) == 1
    staff = service.get_staff_view(return_id)
    assert staff["request"]["staff_solution_json"] and staff["staff_solution"]["customer_final_decision"] == "REFUND"
    assert staff["request"]["seasonality_flag"] == 0


def test_customer_safe_guard():
    for term in FORBIDDEN_CUSTOMER_TERMS:
        assert not is_customer_safe(f"Your shoes go to the {term.upper()} next")
    assert customer_safe("Bring them to the ALDO Downtown Demo Store.", "fallback") == "Bring them to the ALDO Downtown Demo Store."
    assert customer_safe("Sent to Synthetic Outlet East", "fallback") == "fallback"
    assert customer_safe("", "fallback") == "fallback"


def test_ai_texts_naming_internal_destinations_are_replaced(service, repo):
    fake = FakeLiveProvider(
        recommendation="Exchange now; your old pair goes to Synthetic Outlet East.",
        fulfillment="Ship it and we forward it to the Synthetic Company Warehouse.",
    )
    service.retention.provider = fake
    service.fulfillment.provider = fake
    return_id = advance_to_photos(service, "SYN-O-B-001", "I prefer another style")
    service.submit_photos(return_id, "eligible_75")
    service.resolve_review(return_id, "APPROVE")
    service.select_fulfillment_mode(return_id, "SHIP")
    assert service.route_return(return_id)["decision"]["destination_type"] == "OUTLET"
    artifact = service.generate_artifact(return_id)
    view = service.get_customer_view(return_id)
    texts = [view["recommendation"]["explanation"], view["messages"][0]["body"], artifact.customer_instructions]
    for text in texts:
        assert "Outlet" not in text and "Warehouse" not in text and is_customer_safe(text)
    assert "ALDO Downtown Demo Store" in artifact.customer_instructions
    pdf = Path(artifact.local_path).read_bytes()
    assert not any(term in pdf for term in INTERNAL_PDF_TERMS)
    assert b"Free alternative: drop off at this store." in pdf


def test_dropoff_qr_payload_has_no_destination(service, monkeypatch):
    payloads = []
    real_make = fulfillment_module.qrcode.make

    def capture(payload, *args, **kwargs):
        payloads.append(payload)
        return real_make(payload, *args, **kwargs)

    monkeypatch.setattr(fulfillment_module.qrcode, "make", capture)
    return_id = advance_to_photos(service, "SYN-O-C-001", "I prefer another style")
    service.submit_photos(return_id, "eligible_75")
    service.resolve_review(return_id, "OVERRIDE_C")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    route = service.route_return(return_id)
    artifact = service.generate_artifact(return_id)
    assert len(payloads) == 1 and payloads[0].startswith("LOCAL-DEMO:")
    assert route["decision"]["destination_id"] not in payloads[0] and is_customer_safe(payloads[0])
    # PDF string syntax escapes parentheses: "FREE (recommended)" is stored as "FREE \(recommended\)".
    assert rb"FREE \(recommended\)" in Path(artifact.local_path).read_bytes()


_GRID_SCENARIOS = {
    "a_in_season": ("SYN-O-A95-001", "wrong color", "eligible_a_95", None),
    "a_off_season": ("SYN-O-SANDAL-001", "wrong color", "eligible_a_95", None),
    "grade_b": ("SYN-O-B-001", "I prefer another style", "eligible_75", "APPROVE"),
    "grade_c": ("SYN-O-C-001", "I prefer another style", "eligible_75", "OVERRIDE_C"),
}


_GRID = [
    (scenario, decision, mode)
    for scenario in _GRID_SCENARIOS
    for decision in ("REFUND", "EXCHANGE")
    for mode in ("SHIP", "DROPOFF")
    # The off-season sandal has no same-size alternative in stock, so only KEEP/REFUND are offered.
    if not (scenario == "a_off_season" and decision == "EXCHANGE")
]


def test_off_season_sandal_is_refund_only(service):
    return_id = service.start_return("SYN-O-SANDAL-001")["return_id"]
    assert service.submit_reason(return_id, "wrong color")["recommendation"]["choices"] == ["KEEP", "REFUND"]


@pytest.mark.parametrize(("scenario", "decision", "mode"), _GRID)
def test_grade_decision_method_grid_is_customer_safe(service, scenario, decision, mode):
    order_id, reason, fixture, resolution = _GRID_SCENARIOS[scenario]
    return_id = service.start_return(order_id)["return_id"]
    recommendation = service.submit_reason(return_id, reason)["recommendation"]
    assert decision in recommendation["choices"]
    option_id = recommendation["options"][0]["option_id"] if decision == "EXCHANGE" else None
    service.record_decision(return_id, decision, option_id)
    service.submit_photos(return_id, fixture)
    if resolution:
        service.resolve_review(return_id, resolution)
    assert service.available_fulfillment_modes(return_id) == ("SHIP", "DROPOFF")
    service.select_fulfillment_mode(return_id, mode)
    route = service.route_return(return_id)["decision"]
    assert route["intake_location_id"] == "SYN-STORE-1"
    assert route["return_fee"] == (9.0 if mode == "SHIP" else 0.0)
    artifact = service.generate_artifact(return_id)
    pdf = Path(artifact.local_path).read_bytes()
    assert b"ALDO Downtown Demo Store" in pdf
    assert not any(term in pdf for term in INTERNAL_PDF_TERMS)
    assert is_customer_safe(artifact.customer_instructions)
    view = service.get_customer_view(return_id)
    assert view["return_fee"] == route["return_fee"]
    assert is_customer_safe(json.dumps(view["messages"]))
