"""D3: the AI confidence gate (>=0.85 skips review, <0.85 goes to staff) and the staff-only demo override."""
import io

import pytest
from PIL import Image

from return_intelligence.domain.errors import ValidationError
from return_intelligence.services.supervisor import SupervisorService
from tests.conftest import advance_to_photos
from tests.fakes import FakeLiveProvider

ANGLES = ("front", "left", "right")


def _png():
    out = io.BytesIO()
    Image.new("RGB", (800, 600), "green").save(out, "PNG")
    return out.getvalue()


def _assessment(repo, return_id):
    return repo.one(
        "SELECT * FROM visual_assessments WHERE return_id=? ORDER BY created_at DESC LIMIT 1", (return_id,)
    )


def test_exactly_090_skips_staff_review(service, repo):
    rid = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    assert service.submit_photos(rid, "eligible_a_90")["state"] == "READY_TO_ROUTE"
    assessment = _assessment(repo, rid)
    assert assessment["simulated_calibrated_confidence"] == 0.90 and assessment["ai_confidence"] == 0.90
    assert assessment["confidence_source"] == "AI"
    assert repo.open_review(rid) is None
    assert repo.get_return(rid)["final_grade"] == "A"


def test_095_skips_review(service, repo):
    rid = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    assert service.submit_photos(rid, "eligible_a_95")["state"] == "READY_TO_ROUTE"
    assert repo.open_review(rid) is None
    assert service.repo.get_return(rid)["final_grade"] == "A"


def test_worn_high_confidence_closes_without_review(service, repo):
    rid = advance_to_photos(service, "SYN-O-WORN-001")
    assert service.submit_photos(rid, "worn_ineligible")["state"] == "INELIGIBLE_CLOSED"
    assert repo.open_review(rid) is None
    row = repo.get_return(rid)
    assert row["simulated_calibrated_confidence"] == 0.97 and row["final_grade"] is None


def test_worn_low_confidence_goes_to_review_then_staff_decide(service, repo):
    rid = advance_to_photos(service, "SYN-O-WORN-001")
    assert service.submit_photos(rid, "worn_low_confidence")["state"] == "AWAITING_REVIEW"
    review = repo.open_review(rid)
    assert review["ai_eligibility_state"] == "WORN_INELIGIBLE" and review["preliminary_grade"] is None
    row = repo.get_return(rid)
    assert row["condition_state"] == "WORN_INELIGIBLE" and row["preliminary_grade"] is None
    approved = service.resolve_review(rid, "APPROVE")
    assert approved["state"] == "INELIGIBLE_CLOSED" and approved["final_grade"] is None

    other = advance_to_photos(service, "SYN-O-WORN-001")
    service.submit_photos(other, "worn_low_confidence")
    overridden = service.resolve_review(other, "OVERRIDE_B")
    assert overridden["state"] == "READY_TO_ROUTE" and overridden["final_grade"] == "B"
    assert overridden["condition_state"] == "ELIGIBLE_UNWORN"


def test_defect_high_confidence_holds_and_low_confidence_reviews(service, repo):
    rid = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
    assert service.submit_photos(rid, "suspected_defect")["state"] == "DEFECT_HOLD"
    assert repo.open_review(rid) is None

    low = advance_to_photos(service, "SYN-O-DEFECT-001", "sole is broken quality issue")
    assert service.submit_photos(low, "defect_low_confidence")["state"] == "AWAITING_REVIEW"
    assert repo.open_review(low)["ai_eligibility_state"] == "SUSPECTED_DEFECT"
    assert service.resolve_review(low, "APPROVE")["state"] == "DEFECT_HOLD"


def test_force_75_sends_high_ai_value_to_review(service, repo):
    service.set_confidence_override("FORCE_75", "STAFF-DEMO-1")
    rid = advance_to_photos(service, "SYN-O-A95-001", "wrong color")
    assert service.submit_photos(rid, "eligible_a_95")["state"] == "AWAITING_REVIEW"
    assessment = _assessment(repo, rid)
    assert assessment["simulated_calibrated_confidence"] == 0.75
    assert assessment["ai_confidence"] == 0.95
    assert assessment["confidence_source"] == "DEMO_OVERRIDE"
    assert repo.get_return(rid)["simulated_calibrated_confidence"] == 0.75


