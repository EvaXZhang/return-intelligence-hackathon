"""Fail-closed configuration for local UI plus user-authorized Bedrock inference."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Business clock used when DEMO_CLOCK is unset; aligned with the seeded synthetic history.
DEFAULT_DEMO_CLOCK = "2026-01-15T12:00:00+00:00"
VALID_SEASONS = ("SUMMER", "WINTER", "TRANSITION")


class ConfigurationError(RuntimeError):
    pass


class IntegrationDisabledError(ConfigurationError):
    pass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be exactly true or false")
    return value == "true"


def _demo_clock(raw: str) -> datetime | None:
    value = raw.strip()
    if not value or value.lower() == "now":
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError("DEMO_CLOCK must be an ISO-8601 timestamp, 'now', or empty") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    ai_backend: str = "bedrock"
    aws_integration_enabled: bool = True
    deployment_enabled: bool = False
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "amazon.nova-lite-v1:0"
    db_path: Path = Path("data/return_intelligence.db")
    upload_dir: Path = Path("uploads")
    artifact_dir: Path = Path("artifacts")
    log_path: Path = Path("logs/application.log")
    # None = real UTC time (DEMO_CLOCK=now or empty).
    demo_clock: datetime | None = field(default_factory=lambda: datetime.fromisoformat(DEFAULT_DEMO_CLOCK))
    # None = derive the season from the business clock; set only for an explicit override.
    demo_season: str | None = None

    def __post_init__(self) -> None:
        if self.demo_season is not None and self.demo_season not in VALID_SEASONS:
            raise ConfigurationError("DEMO_SEASON must be SUMMER, WINTER or TRANSITION (or unset)")
        backend = self.ai_backend.lower()
        if backend not in {"simulated", "bedrock"}:
            raise ConfigurationError("AI_BACKEND must be simulated or bedrock")
        if backend == "bedrock":
            if not self.aws_integration_enabled:
                raise IntegrationDisabledError("Bedrock requires AWS_INTEGRATION_ENABLED=true")
            if not self.bedrock_model_id:
                raise IntegrationDisabledError("Bedrock requires BEDROCK_MODEL_ID")
        if self.deployment_enabled:
            raise IntegrationDisabledError("AWS resource deployment is disabled in this local prototype")

    def now(self) -> datetime:
        """Business clock: the fixed demo clock, or real UTC time when DEMO_CLOCK=now."""
        return self.demo_clock or datetime.now(timezone.utc)

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "AppConfig":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()

        def local_path(name: str, default: str) -> Path:
            raw = Path(os.getenv(name, default))
            return raw if raw.is_absolute() else root / raw

        config = cls(
            project_root=root,
            ai_backend=os.getenv("AI_BACKEND", "bedrock"),
            aws_integration_enabled=_bool("AWS_INTEGRATION_ENABLED", True),
            deployment_enabled=_bool("DEPLOYMENT_ENABLED", False),
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"),
            db_path=local_path("DB_PATH", "data/return_intelligence.db"),
            upload_dir=local_path("UPLOAD_DIR", "uploads"),
            artifact_dir=local_path("ARTIFACT_DIR", "artifacts"),
            log_path=local_path("LOG_PATH", "logs/application.log"),
            demo_clock=_demo_clock(os.getenv("DEMO_CLOCK", DEFAULT_DEMO_CLOCK)),
            demo_season=(os.getenv("DEMO_SEASON") or "").strip().upper() or None,
        )
        for path in (config.db_path.parent, config.upload_dir, config.artifact_dir, config.log_path.parent):
            path.mkdir(parents=True, exist_ok=True)
        return config
