"""Fixed detail-code vocabularies shared by the classifier, early warning and prompts."""
from __future__ import annotations

import re
from typing import Iterable

SIZE_DIRECTIONS = ("too_small", "too_large", "unspecified")
QUALITY_SYMPTOMS = ("sole_separation", "stitching_seam", "material_damage", "hardware_failure", "other_quality")
FULFILLMENT_ISSUES = ("missing_item", "wrong_item", "out_of_stock", "other_fulfillment")

# Ordered by precedence: the first matching code wins.
FULFILLMENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("out_of_stock", ("out of stock", "sold out", "backorder", "缺货", "断货", "没货")),
    ("wrong_item", ("wrong item", "wrong shoe", "different item", "not what i ordered", "sent the wrong", "发错", "错发")),
    ("missing_item", ("missing", "never arrived", "not received", "didn t receive", "did not receive", "漏发", "少发", "没收到")),
)
QUALITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sole_separation", ("sole", "glue", "separat", "detach", "鞋底", "开胶", "脱胶")),
    ("stitching_seam", ("stitch", "seam", "thread", "缝", "线头")),
    ("material_damage", ("torn", "tear", "rip", "hole", "crack", "peel", "scuff", "破", "裂")),
    ("hardware_failure", ("zip", "lace", "buckle", "eyelet", "strap", "拉链", "鞋带")),
)
SIZE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("too_small", ("too small", "tight", "larger size", "bigger size", "size up", "太小", "偏小", "小了")),
    (
        "too_large",
        (
            "too large", "too big", "smaller size", "size down",
            # Fit phrases only: a bare "loose" also matches quality wording ("the stitching came loose").
            "too loose", "loose fit", "loose fitting", "fit is loose", "fit loose", "fits loose",
            "feel loose", "feels loose", "felt loose", "loose on my feet", "loose on my foot",
            "太大", "偏大", "大了",
        ),
    ),
)

_CATEGORY_KEYS = {
    "Wrong Size": ("size_direction", SIZE_DIRECTIONS, SIZE_KEYWORDS, "unspecified"),
    "Quality Issue": ("quality_symptom", QUALITY_SYMPTOMS, QUALITY_KEYWORDS, "other_quality"),
    "Missing Item/Wrong Item": ("fulfillment_issue", FULFILLMENT_ISSUES, FULFILLMENT_KEYWORDS, "other_fulfillment"),
}


def normalize_text(text: str) -> str:
    """Casefold and strip punctuation while keeping CJK and other word characters."""
    return re.sub(r"[^\w\s]", " ", str(text).casefold())


# Common English inflections allowed after an ASCII keyword ("soles", "peeling", "ripped", "zipper").
_INFLECTION = r"(?:s|es|d|ed|er|ing|ped|ping|per|pers|red|ring)?"
# Stems that are not words on their own and therefore match any word they start.
_PREFIX_STEMS = frozenset({"separat", "defect"})


def has_phrase(normalized: str, phrase: str) -> bool:
    """ASCII phrases match on word boundaries (so "late" never matches "chocolate");
    CJK phrases match by substring because \\b does not separate CJK characters."""
    if not phrase.isascii():
        return phrase in normalized
    tail = "" if phrase in _PREFIX_STEMS else _INFLECTION + r"\b"
    return re.search(r"\b" + re.escape(phrase) + tail, normalized) is not None


def match_code(normalized: str, table: Iterable[tuple[str, tuple[str, ...]]]) -> str | None:
    for code, phrases in table:
        if any(has_phrase(normalized, phrase) for phrase in phrases):
            return code
    return None


def size_direction(normalized: str) -> str:
    """Exactly one matching direction is kept; none or conflicting directions give 'unspecified'."""
    found = {code for code, phrases in SIZE_KEYWORDS if any(has_phrase(normalized, p) for p in phrases)}
    return found.pop() if len(found) == 1 else "unspecified"


def _map_value(key: str, value: str, table, normalized_text: str) -> str | None:
    if key == "size_direction":
        candidate = size_direction(normalize_text(value).replace("_", " "))
        if candidate != "unspecified":
            return candidate
        return size_direction(normalized_text) if normalized_text else None
    mapped = match_code(normalize_text(value).replace("_", " "), table)
    if mapped:
        return mapped
    return match_code(normalized_text, table) if normalized_text else None


def normalize_details(categories: Iterable, details: dict | None, text: str = "") -> dict[str, str]:
    """Map detail values onto the fixed enums for the classified categories.

    Enum members are kept. Otherwise the provider value is mapped, then the customer text,
    then the fallback (unspecified / other_*). Keys outside the three detail keys are kept unchanged.
    """
    result = {str(k): str(v) for k, v in (details or {}).items() if v is not None and str(v).strip()}
    normalized_text = normalize_text(text) if text else ""
    labels = {getattr(category, "value", category) for category in categories}
    for category, (key, allowed, table, fallback) in _CATEGORY_KEYS.items():
        value = result.get(key)
        if value in allowed:
            continue
        if category not in labels and value is None:
            continue
        mapped = _map_value(key, value or "", table, normalized_text)
        result[key] = mapped or fallback
    return result
