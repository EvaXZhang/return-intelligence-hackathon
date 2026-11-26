import streamlit as st


CALIBRATION_CAVEAT = "LLM self-reported confidence is not statistically calibrated — fine for this demo, not for production."


def safety_banner(config):
    if config.ai_backend == "bedrock":
        st.success(
            f"LIVE AI — Amazon Bedrock `{config.bedrock_model_id}` in `{config.aws_region}` via one Strands Supervisor and six specialist agents. "
            "Model inference occurs only when you submit an AI step. SQLite and logistics remain local; no Lambda, S3, DynamoDB, or IAM resources are created."
        )
        st.caption("Deterministic Python still enforces inventory, eligibility, return-method and fulfillment gates.")
    else:
        st.info(
            "LOCAL SYNTHETIC DEMO — AI outputs are deterministic simulations. "
            "Logistics is mocked. No AWS service is called."
        )


def state_badge(state):
    st.markdown(f"**Current status:** `{state}`")


def confidence_report(gate, ai_value, source):
    """Staff-only view of the photo-confidence gate. Never render this on the Customer Portal."""
    columns = st.columns(3)
    columns[0].metric("Gate confidence (used)", f"{gate:.0%}" if gate is not None else "—")
    columns[1].metric("AI confidence", f"{ai_value:.0%}" if ai_value is not None else "—")
    columns[2].metric("Source", source or "—")
    st.caption(f"85% or higher skips staff review; below 85% goes to staff. {CALIBRATION_CAVEAT}")
