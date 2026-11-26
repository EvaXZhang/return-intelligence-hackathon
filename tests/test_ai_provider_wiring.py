from return_intelligence.agents.reason import ReasonClassificationAgent
from return_intelligence.agents.retention import RetentionRecommendationAgent
from return_intelligence.agents.routing import RoutingOptimizationAgent
from return_intelligence.agents.visual import VisualConditionAssessmentAgent
from return_intelligence.domain.enums import EligibilityState, ReasonCategory
from tests.fakes import FakeLiveProvider


def test_live_provider_drives_reason_and_inventory_constrained_recommendation(repo):
    provider = FakeLiveProvider()
    classification = ReasonClassificationAgent(provider).classify("Please exchange these tight shoes")
    assert classification.categories == (ReasonCategory.WRONG_SIZE,)
    assert classification.provider_kind == "fake_live"
    item = repo.get_order_item("SYN-O-SIZE-001")
    item["similar_group"] = "RUNNER"
    recommendation = RetentionRecommendationAgent(repo, provider).recommend(item, classification)
    assert recommendation.options
    assert recommendation.explanation == "Live explanation constrained to verified options."
    assert provider.calls == ["reason", "retention"]


def test_live_visual_uses_model_evidence_and_model_confidence():
    provider = FakeLiveProvider(
        visual={
            "evidence_sufficient": True,
            "eligibility_state": "ELIGIBLE_UNWORN",
            "preliminary_grade": "A",
            "evidence": ["clean soles"],
            "confidence": 0.97,
        }
    )
    result = VisualConditionAssessmentAgent(provider).assess(
        "live_upload",
        images={angle: b"image" for angle in ("front", "left", "right")},
    )
    assert result.eligibility_state == EligibilityState.ELIGIBLE_UNWORN
    assert result.preliminary_grade.value == "A"
    assert result.confidence == 0.97
    assert result.provider_kind == "fake_live"


def test_routing_matrix_result_is_fixed_before_ai_explanation(repo):
    provider = FakeLiveProvider()
    decision = RoutingOptimizationAgent(repo, provider).route("A", 1, "SYN-ZONE-1", "SHIP")
    assert decision.destination_type.value == "OUTLET"
    assert decision.destination_id
    assert "Explained locked OUTLET" in decision.ai_explanation
    assert provider.calls == ["routing"]
