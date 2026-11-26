from __future__ import annotations

from ..domain.enums import ReasonCategory
from ..domain.models import InventoryOption, RecommendationResult
from ..domain.resolution import MISSING_ITEM, NORMAL, OUT_OF_STOCK, SERVICE, resolution_path
from ..providers.simulated import SimulatedAIProvider

MAX_OPTIONS = 5
RETURN_METHODS = {"DROPOFF": "FREE at the nearest eligible store", "SHIP": "$9 prepaid label"}


def _size(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class RetentionRecommendationAgent:
    name = "Customer Retention & Recommendation Agent"

    def __init__(self, repo, provider=None):
        self.repo = repo
        self.provider = provider or SimulatedAIProvider()

    @staticmethod
    def _size_matches(row, item, direction) -> bool:
        current, size = _size(item["size"]), _size(row["size"])
        if direction == "too_small":
            return current is not None and size is not None and size > current
        if direction == "too_large":
            return current is not None and size is not None and size < current
        if direction == "unspecified":
            return str(row["size"]) != str(item["size"])
        return str(row["size"]) == str(item["size"])

    def _similar(self, item, direction=None, exclude_sku_color=False):
        """similar_group items in the needed sizes, excluding the exact variant (and optionally the SKU+colour)."""
        rows = []
        for row in self.repo.similar_inventory(item.get("similar_group")):
            if row["sku"] == item["sku"] and row["color"] == item["color"]:
                if exclude_sku_color or str(row["size"]) == str(item["size"]):
                    continue
            if self._size_matches(row, item, direction):
                rows.append(row)
        return rows

    def _normal_rows(self, item, categories, details):
        if ReasonCategory.WRONG_SIZE in categories:
            direction = details.get("size_direction") or "unspecified"
            rows = [
                row
                for row in self.repo.inventory_options(item["sku"], color=item["color"])
                if self._size_matches(row, item, direction)
            ]
            return rows or self._similar(item, direction)
        if ReasonCategory.WRONG_COLOR in categories:
            rows = [row for row in self.repo.inventory_options(item["sku"], size=item["size"]) if row["color"] != item["color"]]
            return rows or self._similar(item, exclude_sku_color=True)
        if ReasonCategory.PREFERENCE in categories:
            return self._similar(item)
        if categories - {ReasonCategory.DELAYED}:
            # Quality Issue / Other: the exact variant, else same-size similar styles.
            rows = self.repo.inventory_options(item["sku"], size=item["size"], color=item["color"])
            return rows or self._similar(item)
        return []  # Delayed-only: the shoes arrived, there is nothing to swap.

    def _rows_for_path(self, path, item, categories, details):
        if path == NORMAL:
            return self._normal_rows(item, categories, details)
        if path == MISSING_ITEM:
            rows = self.repo.inventory_options(item["sku"], size=item["size"], color=item["color"])
            return rows or self._similar(item)
        if path == OUT_OF_STOCK:
            return self._similar(item, exclude_sku_color=True)
        return []

    @staticmethod
    def _choices(path, has_options) -> tuple[str, ...]:
        if path == SERVICE:
            return ("SERVICE_RESOLUTION", "REFUND")
        if path in (MISSING_ITEM, OUT_OF_STOCK):
            return ("RESHIP", "REFUND") if has_options else ("REFUND",)
        return ("EXCHANGE", "KEEP", "REFUND") if has_options else ("KEEP", "REFUND")

    @staticmethod
    def _preferred(choices) -> str:
        """Deterministic recommendation: EXCHANGE, then RESHIP, else the first allowed choice."""
        for action in ("EXCHANGE", "RESHIP"):
            if action in choices:
                return action
        return choices[0] if choices else "REFUND"

    def recommend(self, item: dict, classification) -> RecommendationResult:
        from ..services.customer_copy import customer_safe, fallback_recommendation_text

        categories = set(classification.categories)
        details = classification.details
        path = resolution_path(classification.categories, details, item["delivered"])
        rows = self._rows_for_path(path, item, categories, details)
        current = _size(item["size"])

        def sort_key(row):
            size = _size(row["size"])
            distance = abs(size - current) if size is not None and current is not None else float("inf")
            return (distance, row["sku"], row["color"], row["destination_id"])

        options = tuple(
            InventoryOption(
                option_id=f"{row['sku']}|{row['size']}|{row['color']}|{row['destination_id']}",
                sku=row["sku"],
                size=row["size"],
                color=row["color"],
                destination_id=row["destination_id"],
                available=row["available"],
            )
            for row in sorted(rows, key=sort_key)[:MAX_OPTIONS]
        )
        choices = self._choices(path, bool(options))
        preferred = self._preferred(choices)
        facts = {
            "shoe": {
                "sku": item["sku"],
                "model_id": item["model_id"],
                "size": item["size"],
                "color": item["color"],
                "delivered": bool(item["delivered"]),
            },
            "classified_categories": [category.value for category in classification.categories],
            "details": classification.details,
            "verified_inventory_options": [option.model_dump(mode="json") for option in options],
            "allowed_customer_choices": choices,
            "preferred_action": preferred,
            "resolution_path": path,
            "return_methods": RETURN_METHODS,
        }
        explanation = customer_safe(
            self.provider.compose_recommendation(facts),
            fallback_recommendation_text(preferred),
        )
        return RecommendationResult(
            options=options,
            choices=choices,
            explanation=explanation,
            provider_kind=self.provider.provider_kind,
            provider_label=self.provider.display_label,
            recommended_action=preferred,
            resolution_path=path,
        )
