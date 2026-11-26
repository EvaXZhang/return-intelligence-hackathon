from __future__ import annotations

import re

from ..domain.detail_codes import SIZE_KEYWORDS, has_phrase, normalize_details
from ..domain.enums import ReasonCategory
from ..domain.errors import ValidationError
from ..domain.models import ClassificationResult
from ..providers.simulated import SimulatedAIProvider

# Keyword tables for the deterministic simulated classifier (direction keywords live in detail_codes).
_GENERIC_SIZE = ("wrong size", "doesn t fit", "don t fit", "does not fit", "didn t fit", "尺码", "尺寸", "码数")
_COLOR = (
    "wrong color", "wrong colour", "colour", "different color", "color is", "color looks", "color was",
    "not the color", "shade", "颜色", "色差",
)
_PREFERENCE = ("dislike", "don t like", "do not like", "prefer", "style", "ugly", "不喜欢", "不好看", "款式")
_QUALITY = (
    "quality", "defect", "sole", "stitch", "torn", "broken",
    "peel", "crack", "glue", "seam", "rip", "hole", "质量", "开胶", "破",
)
_DELAYED = ("delayed", "late", "still shipping", "took too long", "晚到", "延迟", "迟到")
_MISSING_WRONG = (
    "missing", "never arrived", "wrong item", "not received", "didn t receive", "different item",
    "out of stock", "sold out", "backorder", "漏发", "少发", "没收到", "发错", "缺货",
)


class ReasonClassificationAgent:
    name = "Return Reason Classification Agent"

    def __init__(self, provider=None):
        self.provider = provider or SimulatedAIProvider()

    @staticmethod
    def _has(normalized: str, phrases: tuple[str, ...]) -> bool:
        return any(has_phrase(normalized, phrase) for phrase in phrases)

    @classmethod
    def _local_classification(cls, text: str) -> tuple[list[ReasonCategory], dict[str, str]]:
        # \w keeps CJK characters; punctuation (including apostrophes) becomes a space.
        normalized = re.sub(r"[^\w\s]", " ", text.casefold())
        categories: list[ReasonCategory] = []

        def add(category: ReasonCategory) -> None:
            if category not in categories:
                categories.append(category)

        too_small = dict(SIZE_KEYWORDS)["too_small"]
        too_large = dict(SIZE_KEYWORDS)["too_large"]
        # Category order is fixed: size, colour, preference, quality, delayed, missing.
        if cls._has(normalized, too_small + too_large + _GENERIC_SIZE):
            add(ReasonCategory.WRONG_SIZE)
        if cls._has(normalized, _COLOR):
            add(ReasonCategory.WRONG_COLOR)
        if cls._has(normalized, _PREFERENCE):
            add(ReasonCategory.PREFERENCE)
        if cls._has(normalized, _QUALITY):
            add(ReasonCategory.QUALITY)
        if cls._has(normalized, _DELAYED):
            add(ReasonCategory.DELAYED)
        if cls._has(normalized, _MISSING_WRONG):
            add(ReasonCategory.MISSING_WRONG)
        if not categories:
            add(ReasonCategory.OTHER)
        return categories, normalize_details(categories, {}, text)

    def classify(self, text: str) -> ClassificationResult:
        text = text.strip()
        if not 3 <= len(text) <= 1000:
            raise ValidationError("reason must be 3–1000 characters")

        if not self.provider.is_live:
            categories, details = self._local_classification(text)
            return ClassificationResult(
                categories=tuple(categories),
                details=details,
                customer_summary="Deterministic local classification for the synthetic demo.",
                provider_kind=self.provider.provider_kind,
                provider_label=self.provider.display_label,
            )

        raw = self.provider.classify_reason(text)
        allowed = {category.value: category for category in ReasonCategory}
        categories: list[ReasonCategory] = []
        for value in raw.get("categories", []):
            category = allowed.get(str(value))
            if category and category not in categories:
                categories.append(category)
        if not categories:
            categories = [ReasonCategory.OTHER]
        details = normalize_details(categories, raw.get("details") or {}, text)
        return ClassificationResult(
            categories=tuple(categories),
            details=details,
            customer_summary=str(raw.get("customer_summary", "")).strip(),
            provider_kind=self.provider.provider_kind,
            provider_label=self.provider.display_label,
        )
