"""Small scenario service used by Streamlit session state."""

from __future__ import annotations

from .config import Settings
from .orchestrator import DemoOrchestrator, create_orchestrator


def new_scenario(settings: Settings | None = None) -> DemoOrchestrator:
    return create_orchestrator(settings or Settings.from_env())
