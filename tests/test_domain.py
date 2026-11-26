import pytest
from pydantic import ValidationError
from return_intelligence.domain.enums import DestinationType,EligibilityState,Grade
from return_intelligence.domain.models import VisualAssessmentResult
from return_intelligence.domain.policy import needs_review
from return_intelligence.domain.routing_matrix import route_type
from return_intelligence.domain.errors import PolicyViolation

@pytest.mark.parametrize(('condition','season','expected'),[
(Grade.A,0,DestinationType.RETAIL_STORE),(Grade.A,1,DestinationType.OUTLET),(Grade.B,0,DestinationType.OUTLET),(Grade.B,1,DestinationType.OUTLET),(Grade.C,0,DestinationType.COMPANY_WAREHOUSE),(Grade.C,1,DestinationType.COMPANY_WAREHOUSE),(EligibilityState.WORN_INELIGIBLE,0,DestinationType.REJECT),(EligibilityState.WORN_INELIGIBLE,1,DestinationType.REJECT)])
def test_exact_eight_cell_routing_matrix(condition,season,expected):assert route_type(condition,season)==expected
def test_seasonality_never_changes_grade_a():
    grade=Grade.A;assert route_type(grade,1)==DestinationType.OUTLET;assert grade==Grade.A
def test_review_boundary_at_85():assert not needs_review(.90) and not needs_review(.85) and needs_review(.849)
def test_worn_and_defect_cannot_be_grade_c():
    with pytest.raises(ValidationError):VisualAssessmentResult(evidence_sufficient=True,eligibility_state=EligibilityState.WORN_INELIGIBLE,preliminary_grade=Grade.C)
    with pytest.raises(PolicyViolation):route_type(EligibilityState.SUSPECTED_DEFECT,0)
def test_insufficient_evidence_has_no_grade():
    result=VisualAssessmentResult(evidence_sufficient=False,retakes=('front',));assert result.preliminary_grade is None and result.confidence is None
def test_missing_or_invalid_confidence_fails_safe_to_review():
    assert all(needs_review(value) for value in (None,float("nan"),-.01,1.01,"0.95",True))
