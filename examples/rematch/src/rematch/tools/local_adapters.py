"""Deterministic local implementations of the seven mock ALDO APIs."""

from __future__ import annotations

from copy import deepcopy

from ..audit import record_event
from ..config import Settings
from ..models import (
    Approval,
    Buyer,
    Grade,
    GuardrailCheck,
    Offer,
    Route,
    ScenarioState,
    Stage,
)
from ..pricing import calculate_unit_economics


_GRADE_ORDER = {Grade.A: 0, Grade.B: 1, Grade.C: 2}


class LocalToolAdapter:
    def __init__(self, settings: Settings, data: dict):
        self.settings = settings
        self.data = data

    def check_return(self, state: ScenarioState) -> None:
        item = state.item
        checks = [
            GuardrailCheck(name="order_and_sku_verified", passed=bool(item.order_id and item.sku), detail="Synthetic order and SKU match the selected return."),
            GuardrailCheck(name="within_return_window", passed=item.return_day - item.purchase_day <= item.policy_window_days, detail=f"Day {item.return_day - item.purchase_day} of {item.policy_window_days}."),
            GuardrailCheck(name="returnable_flag", passed=item.returnable, detail="Returnable flag must be true."),
            GuardrailCheck(name="not_final_sale", passed=not item.final_sale, detail="Final-sale items are excluded."),
        ]
        state.eligible = all(check.passed for check in checks)
        state.guardrails.extend(checks)
        state.stage = Stage.ELIGIBILITY if state.eligible else Stage.BLOCKED
        state.status_message = "Return is policy-eligible." if state.eligible else "Return is not eligible; agent stopped."
        record_event(
            state,
            tool="check_return",
            safe_input={"return_id": item.return_id, "sku": item.sku, "days_since_purchase": item.return_day - item.purchase_day},
            safe_output={"eligible": state.eligible, "policy_window_days": item.policy_window_days},
            rationale="Deterministic policy checks all passed." if state.eligible else "At least one deterministic policy check failed.",
            confidence=1.0,
            reason_codes=["POLICY_ELIGIBLE" if state.eligible else "POLICY_BLOCKED"],
            guardrails=checks,
        )

    def grade_condition(self, state: ScenarioState) -> None:
        scenario = self.data["scenarios"][state.scenario_variant]
        observation = deepcopy(self.data["observations"][scenario["observation"]])
        low_confidence = observation.confidence < self.settings.confidence_threshold
        mismatch = observation.mismatch
        review = low_confidence or mismatch
        state.observation = observation
        state.needs_human_review = review
        state.stage = Stage.CONDITION_REVIEW if review else Stage.GRADED
        state.status_message = (
            "Paused: low confidence or conflicting evidence requires staff review before matching."
            if review
            else "Preliminary B grade recorded; staff confirmation is still required."
        )
        checks = [
            GuardrailCheck(name="preliminary_only", passed=observation.preliminary, detail="AI/preset grade cannot finalize refund or listing condition."),
            GuardrailCheck(name="confidence_threshold", passed=not low_confidence, detail=f"{observation.confidence:.0%} confidence vs {self.settings.confidence_threshold:.0%} threshold."),
            GuardrailCheck(name="evidence_consistency", passed=not mismatch, detail="Photo evidence and return-desk observation must be consistent."),
        ]
        state.guardrails.extend(checks)
        reason_codes = ["PROVISIONAL_GRADE", "HUMAN_CONFIRMATION_REQUIRED"]
        if low_confidence:
            reason_codes.append("LOW_CONFIDENCE")
        if mismatch:
            reason_codes.append("EVIDENCE_MISMATCH")
        if review:
            reason_codes.append("HUMAN_REVIEW_REQUIRED")
        record_event(
            state,
            tool="grade_condition",
            safe_input={"return_id": state.item.return_id, "photo_provided": False},
            safe_output={"preliminary_grade": observation.grade.value, "evidence": observation.evidence, "human_review": review},
            rationale="Visible-wear evidence supports only a provisional grade; uncertainty pauses buyer matching for staff review.",
            confidence=observation.confidence,
            reason_codes=reason_codes,
            guardrails=checks,
        )

    def resolve_condition_review(self, state: ScenarioState) -> None:
        if state.stage != Stage.CONDITION_REVIEW or state.observation is None:
            raise ValueError("Condition review is only available at the uncertainty checkpoint")
        state.needs_human_review = False
        state.stage = Stage.GRADED
        state.status_message = "Staff reviewed the conflicting evidence; provisional B may proceed to governed matching."
        record_event(
            state,
            tool="approve_inspection",
            safe_input={"preliminary_grade": state.observation.grade.value, "review_trigger": "confidence_or_evidence_mismatch"},
            safe_output={"human_review_completed": True, "provisional_grade_retained": state.observation.grade.value},
            rationale="A staff member reviewed the uncertain evidence before buyer matching resumed; final grade approval remains a later checkpoint.",
            confidence=1.0,
            reason_codes=["HUMAN_REVIEW_COMPLETED", "UNCERTAINTY_RESOLVED"],
            approval={"approver_role": "Store associate", "note": "Synthetic uncertainty review"},
        )

    def find_buyers(self, state: ScenarioState) -> None:
        grade = state.final_grade or (state.observation.grade if state.observation else Grade.B)
        price_overrides = self.data["scenarios"][state.scenario_variant]["buyer_max_prices"]
        matched: list[Buyer] = []
        for original in self.data["buyers"]:
            buyer = original.model_copy(deep=True)
            if buyer.buyer_id in price_overrides:
                buyer.max_price = price_overrides[buyer.buyer_id]
            condition_ok = _GRADE_ORDER[grade] <= _GRADE_ORDER[buyer.max_wear_grade]
            if not (
                buyer.opted_in
                and buyer.sku == state.item.sku
                and buyer.style == state.item.style
                and buyer.size == state.item.size
                and condition_ok
            ):
                continue
            exact_grade_bonus = 20 if buyer.max_wear_grade == grade else 0
            buyer.rank_score = round(buyer.max_price - buyer.distance_km + exact_grade_bonus, 2)
            buyer.reason_codes = ["OPTED_IN", "SKU_STYLE_SIZE_MATCH", "WEAR_ACCEPTED", "PRICE_AND_PROXIMITY_RANK"]
            matched.append(buyer)
        matched.sort(key=lambda buyer: buyer.rank_score, reverse=True)
        state.ranked_buyers = matched
        state.candidate_index = 0
        fairness = GuardrailCheck(
            name="fair_matching",
            passed=True,
            detail="Ranking uses opt-in, SKU/style, size, accepted wear, willingness-to-pay, and distance only; no protected traits or profile proxies.",
        )
        state.guardrails.append(fairness)
        state.stage = Stage.BUYERS
        state.status_message = f"Ranked {len(matched)} eligible, opted-in buyers."
        record_event(
            state,
            tool="find_buyers",
            safe_input={"sku": state.item.sku, "style": state.item.style, "size": state.item.size, "grade": grade.value},
            safe_output={"ranked_buyers": [buyer.buyer_id for buyer in matched], "count": len(matched)},
            rationale="Candidates are ranked only on transaction and fulfillment fit.",
            confidence=1.0,
            reason_codes=["CONSENT_FILTERED", "OPERATIONAL_FACTORS_ONLY"],
            guardrails=[fairness],
        )

    def calculate_offer(self, state: ScenarioState) -> None:
        grade = state.final_grade or (state.observation.grade if state.observation else Grade.B)
        economics = calculate_unit_economics(state.item.retail_price, grade)
        profitable = economics.incremental_recovery >= self.settings.min_margin
        floor_check = GuardrailCheck(
            name="deterministic_price_floor",
            passed=economics.resale_price >= economics.price_floor,
            detail=f"Illustrative resale ${economics.resale_price:.0f} vs guarded floor ${economics.price_floor:.0f}.",
        )
        margin_check = GuardrailCheck(
            name="beats_liquidation",
            passed=profitable,
            detail=f"Incremental recovery ${economics.incremental_recovery:.0f} vs liquidation.",
        )
        state.economics = economics
        state.guardrails.extend([floor_check, margin_check])
        state.stage = Stage.PRICED if floor_check.passed and profitable else Stage.FALLBACK
        state.status_message = "Guarded offer economics calculated." if state.stage == Stage.PRICED else "No profitable path; route to outlet/liquidation."
        record_event(
            state,
            tool="calculate_offer",
            safe_input={"retail_price": state.item.retail_price, "grade": grade.value},
            safe_output=economics.model_dump(),
            rationale="Code—not the model—applies grade rates, handling costs, liquidation baseline, and the price floor.",
            confidence=1.0,
            reason_codes=["ILLUSTRATIVE_ASSUMPTIONS", "REFUND_COST_COMMON_TO_BOTH_PATHS"],
            guardrails=[floor_check, margin_check],
        )

    def approve_inspection(self, state: ScenarioState, grade: Grade) -> None:
        original_grade = state.observation.grade if state.observation else grade
        approval = Approval(
            staff_grade=grade,
            grade_changed=grade != original_grade,
        )
        state.approval = approval
        check = GuardrailCheck(
            name="staff_grade_confirmation",
            passed=True,
            detail=(
                f"Staff changed the preliminary grade from {original_grade.value} to {grade.value}."
                if approval.grade_changed
                else f"Staff confirmed the preliminary {grade.value} grade."
            ),
        )
        state.guardrails.append(check)
        record_event(
            state,
            tool="approve_inspection",
            safe_input={"preliminary_grade": original_grade.value, "staff_grade": grade.value},
            safe_output={"grade_changed": approval.grade_changed, "final_grade": grade.value},
            rationale="The AI grade is preliminary; store staff alone owns and records the final condition grade.",
            confidence=1.0,
            reason_codes=["STAFF_GRADE_CONFIRMED" if not approval.grade_changed else "STAFF_GRADE_CHANGED"],
            guardrails=[check],
            approval=approval.model_dump(mode="json"),
        )
        state.final_grade = grade
        state.needs_human_review = False
        if approval.grade_changed:
            self.find_buyers(state)
            self.calculate_offer(state)
            if state.stage == Stage.FALLBACK:
                return
        state.stage = Stage.READY
        state.status_message = f"Staff finalized grade {grade.value}; the agent may continue to the buyer offer."

    def send_offer(self, state: ScenarioState) -> None:
        economics = state.economics
        if economics is None or state.candidate_index >= len(state.ranked_buyers):
            state.stage = Stage.FALLBACK
            state.status_message = "No profitable opted-in buyer remains; use outlet/liquidation fallback."
            record_event(
                state,
                tool="send_offer",
                safe_input={"candidate_index": state.candidate_index},
                safe_output={"status": "fallback"},
                rationale="The safe fallback is used instead of pricing below the floor.",
                confidence=1.0,
                reason_codes=["NO_BUYER_ABOVE_FLOOR", "SAFE_FALLBACK"],
            )
            return
        buyer = state.ranked_buyers[state.candidate_index]
        price = round(min(economics.resale_price, buyer.max_price), 2)
        if price < economics.price_floor:
            state.candidate_index += 1
            state.stage = Stage.REPLANNING
            state.status_message = f"Skipped {buyer.buyer_id}: willingness-to-pay is below the guarded floor."
            record_event(
                state,
                tool="send_offer",
                safe_input={"buyer_id": buyer.buyer_id, "candidate_max_price": buyer.max_price},
                safe_output={"status": "skipped", "guarded_floor": economics.price_floor},
                rationale="The deterministic floor blocks an unprofitable offer; the agent must re-plan without lowering it.",
                confidence=1.0,
                reason_codes=["BUYER_BELOW_FLOOR", "REPLAN_REQUIRED"],
                guardrails=[GuardrailCheck(name="offer_above_floor", passed=False, detail=f"${price:.0f} willingness-to-pay vs ${economics.price_floor:.0f} floor.")],
            )
            return
        status = buyer.demo_response
        offer = Offer(
            buyer_id=buyer.buyer_id,
            grade=state.final_grade or state.observation.grade,
            price=price,
            status=status,
            attempt=len(state.offers) + 1,
            reason="Synthetic deterministic response for reliable presentation",
        )
        state.offers.append(offer)
        floor_check = GuardrailCheck(name="offer_above_floor", passed=price >= economics.price_floor, detail=f"${price:.0f} offer vs ${economics.price_floor:.0f} floor.")
        record_event(
            state,
            tool="send_offer",
            safe_input={"buyer_id": buyer.buyer_id, "price": price, "grade": offer.grade.value},
            safe_output={"status": status, "attempt": offer.attempt},
            rationale="Offer is sent only to an opted-in, condition-compatible buyer above the deterministic floor.",
            confidence=1.0,
            reason_codes=["BUYER_DECLINED_REPLAN" if status != "accepted" else "BUYER_ACCEPTED"],
            guardrails=[floor_check],
        )
        if status == "accepted":
            state.stage = Stage.ACCEPTED
            state.status_message = f"{buyer.buyer_id} accepted; routing can begin."
        else:
            state.candidate_index += 1
            state.stage = Stage.REPLANNING
            state.status_message = f"{buyer.buyer_id} declined/timed out; agent will re-plan to the next permissible buyer."

    def record_replan(self, state: ScenarioState) -> None:
        remaining = len(state.ranked_buyers) - state.candidate_index
        fallback = remaining <= 0
        record_event(
            state,
            tool="calculate_offer",
            safe_input={"trigger": "buyer_declined_timed_out_or_below_floor", "next_candidate_index": state.candidate_index},
            safe_output={"remaining_candidates": max(remaining, 0), "price_floor_unchanged": True, "fallback": fallback},
            rationale="The event changes buyer selection, not deterministic policy; the agent re-evaluates demand without lowering the floor.",
            confidence=1.0,
            reason_codes=["NO_BUYER_ABOVE_FLOOR", "SAFE_FALLBACK"] if fallback else ["DYNAMIC_REPLAN", "GUARDRAILS_RETAINED"],
        )
        state.stage = Stage.FALLBACK if fallback else Stage.READY
        state.status_message = "No buyer remains; safe fallback selected." if fallback else "Re-plan complete; next eligible buyer selected."

    def route_item(self, state: ScenarioState) -> None:
        accepted = next((offer for offer in reversed(state.offers) if offer.status == "accepted"), None)
        buyer = next((candidate for candidate in state.ranked_buyers if accepted and candidate.buyer_id == accepted.buyer_id), None)
        if buyer is None:
            state.stage = Stage.FALLBACK
            state.status_message = "No accepted buyer to route; use outlet/liquidation."
            return
        store = next(store for store in self.data["stores"] if store.store_id == buyer.store_id)
        state.route = Route(destination_id=store.store_id, destination_label=store.label, reason=f"Preferred pickup store for {buyer.buyer_id}; {buyer.distance_km:.1f} km fulfillment distance.")
        state.stage = Stage.ROUTED
        state.status_message = f"Complete: route to {store.label}."
        record_event(
            state,
            tool="route_item",
            safe_input={"accepted_buyer": buyer.buyer_id, "preferred_store": buyer.store_id},
            safe_output=state.route.model_dump(),
            rationale="Route to the accepted buyer's nearby preferred store to reduce handling and improve pickup convenience.",
            confidence=1.0,
            reason_codes=["NEAREST_SENSIBLE_STORE", "ROUTE_CONFIRMED"],
        )
