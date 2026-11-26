import json
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from return_intelligence.agents.visual import VisualConditionAssessmentAgent
from return_intelligence.db.repositories import Repository
from return_intelligence.db.seed import seed_database
from return_intelligence.services.customer_copy import FORBIDDEN_CUSTOMER_TERMS
from return_intelligence.services.supervisor import SupervisorService
from return_intelligence.ui.customer import METHOD_LABELS, PHOTO_SCENARIO_LABELS, _service_text
from tests.conftest import advance_to_photos

APP = Path(__file__).parents[1] / "app.py"
# Percent figures such as 95% / 75% / 90% (a confidence in disguise) never belong on customer surfaces.
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


def _env(tmp_path, monkeypatch):
    """Simulated, offline environment with every writable path inside tmp_path."""
    monkeypatch.setenv("AI_BACKEND", "simulated")
    monkeypatch.setenv("AWS_INTEGRATION_ENABLED", "false")
    monkeypatch.setenv("DEPLOYMENT_ENABLED", "false")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "ui.db"))
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "logs" / "app.log"))


def _walk(node):
    yield node
    for child in getattr(node, "children", {}).values():
        yield from _walk(child)


def _page_text(app):
    """All rendered element protos joined, so assertions see every widget label and value."""
    return "\n".join(str(node.proto) for node in _walk(app._tree) if getattr(node, "proto", None) is not None)


def _assert_no_stray_none(app):
    assert not app.exception
    assert all(markdown.value != "`None`" for markdown in app.markdown)


