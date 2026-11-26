from pathlib import Path

import streamlit as st

from return_intelligence.config import AppConfig
from return_intelligence.db.seed import reset_database
from return_intelligence.services.container import build_container
from return_intelligence.ui.components import safety_banner
from return_intelligence.ui.customer import render as customer
from return_intelligence.ui.staff import render as staff


st.set_page_config(page_title="AI-Powered Return Prevention", page_icon="👟", layout="wide")
config = AppConfig.from_env(Path(__file__).resolve().parent)
supervisor = build_container(config)

st.title("AI-Powered Return Prevention & Early Warning System")
safety_banner(config)
area = st.sidebar.radio("Area", ["Customer Portal", "Staff Dashboard"])
st.sidebar.divider()
if config.ai_backend == "bedrock":
    st.sidebar.success("LIVE AI")
    st.sidebar.caption(f"Amazon Bedrock · {config.bedrock_model_id} · {config.aws_region}\n\nStrands Supervisor + 6 specialists")
else:
    st.sidebar.caption("Local SQLite · synthetic fixtures · simulated AI")

with st.sidebar.expander("Reset synthetic demo"):
    confirmed = st.checkbox("I understand this deletes only generated local demo data")
    if st.button("Reset and reseed", disabled=not confirmed):
        reset_database(config.db_path, config.project_root, True)
        for key in list(st.session_state):
            if key != "Area":
                del st.session_state[key]
        st.rerun()

if area == "Customer Portal":
    customer(supervisor)
else:
    staff(supervisor)
