from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import DestinationType, EligibilityState, Grade, ReasonCategory


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=False)


class ClassificationResult(FrozenModel):
    categories: tuple[ReasonCategory, ...]
    details: dict[str, str] = Field(default_factory=dict)
    customer_summary: str = ""
    provider_kind: str = "simulated"
    provider_label: str = "SIMULATED AI OUTPUT"


class InventoryOption(FrozenModel):
    option_id: str
    sku: str
    size: str
    color: str
    destination_id: str
    available: int


class RecommendationResult(FrozenModel):
    options: tuple[InventoryOption, ...] = ()
    choices: tuple[str, ...] = ("EXCHANGE", "KEEP", "REFUND")
    explanation: str = "Clearly simulated recommendation; inventory checked locally."
    provider_kind: str = "simulated"
    provider_label: str = "SIMULATED AI OUTPUT"
    recommended_action: str = "REFUND"
    resolution_path: str = "NORMAL"


class VisualAssessmentResult(FrozenModel):
    evidence_sufficient: bool
    eligibility_state: EligibilityState | None = None
    preliminary_grade: Grade | None = None
    # AI self-reported (live) or fixture (simulated) confidence; None means the gate fails safe to staff review.
    confidence: float | None = Field(default=None, ge=0, le=1)
    retakes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    provider_kind: str = "simulated"
    provider_label: str = "SIMULATED AI OUTPUT — deterministic fixture"

    @model_validator(mode="after")
    def validate_condition(self):
        if not self.evidence_sufficient and any(
            (self.eligibility_state, self.preliminary_grade, self.confidence is not None)
        ):
            raise ValueError("insufficient evidence cannot receive condition, grade, or confidence")
        if self.eligibility_state in {EligibilityState.WORN_INELIGIBLE, EligibilityState.SUSPECTED_DEFECT} and self.preliminary_grade:
            raise ValueError("worn/defect cannot receive A/B/C")
        if self.preliminary_grade and self.eligibility_state != EligibilityState.ELIGIBLE_UNWORN:
            raise ValueError("only eligible unworn shoes can receive A/B/C")
        return self


class SeasonalityResult(FrozenModel):
    flag: int = Field(ge=0, le=1)
    season: str
    reason: str
    source: str = "override"
    as_of: str | None = None
    profile: str | None = None


class RoutingDecision(FrozenModel):
    destination_type: DestinationType
    destination_id: str | None = None
    intake_location_id: str | None = None
    intake_location_name: str | None = None
    intake_location_address: str | None = None
    return_fee: float = Field(default=0, ge=0)
    score: float | None = None
    score_components: dict[str, Any] = Field(default_factory=dict)
    dropoff_candidates: tuple[dict[str, Any], ...] = ()
    rationale: str
    ai_explanation: str = ""


class AlertEvaluation(FrozenModel):
    alerted: bool
    complaint_count: int
    units_sold: int
    complaint_rate: float
    baseline_rate: float | None = None
    lift: float | None = None
    recommendation: str = "No threshold-crossing suspected pattern."
    provider_kind: str = "deterministic"
    level: str | None = None
    dimension_value: str | None = None
    category: str | None = None
    detail_code: str | None = None
    baseline_available: bool = False
    alert_id: str | None = None


class ArtifactResult(FrozenModel):
    artifact_id: str
    artifact_type: str
    local_path: str
    sha256: str
    demo_marking: str = "DEMO / NOT VALID FOR SHIPPING"
    customer_instructions: str = ""


class ActivityEntry(FrozenModel):
    agent: str
    action: str
    rationale: str
    input: dict[str, Any]
    output: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
