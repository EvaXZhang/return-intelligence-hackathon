import json

import streamlit as st

from ..domain.errors import DomainError
from ..services.supervisor import CONFIDENCE_OVERRIDE_MODES, FINAL_DESTINATION_TYPES
from .components import CALIBRATION_CAVEAT, confidence_report

DEFAULT_STAFF_ID = "STAFF-DEMO-1"
OVERRIDE_LABELS = {"AI": "Use AI confidence", "FORCE_95": "Force 95%", "FORCE_75": "Force 75%"}


ACTIVE_ALERT_STATUSES = ("OPEN", "INVESTIGATING")
ALERT_LEVEL_LABELS = {"SKU_SIZE": "SKU + size", "MODEL": "Series (model)", "MODEL_SIZE": "Legacy (model + size)"}
ALERT_ACTIONS = {"OPEN": ("Start investigation", "INVESTIGATING"), "INVESTIGATING": ("Close alert", "CLOSED")}
NO_BASELINE = "n/a — no comparable baseline"


def _percent(value):
    return "—" if value is None else f"{value:.0%}"


def _alert_evidence(alert) -> dict:
    try:
        evidence = json.loads(alert.get("evidence_json") or "{}")
    except (TypeError, ValueError):
        evidence = {}
    return evidence if isinstance(evidence, dict) else {}


def _alert_card(supervisor, alert, staff_id):
    evidence = _alert_evidence(alert)
    # Legacy v1 alerts carry no flag; they always had a positive baseline.
    baseline_available = evidence.get("baseline_available", (alert.get("baseline_rate") or 0) > 0)
    baseline = f"{alert['baseline_rate']:.1%}" if baseline_available else NO_BASELINE
    lift = f"{alert['lift']:.1f}×" if baseline_available else NO_BASELINE
    window = evidence.get("window") or {"start": alert["window_start"], "end": alert["window_end"]}
    level = ALERT_LEVEL_LABELS.get(alert["dimension_type"], alert["dimension_type"])
    detail = alert.get("detail_code") or "—"
    st.warning(
        f"**{level}** · `{alert['dimension_value']}` · {alert['category']} / {detail} · status **{alert['status']}**  \n"
        f"Evidence: {alert['complaint_count']}/{alert['units_sold']} ({alert['complaint_rate']:.1%}) · "
        f"baseline {baseline} · lift {lift}"
        + (f" · baseline basis: {evidence['baseline_basis']}" if evidence.get("baseline_basis") else "")
        + f"  \nWindow: {window['start']} → {window['end']}  \n{alert['recommendation']}"
    )
    action = ALERT_ACTIONS.get(alert["status"])
    if not action:
        if alert.get("status_updated_by"):
            st.caption(f"Closed by {alert['status_updated_by']} at {alert['status_updated_at']}.")
        return
    label, target = action
    suffix = f"{alert['alert_id']}_{alert['status']}"
    note = st.text_input("Alert note (optional, max 500 characters)", max_chars=500, key=f"alert_note_{suffix}")
    if st.button(label, key=f"alert_action_{suffix}"):
        try:
            supervisor.update_alert_status(alert["alert_id"], target, staff_id, note)
            st.rerun()
        except DomainError as exc:
            st.error(str(exc))


def _staff_controls(supervisor):
    with st.expander("Staff controls", expanded=False):
        staff_id = st.text_input("Staff ID", value=DEFAULT_STAFF_ID, max_chars=64, key="staff_id")
        current = supervisor.get_confidence_override()
        # Keyed by the stored value so a change made in another tab re-renders with the persisted choice.
        choice = st.radio(
            "Demo photo-confidence override (staff only)",
            CONFIDENCE_OVERRIDE_MODES,
            index=CONFIDENCE_OVERRIDE_MODES.index(current),
            format_func=OVERRIDE_LABELS.get,
            horizontal=True,
            key=f"confidence_override_{current}",
        )
        st.caption(CALIBRATION_CAVEAT)
        if choice != current:
            try:
                supervisor.set_confidence_override(choice, staff_id)
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))
    return staff_id


def _grading_report(assessment):
    st.subheader("AI grading report")
    if not assessment:
        st.info("No photo assessment yet.")
        return
    st.markdown(
        f"**Eligibility:** `{assessment.get('eligibility_state') or 'NOT ASSESSED (retake)'}`  \n"
        f"**Preliminary grade:** `{assessment.get('preliminary_grade') or '—'}`"
    )
    confidence_report(
        assessment.get("simulated_calibrated_confidence"),
        assessment.get("ai_confidence"),
        assessment.get("confidence_source"),
    )
    evidence, uncertainty = st.columns(2)
    with evidence:
        st.markdown("**Evidence**")
        for item in assessment.get("evidence") or ["—"]:
            st.write(f"- {item}")
    with uncertainty:
        st.markdown("**Uncertainty**")
        for item in assessment.get("uncertainty") or ["—"]:
            st.write(f"- {item}")
    lifecycle = assessment.get("lifecycle")
    st.markdown("**Lifecycle**")
    if lifecycle:
        st.markdown(
            f"Season: `{lifecycle['current_season']}` (source {lifecycle['season_source']}, as of {lifecycle['as_of']})  \n"
            f"Product season profile: `{lifecycle['product_season_profile']}`  \n"
            f"{'In season' if lifecycle['in_season'] else 'Off-season'} · {lifecycle['reason']}"
        )
    else:
        st.caption("No lifecycle recorded for this assessment.")


