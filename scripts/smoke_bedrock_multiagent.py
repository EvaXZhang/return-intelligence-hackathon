"""Live, user-authorized Bedrock/Strands smoke for all six specialist agents, using v2 facts.

This script invokes paid model inference but creates no AWS resources. Point DB_PATH, ARTIFACT_DIR,
UPLOAD_DIR and LOG_PATH at a temporary directory (for example under /tmp/ri_live_v2). The visual check
uses synthetic illustrations unless --front, --left and --right name real shoe photos; those are copied
into UPLOAD_DIR first and only the copies are read, so the source files are never modified.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from return_intelligence.agents.retention import RETURN_METHODS, RetentionRecommendationAgent
from return_intelligence.agents.visual import VisualConditionAssessmentAgent
from return_intelligence.config import AppConfig
from return_intelligence.domain.early_warning_rules import THRESHOLDS, evaluate_thresholds
from return_intelligence.domain.enums import EligibilityState
from return_intelligence.domain.policy import needs_review
from return_intelligence.domain.resolution import NORMAL
from return_intelligence.providers import create_provider
from return_intelligence.services.customer_copy import FORBIDDEN_CUSTOMER_TERMS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANGLES = ("front", "left", "right")
# Seeded synthetic records, passed in the same fact shapes the v2 agents build.
SHOE = {"sku": "SYN-RUNNER-100", "model_id": "SYN-MODEL-RUNNER", "size": "8", "color": "Blue", "delivered": True}
EXCHANGE_OPTION = {
    "option_id": "SYN-RUNNER-100|9|Blue|SYN-STORE-1",
    "sku": "SYN-RUNNER-100",
    "size": "9",
    "color": "Blue",
    "destination_id": "SYN-STORE-1",
    "available": 7,
}
RETURN_STORE = {
    "id": "SYN-STORE-1",
    "name": "ALDO Downtown Demo Store",
    "address": "1000 Sainte-Catherine St W, Montréal, QC H3B 1E2 (DEMO)",
}


def synthetic_shoe_view(label: str) -> bytes:
    image = Image.new("RGB", (1200, 800), "#f4efe8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((180, 290, 960, 560), radius=90, fill="#d9b08c", outline="#4b2f25", width=12)
    draw.polygon([(250, 300), (690, 170), (980, 430), (870, 530), (400, 500)], fill="#ead5c3", outline="#4b2f25")
    draw.text((60, 55), f"SYNTHETIC DEMO SHOE VIEW: {label.upper()}", fill="#241914")
    draw.text((60, 95), "Illustration for connectivity testing; no real customer data.", fill="#5f4438")
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def real_photo_copies(sources: dict[str, Path], upload_dir: Path) -> dict[str, bytes]:
    """Copy each photo into UPLOAD_DIR and read the copy; the source file is only ever read."""
    target = (upload_dir / "smoke-real-photos").resolve()
    if target.is_relative_to(PROJECT_ROOT):
        raise SystemExit("UPLOAD_DIR must be outside the project, for example /tmp/ri_live_v2/uploads")
    target.mkdir(parents=True, exist_ok=True)
    images = {}
    for angle, source in sources.items():
        copy = target / f"{angle}{source.suffix.lower()}"
        shutil.copyfile(source, copy)
        images[angle] = copy.read_bytes()
    return images


def record_structured_outputs(provider) -> list[dict]:
    """Keep each specialist's schema-validated output before BedrockProvider post-processes it."""
    captured: list[dict] = []
    run = provider._runtime.run

    def recording_run(key, prompt, output_model):
        result = run(key, prompt, output_model)
        captured.append({"specialist": key, "output": result.model_dump(mode="json")})
        return result

    provider._runtime.run = recording_run
    return captured


def forbidden_hits(text) -> list[str]:
    folded = str(text or "").casefold()
    return [term for term in FORBIDDEN_CUSTOMER_TERMS if term in folded]


def photo_state(assessment) -> tuple[float | None, str | None, str]:
    """SupervisorService.submit_photos without a staff override: the AI confidence is the gate (source AI)."""
    if not assessment.evidence_sufficient:
        return None, None, "RETAKE_REQUIRED"
    gate = assessment.confidence
    if needs_review(gate):
        return gate, "AI", "AWAITING_REVIEW"
    if assessment.eligibility_state == EligibilityState.WORN_INELIGIBLE:
        return gate, "AI", "INELIGIBLE_CLOSED"
    if assessment.eligibility_state == EligibilityState.SUSPECTED_DEFECT:
        return gate, "AI", "DEFECT_HOLD"
    return gate, "AI", "READY_TO_ROUTE"


