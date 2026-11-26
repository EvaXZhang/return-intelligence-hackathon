"""Bedrock visual contract via a fake runtime (BedrockProvider.__new__; no AWS call is ever made)."""
import io

import pytest
from PIL import Image
from pydantic import ValidationError

from return_intelligence.agents.visual import VisualConditionAssessmentAgent
from return_intelligence.integrations.strands_factory import _SPECIALIST_PROMPTS, VisualAgentOutput
from tests.fakes import make_fake_bedrock_provider

FORBIDDEN_PROMPT = "do not output a confidence probability"
ANGLES = ("front", "left", "right")


def _png():
    out = io.BytesIO()
    Image.new("RGB", (800, 600), "green").save(out, "PNG")
    return out.getvalue()


def _visual(**overrides):
    data = {
        "evidence_sufficient": True,
        "eligibility_state": "ELIGIBLE_UNWORN",
        "preliminary_grade": "A",
        "evidence": ["clean uppers"],
    }
    data.update(overrides)
    return data


def _prompt_texts(provider):
    texts = []
    for _key, prompt in provider._runtime.prompts:
        texts.extend(block["text"] for block in prompt if isinstance(block, dict) and "text" in block)
    return texts


def test_visual_output_normalises_confidence():
    assert VisualAgentOutput(**_visual(confidence=0.93)).confidence == 0.93
    assert VisualAgentOutput(**_visual(confidence=93)).confidence == pytest.approx(0.93)
    assert VisualAgentOutput(**_visual(confidence="93%")).confidence == pytest.approx(0.93)
    assert VisualAgentOutput(**_visual(confidence="0.9")).confidence == pytest.approx(0.9)
    insufficient = VisualAgentOutput(evidence_sufficient=False, retakes=["Front: blurry"], confidence=0.8)
    assert insufficient.confidence is None
    with pytest.raises(ValidationError):
        VisualAgentOutput(**_visual(confidence=150))
    with pytest.raises(ValidationError):
        VisualAgentOutput(**_visual(confidence=-0.2))


def test_prompts_ask_for_confidence():
    assert FORBIDDEN_PROMPT not in _SPECIALIST_PROMPTS["visual"].casefold()
    assert "confidence" in _SPECIALIST_PROMPTS["visual"]
    provider = make_fake_bedrock_provider({"visual": _visual(confidence=0.91)})
    provider.assess_visual_evidence("live_upload", {angle: _png() for angle in ANGLES})
    content_text = " ".join(_prompt_texts(provider))
    assert FORBIDDEN_PROMPT not in content_text.casefold()
    assert "confidence" in content_text


def test_model_confidence_passes_through_to_the_agent():
    provider = make_fake_bedrock_provider({"visual": _visual(confidence=0.91)})
    raw = provider.assess_visual_evidence("live_upload", {angle: _png() for angle in ANGLES})
    assert raw["confidence"] == 0.91
    result = VisualConditionAssessmentAgent(provider).assess("live_upload", images={angle: _png() for angle in ANGLES})
    assert result.confidence == 0.91


def test_insufficient_evidence_has_retakes_and_no_confidence():
    provider = make_fake_bedrock_provider(
        {"visual": {"evidence_sufficient": False, "retakes": ["Left photo is too dark"], "confidence": 0.8}}
    )
    raw = provider.assess_visual_evidence("live_upload", {angle: _png() for angle in ANGLES})
    assert raw["confidence"] is None and raw["retakes"] == ["Left: please take one clearer photo."]
    result = VisualConditionAssessmentAgent(provider).assess("live_upload", images={angle: _png() for angle in ANGLES})
    assert not result.evidence_sufficient and result.confidence is None


def test_ungraded_eligible_output_downgrades_to_retake_without_confidence():
    # Both the first call and the grade-repair call return no grade, so the provider asks for a retake.
    provider = make_fake_bedrock_provider({"visual": _visual(preliminary_grade=None, confidence=0.95)})
    raw = provider.assess_visual_evidence("live_upload", {angle: _png() for angle in ANGLES})
    assert raw["evidence_sufficient"] is False and raw["confidence"] is None
    assert len(provider._runtime.prompts) == 2
    _key, repair_prompt = provider._runtime.prompts[1]
    assert "confidence" in repair_prompt[0]["text"]