def _defect_hold(supervisor, row, staff_id):
    return_id = row["return_id"]
    st.subheader("Suspected-defect hold")
    suffix = f"{return_id}_{row['version']}"
    resolution = st.radio(
        "Staff finding",
        ["NOT_DEFECT", "CONFIRMED_DEFECT"],
        format_func={"NOT_DEFECT": "Not a defect", "CONFIRMED_DEFECT": "Confirmed defect"}.get,
        horizontal=True,
        key=f"defect_resolution_{suffix}",
    )
    grade = None
    if resolution == "NOT_DEFECT":
        grade = st.selectbox("Staff grade", ["A", "B", "C"], key=f"defect_grade_{suffix}")
        st.caption("The request returns to the normal flow (READY_TO_ROUTE) with this grade.")
    else:
        exchange = row.get("exchange") or {}
        if row.get("current_decision") == "EXCHANGE" and exchange.get("exchange_status") == "RESERVED_PENDING_ORIGINAL_RETURN":
            st.caption(
                f"Planned outcome: release the reserved replacement {exchange['sku']} · size {exchange['size']} · "
                f"{exchange['color']}. The defective pair is never routed or resold."
            )
        else:
            st.caption("Planned outcome: record a refund. The defective pair is never routed or resold.")
    note = st.text_input("Optional note (max 500 characters)", key=f"defect_note_{suffix}")
    if st.button("Resolve defect hold", key=f"defect_resolve_{suffix}"):
        try:
            supervisor.resolve_defect_hold(return_id, resolution, staff_id, grade=grade, note=note)
            st.rerun()
        except DomainError as exc:
            st.error(str(exc))


def _final_destination(supervisor, row, final, staff_id):
    return_id = row["return_id"]
    st.subheader("Final destination (staff decision)")
    suggested = final["suggested"] or {}
    st.caption(
        f"System suggestion: {suggested.get('name')} · {suggested.get('type')} · score {suggested.get('score')}"
    )
    decision = final["decision"]
    if final["status"] == "STAFF_DECIDED":
        st.success(
            f"Decided by {decision['decided_by']} at {decision['decided_at']}: "
            f"{decision['chosen_destination_name']} · {decision['chosen_destination_type']}"
            + (f" · reason: {decision['reason']}" if decision.get("reason") else "")
        )
    else:
        st.warning(f"Pending staff decision (suggested: {suggested.get('name')} · {suggested.get('type')})")
    destinations = supervisor.repo.active_destinations(FINAL_DESTINATION_TYPES)
    ids = [value["destination_id"] for value in destinations]
    names = {value["destination_id"]: f"{value['name']} · {value['destination_type']}" for value in destinations}
    default = suggested.get("id")
    suffix = f"{return_id}_{row['version']}"
    with st.form(f"final_destination_{suffix}"):
        chosen = st.selectbox(
            "Final destination",
            ids,
            index=ids.index(default) if default in ids else 0,
            format_func=names.get,
        )
        reason = st.text_area("Reason (required when it differs from the suggestion)", max_chars=500)
        if st.form_submit_button("Save final destination"):
            try:
                supervisor.decide_destination(return_id, chosen, staff_id, reason)
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))


