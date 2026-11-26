"""Staff authority: lifecycle report (D7), reservation release + defect-hold resolution (F3),
final-destination decision (D2) and the next-nearest drop-off store (D1 robustness)."""
import json
from pathlib import Path

import pytest

from return_intelligence.db.connection import transaction
from return_intelligence.domain.errors import PolicyViolation, ValidationError
from return_intelligence.services.supervisor import SupervisorService
from tests.conftest import advance_to_photos

STAFF = "STAFF-DEMO-1"


def _inventory(repo, option):
    return repo.one(
        "SELECT on_hand,reserved FROM inventory WHERE sku=? AND size=? AND color=? AND destination_id=?",
        (option["sku"], option["size"], option["color"], option["destination_id"]),
    )


def _exchange(service, fixture=None):
    """SYN-O-SIZE-001 exchange for the size-9 option; returns (return_id, option)."""
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    option = service.submit_reason(return_id, "The shoes are too small")["recommendation"]["options"][0]
    assert option["size"] == "9"
    service.record_decision(return_id, "EXCHANGE", option["option_id"])
    if fixture:
        service.submit_photos(return_id, fixture)
    return return_id, option


def _latest_exchange(repo, return_id):
    row = repo.one(
        "SELECT selected_option_json FROM decision_events WHERE return_id=? AND decision='EXCHANGE' ORDER BY created_at DESC LIMIT 1",
        (return_id,),
    )
    return json.loads(row["selected_option_json"])


def _defect_hold(service, decision="REFUND"):
    if decision == "EXCHANGE":
        return_id, _ = _exchange(service, "suspected_defect")
    else:
        return_id = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
        service.submit_photos(return_id, "suspected_defect")
    assert service.repo.get_return(return_id)["state"] == "DEFECT_HOLD"
    return return_id


def _routed_b_refund_dropoff(service):
    return_id = advance_to_photos(service, "SYN-O-B-001", "I prefer another style", "REFUND")
    service.submit_photos(return_id, "eligible_75")
    service.resolve_review(return_id, "APPROVE")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    assert service.route_return(return_id)["state"] == "ROUTED"
    return return_id


# ---- Item 9: lifecycle -------------------------------------------------------------------------


def test_lifecycle_is_staff_only(repo, tmp_path):
    service = SupervisorService(repo, tmp_path / "artifacts", None)
    return_id = advance_to_photos(service, "SYN-O-SANDAL-001", "wrong color")
    service.submit_photos(return_id, "eligible_a_95")
    lifecycle = service.get_staff_view(return_id)["request"]["latest_assessment"]["lifecycle"]
    assert lifecycle["current_season"] == "WINTER" and lifecycle["season_source"] == "clock"
    assert lifecycle["as_of"] == "2026-01-15"
    assert lifecycle["product_season_profile"] == "SUMMER"
    assert lifecycle["in_season"] is False and lifecycle["seasonality_flag"] == 1 and lifecycle["reason"]
    activity = next(a for a in repo.activities(return_id) if a["action"] == "VISUAL_EVIDENCE_ASSESSED")
    assert json.loads(activity["output_json"])["lifecycle"] == lifecycle

    customer = service.get_customer_view(return_id)
    assert customer["latest_assessment"]["lifecycle_json"] is None
    assert "lifecycle" not in customer["latest_assessment"]
    assert customer["seasonality_flag"] is None
    assert lifecycle["reason"] not in json.dumps(customer, default=str)


def test_retake_records_no_lifecycle(service, repo):
    return_id = advance_to_photos(service, "SYN-O-UNCLEAR-001")
    service.submit_photos(return_id, "unclear")
    assert service.get_staff_view(return_id)["request"]["latest_assessment"]["lifecycle"] is None


# ---- Item 9: reservation release -------------------------------------------------------------


def test_worn_auto_close_releases_exchange_reservation(service, repo):
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    option = service.submit_reason(return_id, "The shoes are too small")["recommendation"]["options"][0]
    before = _inventory(repo, option)
    service.record_decision(return_id, "EXCHANGE", option["option_id"])
    assert _inventory(repo, option)["reserved"] == before["reserved"] + 1
    assert service.submit_photos(return_id, "worn_ineligible")["state"] == "INELIGIBLE_CLOSED"
    assert _inventory(repo, option) == before
    exchange = _latest_exchange(repo, return_id)
    assert exchange["exchange_status"] == "RESERVATION_RELEASED_NOT_PROCEEDING" and exchange["released_at"]


