"""Typed, audit-safe domain models for the ReMatch workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Stage(str, Enum):
    START = "start"
    ELIGIBILITY = "eligibility_checked"
    CONDITION_REVIEW = "condition_review_required"
    GRADED = "provisionally_graded"
    BUYERS = "buyers_ranked"
    PRICED = "offer_calculated"
    INSPECTION = "staff_inspection_required"
    READY = "approved_to_offer"
    OFFERED = "offer_sent"
    REPLANNING = "replanning_after_rejection"
    ACCEPTED = "buyer_accepted"
    ROUTED = "routed"
    FALLBACK = "outlet_liquidation_fallback"
    BLOCKED = "ineligible"


class ReturnItem(BaseModel):
    return_id: str
    order_id: str
    sku: str
    style: str
    size: str
    retail_price: float
    purchase_day: int
    return_day: int
    returnable: bool
    final_sale: bool
    policy_window_days: int


class ConditionObservation(BaseModel):
    grade: Grade
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    source: str
    preliminary: bool = True
    mismatch: bool = False


class BedrockGradeProposal(BaseModel):
    """Strict model-selected evidence; deterministic code still decides escalation."""

    grade: Grade
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1, max_length=5)


class Buyer(BaseModel):
    buyer_id: str
    sku: str
    style: str
    size: str
    max_wear_grade: Grade
    max_price: float
    store_id: str
    distance_km: float
    opted_in: bool
    demo_response: str
    rank_score: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)


class Store(BaseModel):
    store_id: str
    label: str


class Economics(BaseModel):
    retail_price: float
    resale_price: float
    cleaning_cost: float
    routing_cost: float
    total_cost: float
    net_recovery: float
    liquidation_recovery: float
    incremental_recovery: float
    recovery_multiple: float
    price_floor: float
    illustrative: bool = True
    shared_refund_cost_note: str


class Offer(BaseModel):
    buyer_id: str
    grade: Grade
    price: float
    status: str
    attempt: int
    reason: str


class Route(BaseModel):
    destination_id: str
    destination_label: str
    reason: str


class Approval(BaseModel):
    staff_grade: Grade
    grade_changed: bool
    approver_role: str = "Store associate"
    note: str = "Synthetic demo grade confirmation"


class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class AuditEvent(BaseModel):
    sequence: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool: str
    safe_input: dict[str, Any]
    safe_output: dict[str, Any]
    rationale: str
    confidence: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    guardrails: list[GuardrailCheck] = Field(default_factory=list)
    approval: dict[str, Any] | None = None


class ScenarioState(BaseModel):
    stage: Stage = Stage.START
    item: ReturnItem
    observation: ConditionObservation | None = None
    final_grade: Grade | None = None
    eligible: bool | None = None
    ranked_buyers: list[Buyer] = Field(default_factory=list)
    economics: Economics | None = None
    offers: list[Offer] = Field(default_factory=list)
    route: Route | None = None
    approval: Approval | None = None
    audit: list[AuditEvent] = Field(default_factory=list)
    guardrails: list[GuardrailCheck] = Field(default_factory=list)
    candidate_index: int = 0
    needs_human_review: bool = False
    scenario_variant: str = "standard"
    status_message: str = "Ready to evaluate a synthetic return."
    mode: str = "demo"
