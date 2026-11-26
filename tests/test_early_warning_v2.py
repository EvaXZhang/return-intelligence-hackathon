import json
from datetime import datetime, timezone

import pytest

from return_intelligence.db.connection import transaction
from return_intelligence.domain.early_warning_rules import THRESHOLDS, evaluate_thresholds
from return_intelligence.domain.errors import NotFoundError, PolicyViolation, ValidationError
from return_intelligence.integrations.lambda_handlers.early_warning import handler as warning_handler
from return_intelligence.integrations.strands_factory import _SPECIALIST_PROMPTS
from return_intelligence.services.supervisor import SupervisorService
from tests.conftest import advance_to_photos
from tests.fakes import FakeLiveProvider


def _alerts(repo):
    return repo.all("SELECT * FROM early_warning_alerts ORDER BY created_at,alert_id")


def _fifth_too_small(service, order="SYN-O-SIZE-001"):
    rid = service.start_return(order)["return_id"]
    options = service.submit_reason(rid, "The shoes are too small")["recommendation"]["options"]
    service.record_decision(rid, "EXCHANGE", options[0]["option_id"])
    return rid


def _add_history(repo, size, count, category="Quality Issue", detail="sole_separation", prefix="T"):
    with transaction(repo.db_path, True) as connection:
        for index in range(count):
            connection.execute(
                "INSERT INTO historical_complaints VALUES(?,?,?,?,?,?,?,?, 'SYNTHETIC')",
                (f"SYN-HC-{prefix}{size}-{index}", "2025-12-20T12:00:00+00:00", "SYN-RUNNER-100", size, "Blue",
                 "SYN-B-SYN-RUNNER-100", category, detail),
            )


def test_rule_module_thresholds_and_baseline_fallback():
    assert THRESHOLDS["version"] == "v2" and THRESHOLDS["window_days"] == 90
    with_baseline = evaluate_thresholds(5, 25, 1, 100)
    assert with_baseline["alerted"] and with_baseline["baseline_available"] and with_baseline["lift"] == pytest.approx(20)
    flat = evaluate_thresholds(5, 25, 20, 100)
    assert not flat["alerted"] and flat["lift"] == pytest.approx(1)
    no_baseline = evaluate_thresholds(5, 25, 0, 100)
    assert no_baseline["alerted"] and no_baseline["baseline_available"] is False and no_baseline["lift"] is None
    assert not evaluate_thresholds(4, 25, 0, 0)["alerted"]
    assert not evaluate_thresholds(5, 0, 0, 0)["alerted"]


def test_default_fifth_complaint_raises_exactly_one_sku_size_alert(service, repo):
    _fifth_too_small(service)
    alerts = _alerts(repo)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["dimension_type"] == "SKU_SIZE" and alert["dimension_value"] == "SYN-RUNNER-100|8"
    assert (alert["complaint_count"], alert["units_sold"]) == (5, 25)
    assert alert["baseline_rate"] == pytest.approx(0.01) and alert["lift"] == pytest.approx(20)
    assert (alert["window_start"], alert["window_end"]) == ("2025-10-17", "2026-01-15")
    assert alert["alert_id"].endswith("-20260115") and alert["status"] == "OPEN"
    assert "not a confirmed defect" in alert["recommendation"].lower()
    evidence = json.loads(alert["evidence_json"])
    assert evidence["level"] == "SKU_SIZE" and evidence["baseline_available"] is True
    assert evidence["model_id"] == "SYN-MODEL-RUNNER" and evidence["similar_group"] == "RUNNER"
    assert evidence["product_name"] == "Everyday Runner" and evidence["baseline_basis"] == "same SKU, other sizes"
    assert (evidence["historical_count"], evidence["current_count"]) == (4, 1)


def test_same_rate_across_all_sizes_raises_model_alert_only(service, repo):
    _add_history(repo, "8", 4)
    _add_history(repo, "9", 20)
    advance_to_photos(service, "SYN-O-SIZE-001", "The sole is coming apart, quality issue", "REFUND")
    alerts = _alerts(repo)
    assert [alert["dimension_type"] for alert in alerts] == ["MODEL"]
    alert = alerts[0]
    assert alert["dimension_value"] == "SYN-MODEL-RUNNER" and alert["category"] == "Quality Issue"
    assert alert["detail_code"] == "sole_separation"
    assert (alert["complaint_count"], alert["units_sold"]) == (25, 125)
    evidence = json.loads(alert["evidence_json"])
    assert evidence["baseline_available"] is False and evidence["level"] == "MODEL"
    assert evidence["baseline_basis"] == "other models in similar group RUNNER"
    assert alert["baseline_rate"] == 0 and alert["lift"] == 0


