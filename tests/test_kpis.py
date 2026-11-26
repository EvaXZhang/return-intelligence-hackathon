import pytest

from return_intelligence.services.kpis import compute_kpis


def test_compute_kpis_rates():
    kpis = compute_kpis({"EXCHANGE": 2, "KEEP": 1, "REFUND": 1, "RESHIP": 3, "SERVICE_RESOLUTION": 2}, {"DROPOFF": 1, "SHIP": 3})
    assert (kpis["exchanges"], kpis["keeps"], kpis["refunds"], kpis["decided"]) == (2, 1, 1, 4)
    assert kpis["exchange_rate"] == pytest.approx(0.5)
    assert kpis["retention_rate"] == pytest.approx(0.75)
    assert kpis["dropoff_share"] == pytest.approx(0.25) and kpis["routes"] == 4


def test_compute_kpis_zero_denominators_are_none():
    kpis = compute_kpis({}, {})
    assert kpis["exchange_rate"] is None and kpis["retention_rate"] is None and kpis["dropoff_share"] is None
    only_service = compute_kpis({"RESHIP": 1, "SERVICE_RESOLUTION": 1}, {})
    assert only_service["decided"] == 0 and only_service["exchange_rate"] is None


def test_service_scenario_kpis(service, repo):
    # EXCHANGE + SHIP, routed.
    exchange = service.start_return("SYN-O-SIZE-001")["return_id"]
    options = service.submit_reason(exchange, "The shoes are too small")["recommendation"]["options"]
    service.record_decision(exchange, "EXCHANGE", options[0]["option_id"])
    service.submit_photos(exchange, "eligible_a_95")
    service.select_fulfillment_mode(exchange, "SHIP")
    assert service.route_return(exchange)["state"] == "ROUTED"
    # REFUND + DROPOFF, routed.
    refund = service.start_return("SYN-O-A95-001")["return_id"]
    service.submit_reason(refund, "wrong color")
    service.record_decision(refund, "REFUND")
    service.submit_photos(refund, "eligible_a_95")
    service.select_fulfillment_mode(refund, "DROPOFF")
    assert service.route_return(refund)["state"] == "ROUTED"
    # KEEP.
    keep = service.start_return("SYN-O-COLOR-001")["return_id"]
    service.submit_reason(keep, "wrong color")
    service.record_decision(keep, "KEEP")
    # REFUND for an item that never arrived (no route).
    missing = service.start_return("SYN-O-MISSING-001")["return_id"]
    service.submit_reason(missing, "My item never arrived and is missing")
    service.record_decision(missing, "REFUND")

    kpis = repo.kpis()
    assert (kpis["exchanges"], kpis["refunds"], kpis["keeps"]) == (1, 2, 1)
    assert kpis["exchange_rate"] == pytest.approx(0.25)
    assert kpis["retention_rate"] == pytest.approx(0.5)
    assert kpis["dropoff_share"] == pytest.approx(0.5)
    assert service.get_staff_view()["kpis"] == kpis