def test_staff_worn_review_releases_exchange_reservation(service, repo):
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    option = service.submit_reason(return_id, "The shoes are too small")["recommendation"]["options"][0]
    before = _inventory(repo, option)
    service.record_decision(return_id, "EXCHANGE", option["option_id"])
    service.submit_photos(return_id, "worn_low_confidence")
    assert service.resolve_review(return_id, "APPROVE")["state"] == "INELIGIBLE_CLOSED"
    assert _inventory(repo, option) == before
    assert _latest_exchange(repo, return_id)["exchange_status"] == "RESERVATION_RELEASED_NOT_PROCEEDING"


def test_review_resolution_records_staff_id_from_staff_controls(service, repo):
    return_id = advance_to_photos(service, "SYN-O-LOW75-001")
    service.submit_photos(return_id, "eligible_75")
    with pytest.raises(ValidationError):
        service.resolve_review(return_id, "APPROVE", staff_id="  ")
    assert service.resolve_review(return_id, "APPROVE", staff_id=STAFF)["state"] == "READY_TO_ROUTE"
    activity = next(a for a in repo.activities(return_id) if a["action"] == "STAFF_REVIEW_RESOLVED")
    assert json.loads(activity["input_json"])["staff_id"] == STAFF


# ---- Item 9: defect-hold resolution ----------------------------------------------------------


def test_confirmed_defect_releases_reserved_replacement_and_is_never_routed(service, repo):
    return_id, option = _exchange(service)
    reserved = _inventory(repo, option)
    service.submit_photos(return_id, "suspected_defect")
    assert service.repo.get_return(return_id)["state"] == "DEFECT_HOLD"
    assert _inventory(repo, option) == reserved
    row = service.resolve_defect_hold(return_id, "CONFIRMED_DEFECT", STAFF, note="Sole gap confirmed on photos")
    assert row["state"] == "DEFECT_RESOLVED" and row["condition_state"] == "SUSPECTED_DEFECT"
    resolution = json.loads(row["service_resolution_json"])
    assert resolution["resolution"] == "CONFIRMED_DEFECT_REPLACEMENT" and resolution["resale"] is False
    assert resolution["replacement"] == {"sku": option["sku"], "size": "9", "color": option["color"]}
    assert resolution["decided_by"] == STAFF
    after = _inventory(repo, option)
    assert after["on_hand"] == reserved["on_hand"] - 1 and after["reserved"] == reserved["reserved"] - 1
    assert _latest_exchange(repo, return_id)["exchange_status"] == "REPLACEMENT_RELEASED_DEMO"
    assert repo.route(return_id) is None
    with pytest.raises(PolicyViolation):
        service.generate_artifact(return_id)
    with pytest.raises(PolicyViolation):
        service.route_return(return_id)
    activity = next(a for a in repo.activities(return_id) if a["action"] == "DEFECT_HOLD_RESOLVED")
    assert json.loads(activity["input_json"]) == {
        "resolution": "CONFIRMED_DEFECT",
        "staff_id": STAFF,
        "note_present": True,
        "note_length": len("Sole gap confirmed on photos"),
    }
    assert json.loads(activity["output_json"]) == {"state": "DEFECT_RESOLVED", "outcome": "CONFIRMED_DEFECT_REPLACEMENT"}


def test_confirmed_defect_on_refund_records_refund(service):
    return_id = _defect_hold(service)
    row = service.resolve_defect_hold(return_id, "CONFIRMED_DEFECT", STAFF)
    assert row["state"] == "DEFECT_RESOLVED"
    assert json.loads(row["service_resolution_json"])["resolution"] == "CONFIRMED_DEFECT_REFUND"


def test_not_defect_requires_a_grade(service):
    return_id = _defect_hold(service)
    with pytest.raises(ValidationError):
        service.resolve_defect_hold(return_id, "NOT_DEFECT", STAFF)
    with pytest.raises(ValidationError):
        service.resolve_defect_hold(return_id, "NOT_DEFECT", STAFF, grade="D")
    with pytest.raises(ValidationError):
        service.resolve_defect_hold(return_id, "NOT_DEFECT", "", grade="B")
    with pytest.raises(ValidationError):
        service.resolve_defect_hold(return_id, "MAYBE", STAFF)
    assert service.repo.get_return(return_id)["state"] == "DEFECT_HOLD"


