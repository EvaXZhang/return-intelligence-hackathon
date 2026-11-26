"""Append-only, reviewable activity events without private chain-of-thought."""

from __future__ import annotations

from typing import Any

from .models import AuditEvent, GuardrailCheck, ScenarioState


def record_event(
    state: ScenarioState,
    *,
    tool: str,
    safe_input: dict[str, Any],
    safe_output: dict[str, Any],
    rationale: str,
    confidence: float | None = None,
    reason_codes: list[str] | None = None,
    guardrails: list[GuardrailCheck] | None = None,
    approval: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        sequence=len(state.audit) + 1,
        tool=tool,
        safe_input=safe_input,
        safe_output=safe_output,
        rationale=rationale,
        confidence=confidence,
        reason_codes=reason_codes or [],
        guardrails=guardrails or [],
        approval=approval,
    )
    state.audit.append(event)
    return event
