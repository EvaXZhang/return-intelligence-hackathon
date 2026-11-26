from .enums import EligibilityState, Grade
from .errors import PolicyViolation


def needs_review(confidence: float | None) -> bool:
    # Missing or invalid confidence fails safe to staff review; exactly 0.85 is auto-approved.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return True
    return not 0.85 <= confidence <= 1.0

def validate_grade(eligibility: EligibilityState, grade: Grade | None) -> None:
    if eligibility != EligibilityState.ELIGIBLE_UNWORN and grade is not None:
        raise PolicyViolation("only eligible unworn shoes can receive A/B/C")
    if eligibility == EligibilityState.ELIGIBLE_UNWORN and grade is None:
        raise PolicyViolation("eligible unworn routing requires a grade")

def can_fulfill(row: dict, review_open: bool, route: dict | None) -> None:
    if row.get("condition_state") != "ELIGIBLE_UNWORN": raise PolicyViolation("return is not eligible/unworn")
    if row.get("final_grade") not in {"A","B","C"}: raise PolicyViolation("final grade is required")
    if review_open: raise PolicyViolation("staff review must be resolved")
    if not route or route.get("destination_type") == "REJECT" or not route.get("destination_id"): raise PolicyViolation("valid route and destination required")
    if row.get("fulfillment_mode") not in {"SHIP","DROPOFF"}: raise PolicyViolation("fulfillment mode required")