def test_not_defect_grade_b_refund_completes_normal_return(service):
    return_id = _defect_hold(service)
    row = service.resolve_defect_hold(return_id, "NOT_DEFECT", STAFF, grade="B")
    assert row["state"] == "READY_TO_ROUTE" and row["final_grade"] == "B"
    assert row["condition_state"] == "ELIGIBLE_UNWORN" and row["preliminary_grade"] is None
    service.select_fulfillment_mode(return_id, "DROPOFF")
    route = service.route_return(return_id)
    assert route["state"] == "ROUTED" and route["decision"]["return_fee"] == 0.0
    service.generate_artifact(return_id)
    assert service.get_customer_view(return_id)["state"] == "COMPLETED_RETURN"


def test_not_defect_grade_b_exchange_keeps_reservation_and_completes_exchange(service, repo):
    return_id, option = _exchange(service)
    reserved = _inventory(repo, option)
    service.submit_photos(return_id, "suspected_defect")
    service.resolve_defect_hold(return_id, "NOT_DEFECT", STAFF, grade="B")
    assert _inventory(repo, option) == reserved
    service.select_fulfillment_mode(return_id, "DROPOFF")
    service.route_return(return_id)
    service.generate_artifact(return_id)
    assert service.get_customer_view(return_id)["state"] == "AWAITING_ORIGINAL_RETURN"
    assert service.complete_exchange(return_id)["state"] == "COMPLETED_EXCHANGE"


def test_resolving_a_non_hold_is_rejected(service):
    return_id = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    service.submit_photos(return_id, "eligible_a_95")
    with pytest.raises(PolicyViolation):
        service.resolve_defect_hold(return_id, "CONFIRMED_DEFECT", STAFF)


# ---- Item 10: staff final destination --------------------------------------------------------


def test_pending_then_confirm_suggestion_without_reason(service, repo):
    return_id = _routed_b_refund_dropoff(service)
    final = service.get_staff_view(return_id)["final_destination"]
    assert final["status"] == "PENDING_STAFF_DECISION" and final["decision"] is None
    assert final["suggested"]["type"] == "OUTLET" and final["suggested"]["name"]
    decided = service.decide_destination(return_id, final["suggested"]["id"], STAFF)
    assert decided["status"] == "STAFF_DECIDED"
    assert decided["decision"]["deviates_from_suggestion"] == 0 and decided["decision"]["decided_by"] == STAFF


def test_deviation_needs_reason_and_latest_decision_wins(service, repo):
    return_id = _routed_b_refund_dropoff(service)
    before = repo.get_return(return_id)
    route_before = repo.route(return_id)
    suggested = route_before["destination_id"]
    service.decide_destination(return_id, suggested, STAFF)
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, "SYN-WH-1", STAFF)
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, "SYN-WH-1", STAFF, "   ")
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, "SYN-WH-1", STAFF, "x" * 501)
    decided = service.decide_destination(return_id, "SYN-WH-1", "STAFF-DEMO-2", "Packaging damaged at intake")
    assert decided["status"] == "STAFF_DECIDED"
    decision = decided["decision"]
    assert decision["chosen_destination_id"] == "SYN-WH-1" and decision["chosen_destination_type"] == "COMPANY_WAREHOUSE"
    assert decision["deviates_from_suggestion"] == 1 and decision["reason"] == "Packaging damaged at intake"
    assert decision["suggested_destination_id"] == suggested and decision["decided_by"] == "STAFF-DEMO-2"
    assert decision["chosen_destination_name"] == "Synthetic Company Warehouse"
    assert repo.one("SELECT count(*) n FROM staff_destination_decisions WHERE return_id=?", (return_id,))["n"] == 2

    # The suggestion, routes row and state are never changed by a staff decision.
    after = repo.get_return(return_id)
    for column in ("state", "destination_type", "selected_destination_id", "routing_reason", "version"):
        assert after[column] == before[column]
    assert repo.route(return_id) == route_before

    entries = [a for a in repo.activities(return_id) if a["action"] == "STAFF_DESTINATION_DECIDED"]
    assert len(entries) == 2
    assert json.loads(entries[-1]["input_json"]) == {
        "suggested_destination_id": suggested,
        "chosen_destination_id": "SYN-WH-1",
        "deviates": True,
        "reason_present": True,
        "reason_length": len("Packaging damaged at intake"),
    }
    assert json.loads(entries[-1]["output_json"]) == {
        "final_destination_id": "SYN-WH-1",
        "final_destination_type": "COMPANY_WAREHOUSE",
    }


