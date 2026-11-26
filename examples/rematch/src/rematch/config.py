"""Environment-only configuration; credentials use the standard AWS chain."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""
    confidence_threshold: float = 0.75
    min_margin: float = 0.0

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("REMATCH_MODE", "demo").strip().lower()
        if mode not in {"demo", "aws"}:
            raise ValueError("REMATCH_MODE must be 'demo' or 'aws'")
        return cls(
            mode=mode,
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "").strip(),
            confidence_threshold=float(os.getenv("REMATCH_CONFIDENCE_THRESHOLD", "0.75")),
            min_margin=float(os.getenv("REMATCH_MIN_MARGIN", "0.00")),
        )

    def aws_readiness_error(self) -> str | None:
        if self.mode != "aws":
            return None
        if not self.bedrock_model_id:
            return "BEDROCK_MODEL_ID is required in AWS mode. Switch to Demo mode for the credential-free path."
        return None