def render(supervisor):
    runtime = supervisor.runtime_info
    st.header("Staff Dashboard")
    st.caption(
        "SYNTHETIC BUSINESS DATA · LIVE AMAZON BEDROCK + STRANDS" if runtime["live_ai"] else "SYNTHETIC DATA · SIMULATED AI · MOCKED LOGISTICS"
    )
    staff_id = _staff_controls(supervisor)
    data = supervisor.get_staff_view()
    requests = data["requests"]
    active_alerts = [alert for alert in data["alerts"] if alert["status"] in ACTIVE_ALERT_STATUSES]
    closed_alerts = [alert for alert in data["alerts"] if alert["status"] not in ACTIVE_ALERT_STATUSES]
    c1, c2, c3 = st.columns(3)
    c1.metric("Synthetic requests", len(requests))
    c2.metric("Open human reviews", len(data["open_reviews"]))
    c3.metric("Active suspected-pattern alerts", len(active_alerts))
    kpis = data["kpis"]
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Exchanges", kpis["exchanges"])
    k2.metric("Refunds", kpis["refunds"])
    k3.metric("Keeps", kpis["keeps"])
    k4.metric("Exchange rate", _percent(kpis["exchange_rate"]))
    k5.metric("Retention rate", _percent(kpis["retention_rate"]))
    k6.metric("Store drop-off share", _percent(kpis["dropoff_share"]))
    st.caption(
        "Exchange rate = exchanges ÷ decided (exchange, keep or refund); retention = (exchanges + keeps) ÷ decided; "
        "drop-off share = store drop-off routes ÷ all routes. Reships and service cases are not counted."
    )

    flags = data["flags"]
    st.subheader("Product / series flags · suspected, never confirmed")
    if flags:
        for flag in flags:
            st.warning(
                f"{flag['model_id']} ({', '.join(flag['product_names']) or 'unknown product'}): "
                f"{len(flag['alert_ids'])} active alert(s) · {', '.join(flag['categories'])} · status "
                f"{', '.join(flag['statuses'])}. Suspected pattern, not a confirmed defect — review the whole series."
            )
    else:
        st.caption("No product or series is flagged. Flags appear while an alert is OPEN or INVESTIGATING.")

    if data["alerts"]:
        st.subheader("Early-warning evidence · suspected, never confirmed")
        for alert in active_alerts:
            _alert_card(supervisor, alert, staff_id)
        if closed_alerts:
            with st.expander(f"Closed alerts ({len(closed_alerts)})", expanded=False):
                for alert in closed_alerts:
                    _alert_card(supervisor, alert, staff_id)
    if not requests:
        st.info("No requests yet.")
        return

    ids = [row["return_id"] for row in requests]
    return_id = st.selectbox("Inspect request", ids, key="staff_request")
    detail = supervisor.get_staff_view(return_id)
    row = detail["request"]
    st.dataframe(requests, use_container_width=True, hide_index=True)

    st.subheader("Request details")
    flagged = next((flag for flag in flags if flag["model_id"] == row.get("model_id")), None)
    if flagged:
        st.warning(
            f"This request's series {flagged['model_id']} is flagged by {len(flagged['alert_ids'])} active alert(s) "
            "(suspected pattern, not a confirmed defect)."
        )
    st.json(
        {
            key: row.get(key)
            for key in (
                "return_id",
                "order_id",
                "sku",
                "state",
                "current_decision",
                "condition_state",
                "preliminary_grade",
                "final_grade",
                "simulated_calibrated_confidence",
                "seasonality_flag",
                "destination_type",
                "selected_destination_id",
                "fulfillment_mode",
                "dropoff_location_id",
                "return_store_name",
                "return_store_address",
                "return_fee",
                "routing_reason",
            )
        }
    )
    if row.get("exchange"):
        st.subheader("Exchange fulfillment status")
        st.json(row["exchange"])
    with st.expander("Original complaint and AI classification", expanded=True):
        st.write(row.get("raw_reason") or "No complaint submitted yet.")
        if row.get("classification"):
            st.json(row["classification"])
    with st.expander("AI recommendation and customer decision"):
        if row.get("recommendation"):
            st.info(row["recommendation"].get("explanation", ""))
            st.json(row["recommendation"])
        if detail.get("staff_solution"):
            st.markdown("**Staff copy of the AI solution**")
            st.json(detail["staff_solution"])
        if row.get("messages"):
            st.markdown("**Customer messages (simulated email)**")
            st.dataframe(row["messages"], use_container_width=True, hide_index=True)
        if detail["decisions"]:
            st.dataframe(detail["decisions"], use_container_width=True, hide_index=True)

    _grading_report(row.get("latest_assessment"))

    open_review = next((value for value in detail["reviews"] if value["status"] == "OPEN"), None)
    if open_review:
        st.subheader("Human photo review")
        ai_eligibility = open_review.get("ai_eligibility_state") or "ELIGIBLE_UNWORN"
        ai_grade = open_review.get("preliminary_grade")
        ai_summary = f"{ai_eligibility} · grade {ai_grade}" if ai_grade else ai_eligibility
        st.markdown(f"**AI eligibility:** `{ai_summary}`")
        st.caption("The AI result is preliminary. Staff may confirm it, override the grade, mark worn/ineligible, or hold a suspected defect.")
        resolution = st.selectbox(
            "Resolution",
            ["APPROVE", "OVERRIDE_A", "OVERRIDE_B", "OVERRIDE_C", "WORN_INELIGIBLE", "SUSPECTED_DEFECT"],
            format_func=lambda value: f"Confirm AI: {ai_summary}" if value == "APPROVE" else value,
            key=f"resolution_{return_id}_{row['version']}",
        )
        note = st.text_input("Optional audit note (max 500 characters)", key=f"note_{return_id}_{row['version']}")
        if st.button("Resolve review", key=f"resolve_{return_id}_{row['version']}"):
            try:
                supervisor.resolve_review(return_id, resolution, note, staff_id=staff_id)
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))

    if row["state"] == "DEFECT_HOLD":
        _defect_hold(supervisor, row, staff_id)

    if row["route"]:
        st.subheader("Deterministic route and AI explanation")
        st.json(row["route"])
    if detail["final_destination"]["status"] != "NOT_APPLICABLE":
        _final_destination(supervisor, row, detail["final_destination"], staff_id)

    st.subheader("Multi-Agent activity · public rationale, not chain-of-thought")
    for item in detail["activity"]:
        with st.expander(f"{item['created_at']} · {item['agent_name']} · {item['action']}"):
            st.write(item["rationale"])
            st.json({"input": json.loads(item["input_json"]), "output": json.loads(item["output_json"])})