def test_no_comparable_baseline_still_alerts_on_count_and_rate(service, repo):
    _add_history(repo, "8", 4)
    advance_to_photos(service, "SYN-O-SIZE-001", "The sole is coming apart, quality issue", "REFUND")
    alerts = _alerts(repo)
    assert len(alerts) == 1 and alerts[0]["dimension_type"] == "SKU_SIZE"
    assert json.loads(alerts[0]["evidence_json"])["baseline_available"] is False
    assert (alerts[0]["complaint_count"], alerts[0]["units_sold"]) == (5, 25)


def test_every_label_of_a_multi_label_request_is_evaluated(service, repo):
    rid = service.start_return("SYN-O-SIZE-001")["return_id"]
    options = service.submit_reason(rid, "Too small and the sole is broken")["recommendation"]["options"]
    service.record_decision(rid, "EXCHANGE", options[0]["option_id"])
    alerts = _alerts(repo)
    assert [(alert["category"], alert["dimension_type"]) for alert in alerts] == [("Wrong Size", "SKU_SIZE")]
    evaluations = service.warning.evaluate(rid)
    assert {(value.category, value.level) for value in evaluations} == {
        ("Quality Issue", "SKU_SIZE"), ("Quality Issue", "MODEL"), ("Wrong Size", "SKU_SIZE"), ("Wrong Size", "MODEL"),
    }


def test_window_follows_the_business_clock(repo, tmp_path):
    july = SupervisorService(repo, tmp_path / "artifacts", "WINTER", clock=lambda: datetime(2026, 7, 1, 12, tzinfo=timezone.utc))
    _fifth_too_small(july)
    assert _alerts(repo) == []
    assert july.warning.window() == ("2026-04-02", "2026-07-01")


def test_complaints_outside_the_window_are_ignored(service, repo):
    with transaction(repo.db_path, True) as connection:
        connection.execute("UPDATE historical_complaints SET occurred_at='2025-06-01T12:00:00+00:00' WHERE complaint_id='SYN-HC-4'")
    _fifth_too_small(service)
    assert _alerts(repo) == []


def test_differently_worded_live_details_group_under_one_code(repo, tmp_path):
    returns = []
    for order, wording in (("SYN-O-SIZE-001", "sole peeling away"), ("SYN-O-A95-001", "Sole separation near toe")):
        provider = FakeLiveProvider(
            reason={"categories": ["Quality Issue"], "details": {"quality_symptom": wording}, "customer_summary": "Sole issue."}
        )
        live = SupervisorService(repo, tmp_path / "artifacts", "WINTER", provider=provider)
        returns.append(advance_to_photos(live, order, "The sole is coming off", "REFUND"))
    codes = {row["detail_code"] for row in repo.all("SELECT detail_code FROM complaint_event_labels")}
    assert codes == {"sole_separation"}
    evaluation = next(value for value in live.warning.evaluate(returns[-1]) if value.level == "SKU_SIZE")
    assert evaluation.detail_code == "sole_separation" and evaluation.complaint_count == 2


def test_sixth_complaint_updates_the_active_alert_without_a_second_ai_call(service, repo, monkeypatch):
    calls = []
    original = service.provider.explain_alert
    monkeypatch.setattr(service.provider, "explain_alert", lambda facts: calls.append(facts) or original(facts))
    _fifth_too_small(service)
    _fifth_too_small(service, "SYN-O-UNCLEAR-001")
    alerts = _alerts(repo)
    assert len(alerts) == 1 and alerts[0]["complaint_count"] == 6 and alerts[0]["updated_at"]
    assert len(calls) == 1 and calls[0]["level"] == "SKU_SIZE" and calls[0]["baseline_available"] is True


def test_lambda_handler_reuses_the_shared_rule():
    assert warning_handler({"complaint_count": 5, "units_sold": 25, "baseline_rate": 0})["body"]["alerted"] is True
    assert warning_handler({"complaint_count": 4, "units_sold": 25, "baseline_rate": 0})["body"]["alerted"] is False
    assert warning_handler({"complaint_count": 5, "units_sold": 0, "baseline_rate": 0})["body"]["alerted"] is False
    assert warning_handler({"complaint_count": 5, "units_sold": 25, "baseline_rate": 0.15})["body"]["alerted"] is False


def test_early_warning_prompt_handles_missing_baseline_and_levels():
    prompt = _SPECIALIST_PROMPTS["early_warning"]
    assert "baseline_available is false" in prompt and "SKU_SIZE" in prompt and "MODEL" in prompt
    assert "Never state or imply that an anomaly proves a manufacturing defect" in prompt


