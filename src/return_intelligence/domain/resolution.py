"""Fulfillment-type resolution paths (plan design decision 6)."""
from __future__ import annotations

from typing import Iterable

NORMAL = "NORMAL"
MISSING_ITEM = "MISSING_ITEM"
OUT_OF_STOCK = "OUT_OF_STOCK"
SERVICE = "SERVICE"
RESOLUTION_PATHS = (NORMAL, MISSING_ITEM, OUT_OF_STOCK, SERVICE)
# Paths where the customer never received the item, so no photos or return label are needed.
NOT_RECEIVED_PATHS = (MISSING_ITEM, OUT_OF_STOCK)

_MISSING_WRONG = "Missing Item/Wrong Item"
_DELAYED = "Delayed Shipping"


def _labels(categories: Iterable) -> set[str]:
    return {getattr(category, "value", category) for category in categories}


def resolution_path(categories: Iterable, details: dict | None, delivered) -> str:
    """Missing/Wrong + out_of_stock -> OUT_OF_STOCK; Missing/Wrong + missing_item -> MISSING_ITEM;
    other Missing/Wrong or an undelivered order -> SERVICE; delivered otherwise -> NORMAL."""
    labels = _labels(categories)
    issue = (details or {}).get("fulfillment_issue")
    if _MISSING_WRONG in labels:
        if issue == "out_of_stock":
            return OUT_OF_STOCK
        if issue == "missing_item":
            return MISSING_ITEM
        return SERVICE
    if not delivered:
        return SERVICE
    return NORMAL


def legacy_resolution_path(categories: Iterable, delivered) -> str:
    """Rule used before v2 for rows whose recommendation has no stored path."""
    labels = _labels(categories)
    if _DELAYED in labels or _MISSING_WRONG in labels or not delivered:
        return SERVICE
    return NORMAL
