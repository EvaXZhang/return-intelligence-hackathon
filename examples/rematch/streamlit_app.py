"""ReMatch presentation entry point."""

from __future__ import annotations

import os

import streamlit as st

from rematch.config import Settings
from rematch.models import Grade, Stage
from rematch.orchestrator import AwsStrandsOrchestrator, create_orchestrator
from rematch.ui.components import (
    audit_timeline,
    buyer_cards,
    condition_panel,
    economics_panel,
    guardrail_panel,
    mode_badge,
    return_card,
    workflow_status,
)
from rematch.ui.styles import CSS


APP_STATE_VERSION = 2

st.set_page_config(page_title="ReMatch · Agentic return-to-resale", page_icon="↻", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ReMatch control room")
    selected_mode = st.radio("Runtime", ["Demo", "AWS"], index=0 if os.getenv("REMATCH_MODE", "demo").lower() == "demo" else 1)
    mode = selected_mode.lower()
    st.caption("Demo is fully deterministic and requires no credentials. AWS is credential/model gated and never silently falls back.")
    st.divider()
    st.markdown("**Presentation promise**")
    st.write("Every eligible return is matched to its next buyer—with policy, price, consent, and people in control.")

settings = Settings(
    mode=mode,
    aws_region=os.getenv("AWS_REGION", "us-east-1"),
    bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", ""),
    confidence_threshold=float(os.getenv("REMATCH_CONFIDENCE_THRESHOLD", "0.75")),
)
if (
    "orchestrator" not in st.session_state
    or st.session_state.orchestrator.mode != mode
    or st.session_state.get("app_state_version") != APP_STATE_VERSION
):
    st.session_state.orchestrator = create_orchestrator(settings)
    st.session_state.app_state_version = APP_STATE_VERSION
orchestrator = st.session_state.orchestrator
state = orchestrator.state

st.markdown(
    """<div class="hero"><div class="eyebrow">McGill BSRM × ALDO · Retail Gen AI Hackathon</div>
    <h1 style="margin:.35rem 0">ReMatch</h1>
    <h3 style="margin:0">Agentic return-to-resale: every eligible return, matched to its next buyer.</h3>
    <p style="margin:.8rem 0 0;max-width:850px">One agent evaluates uncertainty, invokes governed tools, reacts to buyer and staff events, and preserves deterministic business rules.</p></div>""",
    unsafe_allow_html=True,
)

overview_tab, live_tab, economics_tab, responsible_tab, architecture_tab = st.tabs(
    ["Overview", "Live Agent Demo", "Economics / Impact", "Responsible AI", "AWS Architecture"]
)

with overview_tab:
    mode_badge(mode)
    st.markdown("## Returns should be recovery inventory—not automatic loss")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="card"><div class="kicker">Problem</div><h3>Eligible returns leak value</h3>Good product defaults to handling-heavy liquidation while demand sits elsewhere in the network.</div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><div class="kicker">Thesis</div><h3>Match before liquidating</h3>An agent can connect each return to opted-in demand while deterministic code protects policy and margin.</div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="card"><div class="kicker">Outcome</div><h3>~3× recovery</h3>The illustrative B-grade unit recovers $90 net versus a $30 liquidation baseline.</div>', unsafe_allow_html=True)
    st.markdown("## Why this is agentic")
    st.write("The next action depends on live state: eligibility can stop the flow; uncertain condition pauses for a person; a decline causes candidate re-selection; a staff grade change causes re-pricing and re-matching; and an unprofitable path falls back safely. The agent chooses among permissible actions—it cannot rewrite policy or money rules.")
    st.info("Start in **Live Agent Demo** → Run to checkpoint → staff selects final A/B/C grade → continue through rejection, re-plan, acceptance, and route.")

with live_tab:
    top_left, top_right = st.columns([2, 1])
    with top_left:
        mode_badge(mode)
        st.markdown("## Live return decision")
    with top_right:
        if st.button("↺ Reset scenario", use_container_width=True):
            orchestrator.reset()
            st.rerun()

    variant_labels = {
        "standard": "Standard · decline → re-plan → accept",
        "uncertain": "Uncertain evidence · human review",
        "fallback": "No profitable buyer · safe fallback",
    }
    variant_options = list(variant_labels) if mode == "demo" else ["standard"]
    selected_variant = st.selectbox(
        "Synthetic demo branch",
        variant_options,
        format_func=variant_labels.get,
        help="Switching branches resets only synthetic session state. AWS mode uses live model evidence.",
        key=f"scenario_variant_{mode}",
    )
    if selected_variant != state.scenario_variant:
        state = orchestrator.set_scenario_variant(selected_variant)
    if selected_variant == "uncertain":
        st.info("This branch deterministically supplies 61% confidence plus conflicting evidence, forcing review before any buyer is matched.")
    elif selected_variant == "fallback":
        st.info("This branch keeps three opted-in matches but sets synthetic willingness-to-pay below the guarded floor, so no offer is forced.")

    return_col, upload_col = st.columns([1.25, 1])
    with return_col:
        return_card(state)
    with upload_col:
        photo = st.file_uploader("Optional shoe photos", type=["png", "jpg", "jpeg"], help="Demo mode uses a preset synthetic observation. AWS mode may send only these uploaded bytes plus synthetic context to Bedrock.")
        if photo and isinstance(orchestrator, AwsStrandsOrchestrator):
            orchestrator.uploaded_photo = photo.getvalue()
            orchestrator.uploaded_photo_format = "png" if photo.type == "image/png" else "jpeg"
        st.caption("Privacy boundary: source CSVs and real PII are never loaded by this app or sent to Bedrock.")

    workflow_status(state)
    if state.stage == Stage.READY and state.approval:
        st.success(
            f"Staff recorded final grade {state.approval.staff_grade.value}. "
            "The agent is unlocked—click **Next agent action** or **Run to next checkpoint**."
        )

    aws_error = settings.aws_readiness_error()
    if aws_error:
        st.error(aws_error)
    checkpoint_or_done = {Stage.CONDITION_REVIEW, Stage.INSPECTION, Stage.ROUTED, Stage.FALLBACK, Stage.BLOCKED}
    b1, b2, _ = st.columns([1, 1.35, 2])
    next_disabled = state.stage in checkpoint_or_done or bool(aws_error)
    if b1.button("Next agent action", type="primary", disabled=next_disabled, use_container_width=True):
        try:
            orchestrator.step()
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if b2.button("Run to next checkpoint", disabled=next_disabled, use_container_width=True):
        try:
            orchestrator.run_until_checkpoint()
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if state.stage == Stage.CONDITION_REVIEW:
        st.warning("Uncertainty checkpoint · Matching is paused because confidence is below threshold and/or evidence conflicts.")
        review_left, review_right = st.columns([2, 1])
        review_left.write("A store associate reviews the visible evidence and return-desk note. This clears uncertainty only; the final A/B/C grade is still selected later by staff.")
        if review_right.button("Staff reviewed · retain preliminary grade", type="primary", use_container_width=True):
            orchestrator.resolve_uncertainty()
            st.rerun()

    if state.stage == Stage.INSPECTION:
        preliminary_grade = state.observation.grade if state.observation else Grade.B
        grade_values = [grade.value for grade in Grade]
        st.warning("Staff checkpoint · The AI grade is preliminary. Store staff selects the final condition grade.")
        selected_grade = st.radio(
            "Final staff grade",
            grade_values,
            index=grade_values.index(preliminary_grade.value),
            horizontal=True,
            help="Only store staff can finalize or change the A/B/C condition grade.",
        )
        if selected_grade != preliminary_grade.value:
            st.info(
                f"Changing {preliminary_grade.value} → {selected_grade} will automatically re-price the item and re-rank eligible buyers."
            )
        if st.button("Record final grade and unlock agent", type="primary", use_container_width=True):
            try:
                approved_state = orchestrator.approve(Grade(selected_grade))
            except Exception as exc:
                st.error(f"Could not record the staff grade: {exc}")
            else:
                if approved_state.stage == Stage.INSPECTION:
                    st.error(approved_state.status_message)
                else:
                    st.rerun()

    st.markdown("### Condition decision")
    condition_panel(state, settings.confidence_threshold)
    st.markdown("### Opted-in buyer candidates")
    buyer_cards(state)
    st.markdown("### Guarded unit economics")
    economics_panel(state)
    left, right = st.columns([1, 1.5])
    with left:
        st.markdown("### Guardrail status")
        guardrail_panel(state)
        if state.route:
            st.success(f"Final route · {state.route.destination_label}\n\n{state.route.reason}")
        elif state.stage == Stage.FALLBACK:
            st.warning("Safe outcome · Send to outlet/liquidation; never force a match below the floor.")
    with right:
        st.markdown("### Reviewable agent activity")
        st.caption("Tool, sanitized input/output, rationale, confidence, guardrails, and staff decisions—never private chain-of-thought.")
        audit_timeline(state)

with economics_tab:
    st.markdown("## Before / after unit economics")
    st.caption("Illustrative hackathon assumptions, not a forecast. Adjust with pilot data before production decisions.")
    e = state.economics
    resale = e.resale_price if e else 102
    costs = e.total_cost if e else 12
    net = e.net_recovery if e else 90
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="card"><div class="kicker">Today · liquidation</div><h2>$30 recovery</h2>25% of $120 illustrative retail value.</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="card"><div class="kicker">ReMatch · resale</div><h2>${net:.0f} net recovery</h2>${resale:.0f} resale − ${costs:.0f} cleaning/routing.</div>', unsafe_allow_html=True)
    st.markdown("### +$60 incremental recovery · 3.0× recovery")
    st.write("For the B-grade story: $102 resale − $7 cleaning − $5 routing = $90 net, compared with a $30 liquidation recovery. The customer refund is common to both paths, so it is correctly excluded from the differential comparison—not subtracted from resale alone.")
    st.markdown("### Pilot scorecard")
    cols = st.columns(4)
    cols[0].metric("North-star", "Net recovery / return")
    cols[1].metric("Demand", "Offer acceptance rate")
    cols[2].metric("Operations", "Hours to rematch")
    cols[3].metric("Trust", "Grade override rate")

with responsible_tab:
    st.markdown("## Responsible AI by design")
    items = [
        ("Staff-owned condition", "Photo grading is preliminary; store staff selects the final A/B/C grade. Low confidence and conflicting evidence escalate."),
        ("Money rules stay in code", "A cost/liquidation-linked price floor cannot be overridden by model output."),
        ("Consent and fairness", "Only opted-in buyers are considered. Matching uses product, condition, price, and operational distance—not protected traits or profile proxies."),
        ("Reviewable, not revealing", "The activity trace stores structured tool I/O, reason codes, confidence, checks, and staff decisions—not private chain-of-thought."),
        ("Safe fallback", "If nobody clears the guarded floor, route to outlet/liquidation instead of forcing a bad or unfair match."),
        ("Privacy boundary", "Only hand-authored synthetic records and optional uploaded photos enter the prototype. Raw source files, names, emails, and exact records never go to Bedrock."),
    ]
    cols = st.columns(2)
    for index, (title, text) in enumerate(items):
        with cols[index % 2]:
            st.markdown(f'<div class="card"><div class="kicker">Control {index+1}</div><h3>{title}</h3>{text}</div>', unsafe_allow_html=True)
            st.write("")

with architecture_tab:
    st.markdown("## AWS path: local adapters today, scalable services tomorrow")
    st.write("The prototype proves the governed interaction contract locally. The same seven tool contracts map cleanly to Lambda APIs; no AWS resources are created by this project.")
    local, production = st.columns(2)
    with local:
        st.markdown("### Implemented in prototype")
        for title, text in [
            ("Streamlit UI", "Interactive return, staff grade checkpoint, economics, trace, and reset."),
            ("Strands orchestrator boundary", "Credential-gated AWS class plus reliable deterministic mode."),
            ("Seven local tool adapters", "Policy, grade, matching, pricing, offer, staff confirmation, and routing contracts."),
            ("Synthetic JSON + session state", "Privacy-safe data and resumable workflow state."),
        ]:
            st.markdown(f'<div class="card arch-local"><h3>{title}</h3>{text}</div>', unsafe_allow_html=True)
            st.write("")
    with production:
        st.markdown("### Production extension")
        for title, text in [
            ("API Gateway", "Secure entry point between web UI and agent APIs."),
            ("Strands on Lambda / optional AgentCore", "Runs the orchestrator; AgentCore adds managed runtime capabilities but is not a blocker."),
            ("Amazon Bedrock", "Multimodal condition evidence and bounded orchestration proposals."),
            ("Seven Lambda tool APIs", "Existing deterministic contracts become independently governed services."),
            ("S3 + DynamoDB", "Photos/synthetic artifacts in S3; return, offer, and checkpoint state in DynamoDB."),
            ("CloudWatch", "Tool-call metrics, errors, guardrail outcomes, and auditable operational logs."),
        ]:
            st.markdown(f'<div class="card arch-prod"><h3>{title}</h3>{text}</div>', unsafe_allow_html=True)
            st.write("")
    st.code("Streamlit / React → API Gateway → Strands (Lambda or AgentCore) → Amazon Bedrock\n                                      ↘ 7 Lambda tools → DynamoDB / S3 → CloudWatch", language=None)
