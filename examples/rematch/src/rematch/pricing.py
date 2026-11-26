"""Deterministic unit economics and price-floor guardrails."""

from __future__ import annotations

from .models import Economics, Grade


def calculate_unit_economics(retail_price: float, grade: Grade | str) -> Economics:
    grade = Grade(grade)
    if grade == Grade.B:
        resale_rate, cleaning, routing = 0.85, 7.0, 5.0
    elif grade == Grade.C:
        resale_rate, cleaning, routing = 0.65, 10.0, 5.0
    else:
        resale_rate, cleaning, routing = 0.92, 5.0, 5.0

    liquidation = round(retail_price * 0.25, 2)
    resale = round(retail_price * resale_rate, 2)
    total_cost = cleaning + routing
    floor = round(max(retail_price * 0.55, liquidation + total_cost), 2)
    net = round(resale - total_cost, 2)
    incremental = round(net - liquidation, 2)
    multiple = round(net / liquidation, 2) if liquidation else 0.0
    return Economics(
        retail_price=retail_price,
        resale_price=resale,
        cleaning_cost=cleaning,
        routing_cost=routing,
        total_cost=total_cost,
        net_recovery=net,
        liquidation_recovery=liquidation,
        incremental_recovery=incremental,
        recovery_multiple=multiple,
        price_floor=floor,
        shared_refund_cost_note=(
            "Customer refund cost is common to resale and liquidation, so it is excluded "
            "from this differential recovery comparison."
        ),
    )
