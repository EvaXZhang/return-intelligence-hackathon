"""User-authorized paid smoke through the real SupervisorService application path.

The seeded database, artifacts, uploads and log go to DB_PATH, ARTIFACT_DIR, UPLOAD_DIR and LOG_PATH when
they are set (for example under /tmp/ri_live_v2), otherwise to a throwaway temporary directory; never into
the project. --reason sets the customer's explanation (any language).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from return_intelligence.config import AppConfig
from return_intelligence.db.repositories import Repository
from return_intelligence.db.seed import seed_database
from return_intelligence.providers import create_provider
from return_intelligence.services.customer_copy import FORBIDDEN_CUSTOMER_TERMS, fallback_recommendation_text
from return_intelligence.services.supervisor import SupervisorService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REASON = "These shoes are too small and tight. I want to exchange for a larger size."
PATH_DEFAULTS = {"DB_PATH": "data/live-smoke.db", "ARTIFACT_DIR": "artifacts", "UPLOAD_DIR": "uploads", "LOG_PATH": "logs/app.log"}


def smoke_paths(temporary: Path) -> dict[str, Path]:
    paths = {name: Path(os.environ.get(name) or temporary / default).resolve() for name, default in PATH_DEFAULTS.items()}
    for name, path in paths.items():
        if path.is_relative_to(PROJECT_ROOT):
            raise SystemExit(f"{name} must be outside the project: this smoke seeds its own database")
    if paths["DB_PATH"].exists():
        raise SystemExit("DB_PATH must not exist yet: the early-warning check needs a freshly seeded database")
    return paths


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Paid live Bedrock smoke through SupervisorService.")
    parser.add_argument("--reason", default=DEFAULT_REASON, help="customer return explanation (any language)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        paths = smoke_paths(Path(temporary))
        db_path = paths["DB_PATH"]
        seed_database(db_path)
        config = AppConfig(
            project_root=PROJECT_ROOT,
            ai_backend="bedrock",
            aws_integration_enabled=True,
            deployment_enabled=False,
            aws_region="us-east-1",
            bedrock_model_id="amazon.nova-lite-v1:0",
            db_path=db_path,
            upload_dir=paths["UPLOAD_DIR"],
            artifact_dir=paths["ARTIFACT_DIR"],
            log_path=paths["LOG_PATH"],
        )
        provider = create_provider(config)
        structured = record_structured_outputs(provider)
        service = SupervisorService(
            Repository(db_path),
            config.artifact_dir,
            "WINTER",
            provider=provider,
            upload_root=config.upload_dir,
        )
        report: dict = {"provider": provider.provider_kind, "reason_text": args.reason}
        try:
            request = service.start_return("SYN-O-SIZE-001")
            result = service.submit_reason(request["return_id"], args.reason)
            classification = result["classification"]
            recommendation = result["recommendation"]
            emails = service.get_customer_view(request["return_id"])["messages"]
            report.update(
                classification={key: classification[key] for key in ("categories", "details", "customer_summary")},
                recommendation={
                    "recommended_action": recommendation["recommended_action"],
                    "choices": recommendation["choices"],
                    "options": [option["option_id"] for option in recommendation["options"]],
                    "explanation": recommendation["explanation"],
                    "explanation_is_fallback": recommendation["explanation"]
                    == fallback_recommendation_text(recommendation["recommended_action"]),
                },
                mock_emails=[{"subject": email["subject"], "body": email["body"]} for email in emails],
            )
            options = recommendation["options"]
            if not options:
                raise AssertionError("Live app flow returned no deterministic in-stock exchange option")
            report["decision"] = service.record_decision(
                request["return_id"],
                "EXCHANGE",
                options[0]["option_id"],
                operation_id="live-bedrock-app-smoke",
            )
            alerts = service.repo.all(
                """SELECT dimension_type,dimension_value,category,detail_code,complaint_count,units_sold,recommendation
                FROM early_warning_alerts ORDER BY dimension_type"""
            )
            report["alerts"] = alerts
            agents = [entry["agent_name"] for entry in service.get_staff_view(request["return_id"])["activity"]]
            report["activity_agents"] = agents
            customer_texts = [recommendation["explanation"]] + [f"{email['subject']}\n{email['body']}" for email in emails]
            report["customer_forbidden_hits"] = sorted({term for text in customer_texts for term in forbidden_hits(text)})
            required = {"Supervisor", "Return Reason Classification Agent", "Customer Retention & Recommendation Agent"}
            report["checks"] = {
                "activity_agents_present": required.issubset(set(agents)),
                "classified_wrong_size_too_small": "Wrong Size" in classification["categories"]
                and classification["details"].get("size_direction") == "too_small",
                "recommended_exchange": recommendation["recommended_action"] == "EXCHANGE",
                "mock_email_recorded": bool(emails),
                "customer_texts_safe": not report["customer_forbidden_hits"],
                # The fifth sizing complaint must create an alert, explained by the live Early Warning Agent.
                "early_warning_alert_created": bool(alerts),
            }
        finally:
            report["structured_outputs"] = structured
            report["delegations"] = provider.delegation_history
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        if not all(report["checks"].values()):
            sys.exit(1)


if __name__ == "__main__":
    main()