def test_alert_status_moves_open_investigating_closed_with_audit_rows(service, repo):
    _fifth_too_small(service)
    alert_id = _alerts(repo)[0]["alert_id"]
    investigating = service.update_alert_status(alert_id, "INVESTIGATING", "STAFF-1", "checking the last 2 batches")
    assert investigating["status"] == "INVESTIGATING" and investigating["status_updated_by"] == "STAFF-1"
    closed = service.update_alert_status(alert_id, "CLOSED", "STAFF-2")
    assert closed["status"] == "CLOSED" and closed["status_updated_at"]
    history = repo.alert_status_history(alert_id)
    assert [(row["from_status"], row["to_status"], row["changed_by"]) for row in history] == [
        ("OPEN", "INVESTIGATING", "STAFF-1"), ("INVESTIGATING", "CLOSED", "STAFF-2"),
    ]
    assert history[0]["note"] == "checking the last 2 batches" and history[1]["note"] is None
    for target in ("OPEN", "INVESTIGATING", "CLOSED"):
        with pytest.raises(PolicyViolation):
            service.update_alert_status(alert_id, target, "STAFF-1")


def test_alert_status_rejects_skips_unknown_ids_and_bad_input(service, repo):
    _fifth_too_small(service)
    alert_id = _alerts(repo)[0]["alert_id"]
    with pytest.raises(PolicyViolation):
        service.update_alert_status(alert_id, "CLOSED", "STAFF-1")
    with pytest.raises(NotFoundError):
        service.update_alert_status("SYN-ALERT-UNKNOWN", "INVESTIGATING", "STAFF-1")
    with pytest.raises(ValidationError):
        service.update_alert_status(alert_id, "INVESTIGATING", "   ")
    with pytest.raises(ValidationError):
        service.update_alert_status(alert_id, "INVESTIGATING", "STAFF-1", "x" * 501)
    assert repo.alert_status_history(alert_id) == [] and repo.alert(alert_id)["status"] == "OPEN"


def test_closed_alert_is_not_re_raised_in_the_same_window(service, repo):
    _fifth_too_small(service)
    alert_id = _alerts(repo)[0]["alert_id"]
    service.update_alert_status(alert_id, "INVESTIGATING", "STAFF-1")
    service.update_alert_status(alert_id, "CLOSED", "STAFF-1")
    _fifth_too_small(service, "SYN-O-UNCLEAR-001")
    alerts = _alerts(repo)
    assert len(alerts) == 1 and alerts[0]["status"] == "CLOSED" and alerts[0]["complaint_count"] == 5


def test_flags_follow_active_alerts_only(service, repo):
    assert repo.flagged_series() == []
    _fifth_too_small(service)
    alert_id = _alerts(repo)[0]["alert_id"]
    flags = repo.flagged_series()
    assert [flag["model_id"] for flag in flags] == ["SYN-MODEL-RUNNER"]
    assert flags[0]["alert_ids"] == [alert_id] and flags[0]["product_names"] == ["Everyday Runner"]
    service.update_alert_status(alert_id, "INVESTIGATING", "STAFF-1")
    assert [flag["model_id"] for flag in repo.flagged_series()] == ["SYN-MODEL-RUNNER"]
    service.update_alert_status(alert_id, "CLOSED", "STAFF-1")
    assert repo.flagged_series() == []
    assert service.get_staff_view()["flags"] == []


def test_legacy_model_size_alert_is_flagged_and_updated_by_fingerprint(service, repo):
    import hashlib

    fingerprint = hashlib.sha256(b"SYN-RUNNER-100|8|Wrong Size|too_small").hexdigest()[:24]
    with transaction(repo.db_path, True) as connection:
        connection.execute(
            "INSERT INTO early_warning_alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
            (f"SYN-ALERT-{fingerprint}", fingerprint, "2025-10-17", "2026-01-15", "MODEL_SIZE", "SYN-MODEL-RUNNER|8",
             "Wrong Size", "too_small", 5, 25, 0.2, 0.01, 20.0, "{}", '{"return_id":"SYN-R-OLD","synthetic_history":4}',
             "Legacy suspected pattern; not a confirmed defect.", "OPEN", "2026-01-15T12:00:00+00:00"),
        )
    assert [flag["model_id"] for flag in repo.flagged_series()] == ["SYN-MODEL-RUNNER"]
    _fifth_too_small(service)
    alerts = _alerts(repo)
    assert len(alerts) == 1 and alerts[0]["alert_id"] == f"SYN-ALERT-{fingerprint}"
    assert alerts[0]["dimension_type"] == "SKU_SIZE" and alerts[0]["dimension_value"] == "SYN-RUNNER-100|8"
