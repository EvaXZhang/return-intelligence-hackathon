from __future__ import annotations

from ..domain.enums import DestinationType
from ..domain.models import RoutingDecision
from ..domain.routing_matrix import route_type
from ..providers.simulated import SimulatedAIProvider


class RoutingOptimizationAgent:
    name = "Seasonality & Routing Optimization Agent"
    weights = {"distance": 0.25, "transport_cost": 0.20, "capacity": 0.20, "inventory_fit": 0.15, "demand": 0.20}
    shipping_fee = 9.0
    dropoff_fee = 0.0

    def __init__(self, repo, provider=None):
        self.repo = repo
        self.provider = provider or SimulatedAIProvider()

    def _score(self, row):
        components = {
            "distance": max(0, 1 - min(row["distance_km"] / 100, 1)),
            "transport_cost": max(0, 1 - min(row["transport_cost_index"], 1)),
            "capacity": max(0, min((row["capacity_units"] - row["current_load_units"]) / row["capacity_units"], 1)),
            "inventory_fit": max(0, 1 - min(row["target_sku_units"] / 100, 1)),
            "demand": max(0, min(row["demand_index"], 1)),
        }
        total = round(sum(components[key] * self.weights[key] for key in components) * 100, 2)
        return total, {
            "components": components,
            "weights": self.weights,
            "source_values": {
                key: row[key]
                for key in (
                    "distance_km",
                    "transport_cost_index",
                    "capacity_units",
                    "current_load_units",
                    "target_sku_units",
                    "demand_index",
                )
            },
        }

    def _rank_destinations(self, destination_type: DestinationType, zone: str, *, dropoff: bool = False):
        ranked = []
        for row in self.repo.destinations(destination_type.value, zone, dropoff=dropoff):
            score, detail = self._score(row)
            ranked.append((score, row["destination_id"], detail, row["name"], row["address"], row["distance_km"]))
        ranked.sort(key=lambda value: (-value[0], value[1]))
        return ranked

    def route(self, condition, seasonality_flag, zone, fulfillment_mode="SHIP"):
        destination_type = route_type(condition, seasonality_flag)
        if destination_type == DestinationType.REJECT:
            return RoutingDecision(
                destination_type=destination_type,
                rationale="Worn/used shoes are rejected from normal return flow.",
                ai_explanation="The deterministic eligibility gate rejected normal routing before any AI optimization.",
            )
        if fulfillment_mode not in {"SHIP", "DROPOFF"}:
            raise ValueError("fulfillment mode must be SHIP or DROPOFF")

        final_candidates = self._rank_destinations(destination_type, zone)
        dropoff_candidates = self._rank_destinations(DestinationType.RETAIL_STORE, zone, dropoff=True)
        dropoff_candidates.sort(key=lambda value: (value[5], -value[0], value[1]))
        dropoff_cards = tuple(
            {
                "destination_id": value[1],
                "name": value[3],
                "address": value[4],
                "distance_km": value[5],
                "score": value[0],
                "score_components": value[2],
            }
            for value in dropoff_candidates
        )
        if not dropoff_candidates:
            return RoutingDecision(
                destination_type=destination_type,
                return_fee=self.dropoff_fee if fulfillment_mode == "DROPOFF" else self.shipping_fee,
                rationale="No eligible nearby customer return store is available; routing is blocked.",
                dropoff_candidates=dropoff_cards,
            )

        intake = dropoff_candidates[0]
        intake_location_id = intake[1]
        intake_location_name = intake[3]
        intake_location_address = intake[4]
        if destination_type == DestinationType.RETAIL_STORE and fulfillment_mode == "DROPOFF":
            selected = dropoff_candidates[0]
        else:
            selected = final_candidates[0] if final_candidates else None
        if not selected:
            return RoutingDecision(
                destination_type=destination_type,
                intake_location_id=intake_location_id,
                intake_location_name=intake_location_name,
                intake_location_address=intake_location_address,
                return_fee=self.dropoff_fee if fulfillment_mode == "DROPOFF" else self.shipping_fee,
                rationale="No active/open final destination with capacity; routing blocked.",
                dropoff_candidates=dropoff_cards,
            )

        return_fee = self.dropoff_fee if fulfillment_mode == "DROPOFF" else self.shipping_fee
        facts = {
            "condition_grade": str(condition),
            "seasonality_flag": seasonality_flag,
            "destination_type": destination_type.value,
            "selected_final_destination": selected[1],
            "customer_return_method": fulfillment_mode,
            "customer_return_store": {
                "id": intake_location_id,
                "name": intake_location_name,
                "address": intake_location_address,
            },
            "customer_return_fee": return_fee,
            "score": selected[0],
            "score_components": selected[2],
            "rule": "Destination type is locked by the mandatory condition × seasonality matrix.",
        }
        ai_explanation = self.provider.explain_route(facts)
        method_reason = (
            f"Customer drops off free at {intake_location_name}, {intake_location_address}."
            if fulfillment_mode == "DROPOFF"
            else f"Customer ships to {intake_location_name}, {intake_location_address}, using a $9 prepaid label."
        ) + " The destination is a system suggestion; staff confirm the final destination after intake."
        return RoutingDecision(
            destination_type=destination_type,
            destination_id=selected[1],
            intake_location_id=intake_location_id,
            intake_location_name=intake_location_name,
            intake_location_address=intake_location_address,
            return_fee=return_fee,
            score=selected[0],
            score_components=selected[2],
            dropoff_candidates=dropoff_cards,
            rationale=(
                "Deterministic score; condition × seasonality matrix cannot be overridden by AI. "
                + method_reason
            ),
            ai_explanation=ai_explanation,
        )
