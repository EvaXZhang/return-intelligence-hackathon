import pytest

from return_intelligence.agents.reason import ReasonClassificationAgent
from return_intelligence.agents.retention import RetentionRecommendationAgent
from return_intelligence.domain.detail_codes import (
    FULFILLMENT_ISSUES,
    QUALITY_SYMPTOMS,
    SIZE_DIRECTIONS,
    normalize_details,
)
from return_intelligence.domain.enums import ReasonCategory as R
from return_intelligence.integrations.strands_factory import _SPECIALIST_PROMPTS


def _classify(text):
    return ReasonClassificationAgent().classify(text)


def test_demo_sentence_is_too_small_and_offers_size_9(repo):
    result = _classify("The shoes are too small and tight; I want a larger size")
    assert result.categories == (R.WRONG_SIZE,) and result.details["size_direction"] == "too_small"
    item = repo.get_order_item("SYN-O-SIZE-001")
    item["similar_group"] = "RUNNER"
    options = RetentionRecommendationAgent(repo).recommend(item, result).options
    assert any(option.size == "9" and option.available > 0 for option in options)


@pytest.mark.parametrize(
    "text,direction",
    [
        ("I need a smaller size", "too_large"),
        ("wrong size", "unspecified"),
        ("They don't fit", "unspecified"),
        ("Too small but also too big in the toe", "unspecified"),
    ],
)
def test_size_direction(text, direction):
    result = _classify(text)
    assert result.categories == (R.WRONG_SIZE,) and result.details["size_direction"] == direction


@pytest.mark.parametrize("text", ["The color looks different from the photos", "wrong colour"])
def test_colour_phrasing(text):
    assert _classify(text).categories == (R.WRONG_COLOR,)


@pytest.mark.parametrize(
    "text,categories,details",
    [
        ("鞋子太小了", (R.WRONG_SIZE,), {"size_direction": "too_small"}),
        ("尺码太大", (R.WRONG_SIZE,), {"size_direction": "too_large"}),
        ("尺码不对", (R.WRONG_SIZE,), {"size_direction": "unspecified"}),
        ("颜色不对", (R.WRONG_COLOR,), {}),
        ("我不喜欢这个款式", (R.PREFERENCE,), {}),
        ("质量有问题，鞋底开胶", (R.QUALITY,), {"quality_symptom": "sole_separation"}),
        ("快递晚到了", (R.DELAYED,), {}),
        ("漏发了一只鞋", (R.MISSING_WRONG,), {"fulfillment_issue": "missing_item"}),
        # The reason field requires at least 3 characters, so "缺货" carries a trailing particle.
        ("缺货了", (R.MISSING_WRONG,), {"fulfillment_issue": "out_of_stock"}),
    ],
)
def test_chinese_inputs(text, categories, details):
    result = _classify(text)
    assert result.categories == categories and result.details == details


def test_word_boundaries_and_wrong_item():
    assert R.DELAYED not in _classify("chocolate stain on the box").categories
    result = _classify("I received the wrong item")
    assert result.categories == (R.MISSING_WRONG,) and result.details["fulfillment_issue"] == "wrong_item"
    out_of_stock = _classify("The shoes were out of stock and never shipped")
    assert out_of_stock.details["fulfillment_issue"] == "out_of_stock"
    assert R.PREFERENCE in _classify("I dislike the fit").categories


def test_stitching_came_loose_is_quality_only_and_keeps_the_same_pair_exchange(service):
    result = _classify("The stitching came loose")
    assert result.categories == (R.QUALITY,) and result.details == {"quality_symptom": "stitching_seam"}
    # SYN-O-DEFECT-001 is SYN-BOOT-300 · 9 · Black, and that exact pair is in stock.
    return_id = service.start_return("SYN-O-DEFECT-001")["return_id"]
    recommendation = service.submit_reason(return_id, "The stitching came loose")["recommendation"]
    assert recommendation["recommended_action"] == "EXCHANGE" and "EXCHANGE" in recommendation["choices"]
    assert [(o["sku"], o["size"], o["color"]) for o in recommendation["options"]] == [("SYN-BOOT-300", "9", "Black")]


def test_too_loose_fit_is_wrong_size_too_large():
    result = _classify("They feel too loose")
    assert result.categories == (R.WRONG_SIZE,) and result.details == {"size_direction": "too_large"}


class _FakeLiveReason:
    provider_kind = "fake_live"
    display_label = "FAKE LIVE PROVIDER"
    is_live = True

    def __init__(self, raw):
        self.raw = raw

    def classify_reason(self, text):
        return self.raw


def test_live_details_are_normalized_from_text_and_fallback():
    agent = ReasonClassificationAgent(
        _FakeLiveReason({"categories": ["Quality Issue"], "details": {"quality_symptom": "delamination"}, "customer_summary": "x"})
    )
    assert agent.classify("The sole is peeling away from the upper").details["quality_symptom"] == "sole_separation"
    raw = {
        "categories": ["Wrong Size", "Quality Issue", "Missing Item/Wrong Item"],
        "details": {"size_direction": "mystery", "quality_symptom": "mystery", "fulfillment_issue": "mystery", "requested_color": "Red"},
        "customer_summary": "x",
    }
    details = ReasonClassificationAgent(_FakeLiveReason(raw)).classify("Something odd happened").details
    assert details == {
        "size_direction": "unspecified",
        "quality_symptom": "other_quality",
        "fulfillment_issue": "other_fulfillment",
        "requested_color": "Red",
    }


def test_normalize_details_keeps_enum_members_and_maps_values():
    assert normalize_details([R.WRONG_SIZE], {"size_direction": "too_large"}, "too small") == {"size_direction": "too_large"}
    assert normalize_details(["Wrong Size"], {"size_direction": "too small"}) == {"size_direction": "too_small"}
    assert normalize_details(["Quality Issue"], {"quality_symptom": "broken zipper"}) == {"quality_symptom": "hardware_failure"}
    assert normalize_details(["Other"], {"note": "kept"}) == {"note": "kept"}


def test_reason_prompt_lists_allowed_detail_values():
    prompt = _SPECIALIST_PROMPTS["reason"]
    for value in SIZE_DIRECTIONS + QUALITY_SYMPTOMS + FULFILLMENT_ISSUES:
        assert value in prompt
