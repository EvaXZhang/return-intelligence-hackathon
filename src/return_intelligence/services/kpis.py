"""Return-prevention KPIs (pure). RESHIP and SERVICE_RESOLUTION are not return-vs-keep choices, so they are excluded."""
from __future__ import annotations

DECIDED = ("EXCHANGE", "KEEP", "REFUND")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def compute_kpis(decision_counts: dict[str, int], mode_counts: dict[str, int]) -> dict:
    """decision_counts: current_decision -> requests; mode_counts: routes.fulfillment_mode -> routes.

    Rates are None when their denominator is 0 (the UI shows '—').
    """
    exchanges = int(decision_counts.get("EXCHANGE", 0))
    keeps = int(decision_counts.get("KEEP", 0))
    refunds = int(decision_counts.get("REFUND", 0))
    decided = exchanges + keeps + refunds
    routes = sum(int(value) for value in mode_counts.values())
    dropoffs = int(mode_counts.get("DROPOFF", 0))
    return {
        "exchanges": exchanges,
        "refunds": refunds,
        "keeps": keeps,
        "decided": decided,
        "routes": routes,
        "dropoff_routes": dropoffs,
        "exchange_rate": _ratio(exchanges, decided),
        "retention_rate": _ratio(exchanges + keeps, decided),
        "dropoff_share": _ratio(dropoffs, routes),
    }