def test_no_stray_none_on_customer_and_staff_pages(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    _assert_no_stray_none(app)
    assert "Customer Portal" in _page_text(app)

    next(button for button in app.button if button.label == "Start return").click().run()
    app.text_area[0].input("The shoes are too small and tight; I want a larger size").run()
    next(button for button in app.button if button.label == "Classify reason and show options").click().run()
    _assert_no_stray_none(app)
    assert "OPTIONS_READY" in _page_text(app)

    app.sidebar.radio[0].set_value("Staff Dashboard").run()
    _assert_no_stray_none(app)
    assert "Staff Dashboard" in _page_text(app)


def _drive_customer_states(tmp_path):
    """Drive one request into each customer-visible state on the same DB the AppTest app uses."""
    db = tmp_path / "data" / "ui.db"
    seed_database(db, tmp_path)
    service = SupervisorService(Repository(db), tmp_path / "artifacts", upload_root=tmp_path / "uploads")
    states = {}

    def start(order_id, reason):
        return_id = service.start_return(order_id)["return_id"]
        return return_id, service.submit_reason(return_id, reason)["recommendation"]

    states["OPTIONS_READY"], _ = start("SYN-O-SIZE-001", "The shoes are too small")

    # The photo step itself (and its retake) renders the simulated scenario selector.
    states["AWAITING_PHOTOS"] = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    return_id = advance_to_photos(service, "SYN-O-UNCLEAR-001")
    service.submit_photos(return_id, "unclear")
    states["RETAKE_REQUIRED"] = return_id

    return_id = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    service.submit_photos(return_id, "eligible_a_95")
    states["READY_TO_ROUTE"] = return_id

    for label, order_id, reason, fixture, resolution, mode in (
        ("ROUTED_B_DROPOFF", "SYN-O-B-001", "I prefer another style", "eligible_75", "APPROVE", "DROPOFF"),
        ("ROUTED_C_SHIP", "SYN-O-C-001", "I prefer another style", "eligible_75", "OVERRIDE_C", "SHIP"),
        ("ROUTED_SANDAL_SHIP", "SYN-O-SANDAL-001", "wrong color", "eligible_a_95", None, "SHIP"),
    ):
        return_id = advance_to_photos(service, order_id, reason)
        service.submit_photos(return_id, fixture)
        if resolution:
            service.resolve_review(return_id, resolution)
        service.select_fulfillment_mode(return_id, mode)
        assert service.route_return(return_id)["state"] == "ROUTED"
        states[label] = return_id

    for label in ("AWAITING_ORIGINAL_RETURN", "COMPLETED_EXCHANGE"):
        return_id, recommendation = start("SYN-O-SIZE-001", "The shoes are too small")
        service.record_decision(return_id, "EXCHANGE", recommendation["options"][0]["option_id"])
        service.submit_photos(return_id, "eligible_a_95")
        service.select_fulfillment_mode(return_id, "SHIP")
        service.route_return(return_id)
        service.generate_artifact(return_id)
        if label == "COMPLETED_EXCHANGE":
            service.complete_exchange(return_id)
        states[label] = return_id

    return_id = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    service.submit_photos(return_id, "eligible_a_95")
    service.select_fulfillment_mode(return_id, "DROPOFF")
    service.route_return(return_id)
    service.generate_artifact(return_id)
    states["COMPLETED_RETURN"] = return_id

    return_id, recommendation = start("SYN-O-MISSING-001", "My item never arrived and is missing")
    service.record_decision(return_id, "RESHIP", recommendation["options"][0]["option_id"])
    states["COMPLETED_SERVICE"] = return_id

    return_id = advance_to_photos(service, "SYN-O-LOW75-001")
    service.submit_photos(return_id, "eligible_75")
    states["AWAITING_REVIEW"] = return_id

    return_id = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
    service.submit_photos(return_id, "suspected_defect")
    states["DEFECT_HOLD"] = return_id

    for label, decision in (("DEFECT_RESOLVED_REPLACEMENT", "EXCHANGE"), ("DEFECT_RESOLVED_REFUND", "REFUND")):
        if decision == "EXCHANGE":
            return_id, recommendation = start("SYN-O-SIZE-001", "The shoes are too small")
            service.record_decision(return_id, "EXCHANGE", recommendation["options"][0]["option_id"])
        else:
            return_id = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
        service.submit_photos(return_id, "suspected_defect")
        service.resolve_defect_hold(return_id, "CONFIRMED_DEFECT", "STAFF-DEMO-1")
        states[label] = return_id

    return_id, recommendation = start("SYN-O-SIZE-001", "The shoes are too small")
    service.record_decision(return_id, "EXCHANGE", recommendation["options"][0]["option_id"])
    service.submit_photos(return_id, "worn_ineligible")
    states["INELIGIBLE_CLOSED"] = return_id

    for label, return_id in states.items():
        expected = (
            "ROUTED" if label.startswith("ROUTED_") else "DEFECT_RESOLVED" if label.startswith("DEFECT_RESOLVED_") else label
        )
        assert service.get_customer_view(return_id)["state"] == expected, label
    return states


def test_customer_portal_states_never_show_internal_destinations(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    states = _drive_customer_states(tmp_path)
    for label, return_id in states.items():
        app = AppTest.from_file(str(APP), default_timeout=30)
        app.session_state["return_id"] = return_id
        app.run()
        assert not app.exception, label
        text = _page_text(app).casefold()
        found = [term for term in FORBIDDEN_CUSTOMER_TERMS + ("destination", "matrix") if term in text]
        assert not found, f"{label}: {found}"

        if label == "OPTIONS_READY":
            assert any(expander.label == "Sent to your email (simulated)" for expander in app.expander)
            assert "customer-syn-o-size-001@example.test" in text
            decision = next(radio for radio in app.radio if radio.label == "Resolution")
            assert decision.value == "EXCHANGE" and decision.options[0].endswith("(recommended)")
        if label == "READY_TO_ROUTE":
            method = next(radio for radio in app.radio if radio.label == "How would you like to return the shoes?")
            assert method.options == [METHOD_LABELS["DROPOFF"], METHOD_LABELS["SHIP"]]
            assert method.value == "DROPOFF"
            assert any(button.label == "Confirm return method" for button in app.button)
        if label.startswith("ROUTED_"):
            assert "aldo downtown demo store" in text
        if label == "COMPLETED_SERVICE":
            assert "no return needed" in text
        if label == "DEFECT_RESOLVED_REPLACEMENT":
            assert "replacement" in text and "no return needed" in text
        if label == "DEFECT_RESOLVED_REFUND":
            assert "refund has been recorded" in text and "no return needed" in text
        if label == "INELIGIBLE_CLOSED":
            assert "exchange reservation was cancelled" in text
        # Neither confidence numbers nor the staff demo override ever reach the Customer Portal.
        for term in ("confidence", "force 95%", "force 75%", "use ai confidence", "demo_override", "lifecycle"):
            assert term not in text, f"{label}: {term}"
        assert not PERCENT.findall(text), f"{label}: {PERCENT.findall(text)}"


def _render_customer(supervisor, return_id):
    import streamlit as st

    from return_intelligence.ui.customer import render

    st.session_state["return_id"] = return_id
    render(supervisor)


def test_customer_photo_step_has_no_confidence_selector(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    db = tmp_path / "data" / "ui.db"
    seed_database(db, tmp_path)
    repo = Repository(db)
    service = SupervisorService(repo, tmp_path / "artifacts", "WINTER", upload_root=tmp_path / "uploads")
    service.set_confidence_override("FORCE_75", "STAFF-DEMO-1")
    return_id = advance_to_photos(service, "SYN-O-A95-001", "wrong color")

    simulated = AppTest.from_file(str(APP), default_timeout=30)
    simulated.session_state["return_id"] = return_id
    simulated.run()
    assert not simulated.exception
    assert len(simulated.radio) == 1  # only the sidebar Area selector
    assert not simulated.main.radio
    text = _page_text(simulated)
    for term in ("Force 95%", "Force 75%", "Use AI confidence", "review-control"):
        assert term not in text
    assert "confidence" not in text.casefold() and not PERCENT.findall(text)
    # Customers see neutral photo descriptions; the fixture keys (which encode confidence and outcome) stay internal.
    fixtures = list(VisualConditionAssessmentAgent.fixtures)
    photo = next(box for box in simulated.selectbox if box.label == "Synthetic photo scenario")
    assert photo.options == [PHOTO_SCENARIO_LABELS[key] for key in fixtures]
    assert len(set(photo.options)) == len(fixtures) and photo.value == fixtures[0]
    assert not [key for key in fixtures if key in text]

    from tests.fakes import FakeLiveProvider

    live_service = SupervisorService(
        repo, tmp_path / "artifacts", "WINTER", provider=FakeLiveProvider(), upload_root=tmp_path / "uploads"
    )
    live = AppTest.from_function(_render_customer, args=(live_service, return_id), default_timeout=30).run()
    assert not live.exception
    assert len(live.radio) == 0
    assert len(live.file_uploader) == 3
    assert "confidence" not in _page_text(live).casefold()

    # A neutral label still submits its internal fixture key.
    photo.set_value("unclear").run()
    next(button for button in simulated.button if button.label == "Submit 3 synthetic photos").click().run()
    assert not simulated.exception
    assert repo.get_return(return_id)["state"] == "RETAKE_REQUIRED"


def test_generic_service_text_is_neutral_for_every_service_case():
    # The generic branch also serves wrong-item and undelivered orders, so it names no specific case.
    resolution = {"status": "synthetic service case recorded", "photos_required": False}
    text = _service_text({"service_resolution_json": json.dumps(resolution)}).casefold()
    assert "missing" not in text and "delayed" not in text
    assert "no photos or return label are needed" in text


def test_staff_override_radio_defaults_to_ai_and_persists(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Staff Dashboard").run()
    label = "Demo photo-confidence override (staff only)"
    override = next(radio for radio in app.radio if radio.label == label)
    assert override.value == "AI" and override.options == ["Use AI confidence", "Force 95%", "Force 75%"]
    assert "not statistically calibrated" in _page_text(app)
    assert next(box for box in app.text_input if box.key == "staff_id").value == "STAFF-DEMO-1"
    override.set_value("FORCE_75").run()
    assert not app.exception
    repo = Repository(tmp_path / "data" / "ui.db")
    assert repo.get_setting("visual_confidence_override") == "FORCE_75"
    assert repo.one("SELECT updated_by FROM demo_settings WHERE setting_key='visual_confidence_override'")["updated_by"] == "STAFF-DEMO-1"

    # A fresh session (another browser tab) shows the persisted choice.
    other = AppTest.from_file(str(APP), default_timeout=30).run()
    other.sidebar.radio[0].set_value("Staff Dashboard").run()
    assert next(radio for radio in other.radio if radio.label == label).value == "FORCE_75"


def test_staff_dashboard_shows_grading_report_hold_and_final_destination(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    db = tmp_path / "data" / "ui.db"
    seed_database(db, tmp_path)
    service = SupervisorService(Repository(db), tmp_path / "artifacts", upload_root=tmp_path / "uploads")
    hold = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
    service.submit_photos(hold, "suspected_defect")
    routed = advance_to_photos(service, "SYN-O-B-001", "I prefer another style")
    service.submit_photos(routed, "eligible_75")
    service.resolve_review(routed, "APPROVE")
    service.select_fulfillment_mode(routed, "DROPOFF")
    service.route_return(routed)

    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Staff Dashboard").run()
    app.selectbox(key="staff_request").set_value(hold).run()
    assert not app.exception
    text = _page_text(app)
    assert "AI grading report" in text and "Suspected-defect hold" in text and "Lifecycle" in text
    finding = next(radio for radio in app.radio if radio.label == "Staff finding")
    finding.set_value("CONFIRMED_DEFECT").run()
    next(button for button in app.button if button.label == "Resolve defect hold").click().run()
    assert not app.exception
    assert service.repo.get_return(hold)["state"] == "DEFECT_RESOLVED"

    app.selectbox(key="staff_request").set_value(routed).run()
    text = _page_text(app)
    assert "Final destination (staff decision)" in text
    suggested = service.final_destination(routed)["suggested"]
    assert f"Pending staff decision (suggested: {suggested['name']} · OUTLET)" in text
    next(button for button in app.button if button.label == "Save final destination").click().run()
    assert not app.exception
    assert service.final_destination(routed)["status"] == "STAFF_DECIDED"


def test_staff_dashboard_kpis_flags_and_alert_status_buttons(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    db = tmp_path / "data" / "ui.db"
    seed_database(db, tmp_path)
    service = SupervisorService(Repository(db), tmp_path / "artifacts", upload_root=tmp_path / "uploads")
    return_id = service.start_return("SYN-O-SIZE-001")["return_id"]
    options = service.submit_reason(return_id, "The shoes are too small")["recommendation"]["options"]
    service.record_decision(return_id, "EXCHANGE", options[0]["option_id"])
    alert_id = service.repo.one("SELECT alert_id FROM early_warning_alerts")["alert_id"]

    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Staff Dashboard").run()
    assert not app.exception
    text = _page_text(app)
    assert "Exchange rate" in text and "Retention rate" in text and "Store drop-off share" in text
    assert "Product / series flags · suspected, never confirmed" in text and "SYN-MODEL-RUNNER" in text
    assert "SKU + size" in text and "not a confirmed defect" in text
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Active suspected-pattern alerts"] == "1" and metrics["Exchange rate"] == "100%"
    assert metrics["Store drop-off share"] == "—"
    app.selectbox(key="staff_request").set_value(return_id).run()
    assert "series SYN-MODEL-RUNNER is flagged by 1 active alert" in _page_text(app)

    next(button for button in app.button if button.label == "Start investigation").click().run()
    assert not app.exception
    assert service.repo.alert(alert_id)["status"] == "INVESTIGATING"
    assert service.repo.alert(alert_id)["status_updated_by"] == "STAFF-DEMO-1"
    next(button for button in app.button if button.label == "Close alert").click().run()
    assert not app.exception
    assert service.repo.alert(alert_id)["status"] == "CLOSED"
    assert len(service.repo.alert_status_history(alert_id)) == 2
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Active suspected-pattern alerts"] == "0"
    assert "No product or series is flagged" in _page_text(app)
    assert any(expander.label == "Closed alerts (1)" for expander in app.expander)
