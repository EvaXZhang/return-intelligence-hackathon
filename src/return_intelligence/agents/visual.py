from __future__ import annotations

from ..domain.enums import EligibilityState, Grade
from ..domain.errors import ValidationError
from ..domain.models import VisualAssessmentResult
from ..providers.simulated import SimulatedAIProvider


class VisualConditionAssessmentAgent:
    name = "Visual Condition Assessment Agent"
    required_angles = ("front", "left", "right")
    fixtures = {
        "eligible_a_95": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.ELIGIBLE_UNWORN,
            preliminary_grade=Grade.A,
            confidence=0.95,
            evidence=("clean synthetic uppers", "no visible wear in the three synthetic views"),
        ),
        "eligible_75": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.ELIGIBLE_UNWORN,
            preliminary_grade=Grade.B,
            confidence=0.75,
            evidence=("minor handling marks in synthetic fixture",),
        ),
        "eligible_a_90": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.ELIGIBLE_UNWORN,
            preliminary_grade=Grade.A,
            confidence=0.90,
            evidence=("clean synthetic uppers", "slight glare on the left synthetic view"),
        ),
        "worn_ineligible": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.WORN_INELIGIBLE,
            confidence=0.97,
            evidence=("simulated visible wear",),
        ),
        "worn_low_confidence": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.WORN_INELIGIBLE,
            confidence=0.80,
            evidence=("simulated faint creasing that may be wear",),
            uncertainty=("creasing could be packaging marks",),
        ),
        "suspected_defect": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.SUSPECTED_DEFECT,
            confidence=0.96,
            evidence=("simulated possible material separation",),
        ),
        "defect_low_confidence": dict(
            evidence_sufficient=True,
            eligibility_state=EligibilityState.SUSPECTED_DEFECT,
            confidence=0.80,
            evidence=("simulated small gap near the sole edge",),
            uncertainty=("gap could be a shadow",),
        ),
        "unclear": dict(
            evidence_sufficient=False,
            retakes=("Front: please take one clearer photo.",),
        ),
    }

    def __init__(self, provider=None):
        self.provider = provider or SimulatedAIProvider()

    def assess(
        self,
        fixture_key: str,
        angles: tuple[str, ...] = required_angles,
        images: dict[str, bytes] | None = None,
    ) -> VisualAssessmentResult:
        missing = set(self.required_angles) - set(angles)
        if missing:
            return VisualAssessmentResult(
                evidence_sufficient=False,
                retakes=tuple(f"{angle.title()}: please add this required photo." for angle in sorted(missing)),
                provider_kind=self.provider.provider_kind,
                provider_label=self.provider.display_label,
            )

        if not self.provider.is_live:
            if fixture_key not in self.fixtures:
                raise ValidationError("unknown synthetic visual fixture")
            return VisualAssessmentResult(
                **self.fixtures[fixture_key],
                provider_kind=self.provider.provider_kind,
                provider_label=self.provider.display_label,
            )

        if not images:
            raise ValidationError("live Bedrock visual assessment requires Front, Left, and Right photos")
        raw = self.provider.assess_visual_evidence(fixture_key, images)
        sufficient = bool(raw.get("evidence_sufficient"))
        eligibility = EligibilityState(raw["eligibility_state"]) if raw.get("eligibility_state") else None
        grade = Grade(raw["preliminary_grade"]) if raw.get("preliminary_grade") else None
        # The model's self-reported confidence drives the gate for every eligibility state; none when photos are unusable.
        confidence = raw.get("confidence") if sufficient else None
        return VisualAssessmentResult(
            evidence_sufficient=sufficient,
            eligibility_state=eligibility,
            preliminary_grade=grade,
            confidence=confidence,
            evidence=tuple(str(value) for value in raw.get("evidence", [])),
            retakes=tuple(str(value) for value in raw.get("retakes", [])),
            uncertainty=tuple(str(value) for value in raw.get("uncertainty", [])),
            provider_kind=self.provider.provider_kind,
            provider_label=self.provider.display_label,
        )
