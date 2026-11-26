"""Bounded live AWS/Strands smoke using only the synthetic demo record."""

from __future__ import annotations

import json
import os
import sys

from strands.models import BedrockModel

from rematch.config import Settings
from rematch.models import Stage
from rematch.orchestrator import AwsStrandsOrchestrator

EXPECTED_TOOLS = {
    "check_return",
    "grade_condition",
    "find_buyers",
    "calculate_offer",
    "send_offer",
    "approve_inspection",
    "route_item",
}


class SmokeConfigurationError(Exception):
    """Safe configuration failure whose message may be printed."""


def main() -> None:
    if os.getenv("REMATCH_MODE", "").strip().lower() != "aws":
        raise SmokeConfigurationError("REMATCH_MODE=aws is required; refusing to fall back to Demo mode")
    explicit_region = os.getenv("AWS_REGION", "").strip()
    if not explicit_region:
        raise SmokeConfigurationError("AWS_REGION is required; refusing to use an implicit region")
    if not os.getenv("BEDROCK_MODEL_ID", "").strip():
        raise SmokeConfigurationError("BEDROCK_MODEL_ID is required; refusing to fall back to Demo mode")

    settings = Settings.from_env()
    if settings.aws_region != explicit_region:
        raise SmokeConfigurationError("AWS_REGION did not parse to the explicitly configured region")
    orchestrator = AwsStrandsOrchestrator(settings)
    assert orchestrator.mode == "aws" and orchestrator.state.mode == "aws"

    agent = orchestrator._create_agent()
    assert isinstance(agent.model, BedrockModel), "Strands agent is not Bedrock-backed"
    registered_tools = set(agent.tool_names)
    assert registered_tools == EXPECTED_TOOLS, (
        f"Expected exactly seven ReMatch tools, got {sorted(registered_tools)}"
    )

    previous_events = len(orchestrator.state.audit)
    orchestrator.step()
    assert orchestrator.state.stage == Stage.ELIGIBILITY
    assert len(orchestrator.state.audit) == previous_events + 1

    event = orchestrator.state.audit[-1]
    assert event.tool == "check_return"
    assert event.safe_output.get("eligible") is True
    assert "POLICY_ELIGIBLE" in event.reason_codes

    print("PASS agent_backend=BedrockModel")
    print(f"PASS registered_tools={','.join(sorted(registered_tools))}")
    print(f"LIVE_TOOL_SELECTED={event.tool}")
    print(f"RESULTING_STATE={orchestrator.state.stage.value}")
    print(f"ADAPTER_RESULT={json.dumps(event.safe_output, sort_keys=True)}")
    print(f"REASON_CODES={','.join(event.reason_codes)}")
    print("NO_SILENT_DEMO_FALLBACK=true")


if __name__ == "__main__":
    try:
        main()
    except SmokeConfigurationError as exc:
        print(f"FAIL configuration_error={exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("FAIL aws_strands_smoke_failed; sensitive exception details suppressed", file=sys.stderr)
        raise SystemExit(1) from None
