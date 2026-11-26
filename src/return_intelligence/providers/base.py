from __future__ import annotations

from typing import Any, Protocol


class AIProvider(Protocol):
    provider_kind: str
    display_label: str
    is_live: bool

    def classify_reason(self, text: str) -> dict[str, Any]: ...

    def compose_recommendation(self, facts: dict[str, Any]) -> str: ...

    def assess_visual_evidence(self, fixture_key: str, images: dict[str, bytes] | None = None) -> dict[str, Any]: ...

    def explain_alert(self, facts: dict[str, Any]) -> str: ...

    def explain_route(self, facts: dict[str, Any]) -> str: ...

    def compose_fulfillment_instructions(self, facts: dict[str, Any]) -> str: ...