@pytest.mark.parametrize(
    ("mode", "order_id", "fixture", "gate"),
    [("FORCE_75", "SYN-O-A95-001", "eligible_a_95", 0.75), ("FORCE_95", "SYN-O-LOW75-001", "eligible_75", 0.95)],
)
def test_customer_view_hides_gate_confidence_and_override(service, mode, order_id, fixture, gate):
    service.set_confidence_override(mode, "STAFF-DEMO-1")
    rid = advance_to_photos(service, order_id)
    service.submit_photos(rid, fixture)
    customer = service.get_customer_view(rid)
    assert customer["simulated_calibrated_confidence"] is None
    for key in ("simulated_calibrated_confidence", "ai_confidence", "confidence_source"):
        assert customer["latest_assessment"][key] is None, key
    # Staff still see the gate value actually used and that the override produced it.
    staff = service.get_staff_view(rid)["request"]
    assert staff["simulated_calibrated_confidence"] == gate
    assert staff["latest_assessment"]["simulated_calibrated_confidence"] == gate
    assert staff["latest_assessment"]["confidence_source"] == "DEMO_OVERRIDE"


def test_force_95_skips_review_for_low_ai_value(service, repo):
    service.set_confidence_override("FORCE_95", "STAFF-DEMO-1")
    rid = advance_to_photos(service, "SYN-O-LOW75-001")
    assert service.submit_photos(rid, "eligible_75")["state"] == "READY_TO_ROUTE"
    assert _assessment(repo, rid)["confidence_source"] == "DEMO_OVERRIDE"


def test_override_persists_across_service_instances_and_rejects_bogus_mode(service, repo, tmp_path):
    assert service.get_confidence_override() == "AI"
    service.set_confidence_override("FORCE_75", "STAFF-DEMO-1")
    other = SupervisorService(type(repo)(repo.db_path), tmp_path / "artifacts", "WINTER")
    assert other.get_confidence_override() == "FORCE_75"
    with pytest.raises(ValidationError):
        other.set_confidence_override("FORCE_50", "STAFF-DEMO-1")
    with pytest.raises(ValidationError):
        other.set_confidence_override("AI", "   ")
    assert other.get_confidence_override() == "FORCE_75"


def test_unclear_with_override_still_requires_retake(service, repo):
    service.set_confidence_override("FORCE_95", "STAFF-DEMO-1")
    rid = advance_to_photos(service, "SYN-O-UNCLEAR-001")
    assert service.submit_photos(rid, "unclear")["state"] == "RETAKE_REQUIRED"
    assessment = _assessment(repo, rid)
    assert assessment["simulated_calibrated_confidence"] is None
    assert assessment["ai_confidence"] is None and assessment["confidence_source"] is None
    assert repo.get_return(rid)["simulated_calibrated_confidence"] is None


@pytest.mark.parametrize(("value", "expected"), [(0.85, "READY_TO_ROUTE"), (0.849, "AWAITING_REVIEW"), (None, "AWAITING_REVIEW")])
def test_live_model_confidence_drives_the_gate(repo, tmp_path, value, expected):
    visual = {
        "evidence_sufficient": True,
        "eligibility_state": "ELIGIBLE_UNWORN",
        "preliminary_grade": "A",
        "evidence": ["clean uppers"],
        "confidence": value,
    }
    live = SupervisorService(
        repo, tmp_path / "artifacts", "WINTER", provider=FakeLiveProvider(visual=visual), upload_root=tmp_path / "uploads"
    )
    rid = advance_to_photos(live, "SYN-O-A95-001", "wrong color")
    # The local photo store validates real images, so upload real PNG bytes.
    assert live.submit_photos(rid, "live_upload", uploads={angle: _png() for angle in ANGLES})["state"] == expected
    assessment = _assessment(repo, rid)
    assert assessment["ai_confidence"] == value and assessment["confidence_source"] == "AI"
    assert assessment["fixture_key"] == "live_upload"
