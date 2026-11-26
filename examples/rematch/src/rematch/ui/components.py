"""Reusable Streamlit renderers; all rationale is concise and reviewable."""

from __future__ import annotations

import streamlit as st

from ..models import ScenarioState, Stage


_STAGE_PROGRESS = {
    Stage.START: 0.02,
    Stage.ELIGIBILITY: 0.12,
    Stage.CONDITION_REVIEW: 0.2,
    Stage.GRADED: 0.25,
    Stage.BUYERS: 0.38,
    Stage.PRICED: 0.48,
    Stage.INSPECTION: 0.55,
    Stage.READY: 0.64,
    Stage.OFFERED: 0.7,
    Stage.REPLANNING: 0.76,
    Stage.ACCEPTED: 0.9,
    Stage.ROUTED: 1.0,
    Stage.FALLBACK: 1.0,
    Stage.BLOCKED: 1.0,
}


def mode_badge(mode: str) -> None:
    css_class = "mode-demo" if mode == "demo" else "mode-aws"
    label = "Deterministic Demo · No AWS required" if mode == "demo" else "AWS · Strands + Amazon Bedrock"
    st.markdown(f'<span class="mode-badge {css_class}">● {label}</span>', unsafe_allow_html=True)


def return_card(state: ScenarioState) -> None:
    item = state.item
    st.markdown(
        f"""<div class="card"><div class="kicker">Synthetic return</div>
        <h3 style="margin:.25rem 0">{item.style} · size {item.size}</h3>
        <strong>${item.retail_price:.0f} retail</strong> &nbsp;·&nbsp; SKU {item.sku}<br>
        <span class="small-note">{item.return_id} · day {item.return_day-item.purchase_day} of {item.policy_window_days} · not final sale</span></div>""",
        unsafe_allow_html=True,
    )


def workflow_status(state: ScenarioState) -> None:
    st.progress(_STAGE_PROGRESS.get(state.stage, 0), text=f"Agent state · {state.stage.value.replace('_', ' ').title()}")
    st.markdown(f'<div class="stage-pill"><strong>{state.status_message}</strong></div>', unsafe_allow_html=True)


def condition_panel(state: ScenarioState, confidence_threshold: float) -> None:
    if not state.observation:
        st.info("Condition evidence appears after the grading tool runs.")
        return
    observation = state.observation
    final = state.final_grade.value if state.final_grade else "Pending staff"
    c1, c2, c3 = st.columns(3)
    c1.metric("Preliminary grade", observation.grade.value, "AI/preset—not final")
    c2.metric("Confidence", f"{observation.confidence:.0%}", f"Threshold {confidence_threshold:.0%}")
    c3.metric("Final staff grade", final)
    st.markdown("**Evidence:** " + " · ".join(observation.evidence))
    st.caption("The photo grade is preliminary. Low confidence or model/staff mismatch escalates to human review.")


def buyer_cards(state: ScenarioState) -> None:
    if not state.ranked_buyers:
        st.info("Buyer candidates appear after consent and fit filtering.")
        return
    columns = st.columns(min(3, len(state.ranked_buyers)))
    for index, buyer in enumerate(state.ranked_buyers[:3]):
        with columns[index]:
            response = next((offer.status for offer in state.offers if offer.buyer_id == buyer.buyer_id), "queued")
            st.markdown(
                f"""<div class="card buyer-card"><div class="kicker">Match #{index+1} · {response}</div>
                <h3 style="margin:.25rem 0">{buyer.buyer_id}</h3>
                Up to <strong>${buyer.max_price:.0f}</strong> · accepts ≤ {buyer.max_wear_grade.value}<br>
                <span class="small-note">size {buyer.size} · {buyer.distance_km:.1f} km · opted in ✓</span></div>""",
                unsafe_allow_html=True,
            )
    st.caption("Ranking inputs: opt-in, exact SKU/style/size, accepted wear, willingness-to-pay, and fulfillment distance. No protected traits or customer profile proxies.")


def economics_panel(state: ScenarioState) -> None:
    economics = state.economics
    if not economics:
        st.info("Economics appear after the deterministic pricing tool runs.")
        return
    cols = st.columns(5)
    cols[0].metric("Retail", f"${economics.retail_price:.0f}")
    cols[1].metric("Resale", f"${economics.resale_price:.0f}")
    cols[2].metric("Cleaning + route", f"${economics.total_cost:.0f}")
    cols[3].metric("Net recovery", f"${economics.net_recovery:.0f}")
    cols[4].metric("vs liquidation", f"+${economics.incremental_recovery:.0f}", f"{economics.recovery_multiple:.1f}× recovery")
    st.caption(f"Illustrative assumptions only. Guarded floor: ${economics.price_floor:.0f}. {economics.shared_refund_cost_note}")


def guardrail_panel(state: ScenarioState) -> None:
    latest = {}
    for check in state.guardrails:
        latest[check.name] = check
    if not latest:
        st.info("Guardrail checks will appear as tools execute.")
        return
    for check in latest.values():
        icon, css = ("✓", "guard-pass") if check.passed else ("!", "guard-fail")
        st.markdown(f'<div class="{css}">{icon} {check.name.replace("_", " ").title()}</div><div class="small-note">{check.detail}</div>', unsafe_allow_html=True)


def audit_timeline(state: ScenarioState) -> None:
    if not state.audit:
        st.info("The append-only activity trace begins with the first tool call.")
        return
    for event in reversed(state.audit):
        with st.expander(f"{event.sequence:02d} · {event.tool} · {', '.join(event.reason_codes)}"):
            st.write(event.rationale)
            if event.confidence is not None:
                st.caption(f"Confidence: {event.confidence:.0%}")
            c1, c2 = st.columns(2)
            c1.markdown("**Structured input (sanitized)**")
            c1.json(event.safe_input)
            c2.markdown("**Structured output**")
            c2.json(event.safe_output)
            if event.guardrails:
                st.markdown("**Guardrail checks**")
                for check in event.guardrails:
                    st.write(("✅" if check.passed else "⚠️") + f" {check.name}: {check.detail}")
            if event.approval:
                st.markdown("**Human approval**")
                st.json(event.approval)