def test_customer_never_sees_staff_destination_decision(service):
    return_id = _routed_b_refund_dropoff(service)
    service.decide_destination(return_id, "SYN-WH-1", STAFF, "Overflow at outlet")
    customer = service.get_customer_view(return_id)
    assert "final_destination" not in customer
    text = json.dumps(customer, default=str)
    assert "SYN-WH-1" not in text and "Overflow at outlet" not in text and "Warehouse" not in text
    artifact = service.generate_artifact(return_id)
    assert b"Warehouse" not in Path(artifact.local_path).read_bytes()


def test_exchange_completes_without_decision_and_decision_after_completion_is_allowed(service):
    return_id, _ = _exchange(service, "eligible_a_95")
    service.select_fulfillment_mode(return_id, "SHIP")
    service.route_return(return_id)
    service.generate_artifact(return_id)
    assert service.complete_exchange(return_id)["state"] == "COMPLETED_EXCHANGE"
    assert service.final_destination(return_id)["status"] == "PENDING_STAFF_DECISION"
    assert service.decide_destination(return_id, "SYN-OUTLET-2", STAFF, "Store overstocked")["status"] == "STAFF_DECIDED"
    assert service.repo.get_return(return_id)["state"] == "COMPLETED_EXCHANGE"


def test_deciding_before_routing_or_for_worn_and_defect_is_rejected(service):
    worn = advance_to_photos(service, "SYN-O-WORN-001")
    service.submit_photos(worn, "worn_ineligible")
    hold = _defect_hold(service)
    resolved = _defect_hold(service)
    service.resolve_defect_hold(resolved, "CONFIRMED_DEFECT", STAFF)
    ready = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    service.submit_photos(ready, "eligible_a_95")
    for return_id in (worn, hold, resolved, ready):
        assert service.final_destination(return_id)["status"] == "NOT_APPLICABLE"
        with pytest.raises(PolicyViolation):
            service.decide_destination(return_id, "SYN-WH-1", STAFF, "reason")


def test_inactive_or_unknown_destination_is_rejected(service, repo):
    return_id = _routed_b_refund_dropoff(service)
    with transaction(repo.db_path, True) as connection:
        connection.execute("UPDATE destinations SET active=0 WHERE destination_id='SYN-OUTLET-2'")
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, "SYN-OUTLET-2", STAFF, "reason")
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, "SYN-NOPE", STAFF, "reason")
    with pytest.raises(ValidationError):
        service.decide_destination(return_id, repo.route(return_id)["destination_id"], "x" * 65)


# ---- Item 10: next-nearest drop-off store ----------------------------------------------------


def _fill(repo, destination_id):
    with transaction(repo.db_path, True) as connection:
        connection.execute(
            "UPDATE destinations SET current_load_units=capacity_units WHERE destination_id=?", (destination_id,)
        )


def test_full_nearest_store_falls_back_to_next_nearest_dropoff_store(service, repo):
    _fill(repo, "SYN-STORE-1")
    return_id = advance_to_photos(service, "SYN-O-B-001", "I prefer another style", "REFUND")
    service.submit_photos(return_id, "eligible_75")
    service.resolve_review(return_id, "APPROVE")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    route = service.route_return(return_id)
    assert route["state"] == "ROUTED"
    assert route["decision"]["intake_location_id"] == "SYN-STORE-2" and route["decision"]["return_fee"] == 0.0
    assert service.get_customer_view(return_id)["return_store_name"] == "ALDO North Demo Store"


def test_all_dropoff_stores_full_blocks_routing(service, repo):
    _fill(repo, "SYN-STORE-1")
    _fill(repo, "SYN-STORE-2")
    return_id = advance_to_photos(service, "SYN-O-B-001", "I prefer another style", "REFUND")
    service.submit_photos(return_id, "eligible_75")
    service.resolve_review(return_id, "APPROVE")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    assert service.route_return(return_id)["state"] == "ROUTING_BLOCKED"
