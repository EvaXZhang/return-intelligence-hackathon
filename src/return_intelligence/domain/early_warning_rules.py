"""Deterministic early-warning threshold rule shared by the agent and the local Lambda-style handler."""
from __future__ import annotations

THRESHOLDS = {
    "minimum_complaints": 5,
    "minimum_units_sold": 20,
    "minimum_rate": 0.15,
    "minimum_lift": 2.0,
    "window_days": 90,
    "version": "v2",
}


def evaluate_rates(count: int, sold: int, baseline_rate: float | None) -> dict:
    """Apply the rule to a group's count/sales and a baseline rate (None or <= 0 means no comparable baseline)."""
    rate = count / sold if sold else 0
    baseline_available = baseline_rate is not None and baseline_rate > 0
    lift = rate / baseline_rate if baseline_available else None
    alerted = (
        count >= THRESHOLDS["minimum_complaints"]
        and sold >= THRESHOLDS["minimum_units_sold"]
        and rate >= THRESHOLDS["minimum_rate"]
        and (lift is None or lift >= THRESHOLDS["minimum_lift"])
    )
    return {
        "alerted": alerted,
        "rate": rate,
        "baseline_rate": baseline_rate if baseline_available else None,
        "lift": lift,
        "baseline_available": baseline_available,
    }


def evaluate_thresholds(count: int, sold: int, baseline_count: int, baseline_sold: int) -> dict:
    """Without a comparable baseline the group still alerts on minimum count, units sold and rate."""
    baseline_available = baseline_sold > 0 and baseline_count > 0
    baseline_rate = baseline_count / baseline_sold if baseline_available else None
    return evaluate_rates(count, sold, baseline_rate)