def main() -> None:
    parser = argparse.ArgumentParser(description="Paid live Bedrock smoke for the six specialist agents (v2 facts).")
    for angle in ANGLES:
        parser.add_argument(f"--{angle}", type=Path, help=f"real {angle} shoe photo (copied into UPLOAD_DIR before use)")
    args = parser.parse_args()
    sources = {angle: getattr(args, angle) for angle in ANGLES if getattr(args, angle)}
    if sources and len(sources) != len(ANGLES):
        parser.error("pass all of --front, --left and --right, or none of them")

    config = AppConfig.from_env(PROJECT_ROOT)
    images = real_photo_copies(sources, config.upload_dir) if sources else {angle: synthetic_shoe_view(angle) for angle in ANGLES}
    provider = create_provider(config)
    if not provider.is_live:
        raise RuntimeError("Set AI_BACKEND=bedrock and AWS_INTEGRATION_ENABLED=true")
    structured = record_structured_outputs(provider)
    errors: dict[str, str] = {}

    def stage(name, call):
        # This smoke is meant to run once, so one failing live call must not hide the other stages.
        try:
            return call()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"[:700]
            return None

    reason = stage(
        "reason",
        lambda: provider.classify_reason("These shoes are too small and tight. I want the next available size."),
    ) or {}
    choices = RetentionRecommendationAgent._choices(NORMAL, True)
    preferred = RetentionRecommendationAgent._preferred(choices)
    recommendation = stage(
        "recommendation",
        lambda: provider.compose_recommendation(
            {
                "shoe": SHOE,
                "classified_categories": reason.get("categories") or ["Wrong Size"],
                "details": reason.get("details") or {"size_direction": "too_small"},
                "verified_inventory_options": [EXCHANGE_OPTION],
                "allowed_customer_choices": choices,
                "preferred_action": preferred,
                "resolution_path": NORMAL,
                "return_methods": RETURN_METHODS,
            }
        ),
    )
    rule = evaluate_thresholds(5, 25, 1, 100)
    warning = stage(
        "early_warning",
        lambda: provider.explain_alert(
            {
                "complaint_count": 5,
                "units_sold": 25,
                "complaint_rate": rule["rate"],
                "baseline_rate": rule["baseline_rate"],
                "lift": rule["lift"],
                "level": "SKU_SIZE",
                "dimension_value": "SYN-RUNNER-100|8",
                "category": "Wrong Size",
                "detail_code": "too_small",
                "baseline_available": rule["baseline_available"],
                "sku": SHOE["sku"],
                "model_id": SHOE["model_id"],
                "size": SHOE["size"],
                "baseline_basis": "same SKU, other sizes",
                "window": {"start": "2025-10-17", "end": "2026-01-15"},
                "thresholds": THRESHOLDS,
            }
        ),
    )
    visual = stage("visual", lambda: VisualConditionAssessmentAgent(provider).assess("live_upload", images=images))
    gate, gate_source, photo_path = photo_state(visual) if visual else (None, None, None)
    routing = stage(
        "routing",
        lambda: provider.explain_route(
            {
                "condition_grade": "A",
                "seasonality_flag": 0,
                "destination_type": "RETAIL_STORE",
                "selected_final_destination": "SYN-STORE-1",
                "customer_return_method": "SHIP",
                "customer_return_store": RETURN_STORE,
                "customer_return_fee": 9.0,
                "score": 82.5,
                "rule": "Destination type is locked by the mandatory condition × seasonality matrix.",
            }
        ),
    )
    fulfillment = stage(
        "fulfillment",
        lambda: provider.compose_fulfillment_instructions(
            {
                "return_id": "SYN-R-LIVE-SMOKE",
                "customer_decision": "EXCHANGE",
                "exchange_replacement": {
                    **EXCHANGE_OPTION,
                    "exchange_status": "RESERVED_PENDING_ORIGINAL_RETURN",
                    "reservation_type": "LOCAL_DEMO",
                },
                "fulfillment_mode": "SHIP",
                "return_fee": 9.0,
                "customer_return_store": RETURN_STORE,
                "demo_marking": "DEMO / NOT VALID FOR SHIPPING",
            }
        ),
    )

    model_action = next(
        (entry["output"]["recommended_action"] for entry in structured if entry["specialist"] == "retention"), None
    )
    specialists = {entry["specialist"] for entry in provider.delegation_history}
    checks = {
        "all_stages_succeeded": not errors,
        "six_unique_specialists": len(specialists) == 6,
        "reason_wrong_size_too_small": "Wrong Size" in (reason.get("categories") or [])
        and (reason.get("details") or {}).get("size_direction") == "too_small",
        "recommendation_next_step_exchange": preferred == "EXCHANGE"
        and f"Recommended next step: {preferred}." in (recommendation or ""),
        "recommendation_customer_safe": recommendation is not None and not forbidden_hits(recommendation),
        "fulfillment_customer_safe": fulfillment is not None and not forbidden_hits(fulfillment),
        "early_warning_explained": bool(warning),
    }
    if sources:
        # Real photos should be usable, so the model's confidence must reach the >=0.85 gate.
        checks["visual_gate_exercised"] = bool(visual and visual.evidence_sufficient and visual.confidence is not None)
    print(
        json.dumps(
            {
                "provider": provider.provider_kind,
                "model_id": config.bedrock_model_id,
                "photos": {angle: str(path) for angle, path in sources.items()} or "synthetic illustrations",
                "reason": reason,
                "recommendation": {
                    "preferred_action": preferred,
                    "model_recommended_action": model_action,
                    "message": recommendation,
                    "forbidden_hits": forbidden_hits(recommendation),
                },
                "early_warning": warning,
                "visual": {
                    **(visual.model_dump(mode="json") if visual else {}),
                    "gate_confidence": gate,
                    "gate_source": gate_source,
                    "resulting_state": photo_path,
                },
                "routing": routing,
                "fulfillment": {"message": fulfillment, "forbidden_hits": forbidden_hits(fulfillment)},
                "structured_outputs": structured,
                "delegations": provider.delegation_history,
                "errors": errors,
                "checks": checks,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if not all(checks.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
