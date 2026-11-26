"""Headless deterministic acceptance smoke; this is intentionally not a test suite."""

from rematch.config import Settings
from rematch.models import Grade, Stage
from rematch.orchestrator import DemoOrchestrator


def reach_inspection(orchestrator: DemoOrchestrator) -> None:
    orchestrator.run_until_checkpoint()
    state = orchestrator.state
    assert state.stage == Stage.INSPECTION
    assert state.eligible is True
    assert state.observation and state.observation.grade == Grade.B and state.observation.preliminary
    assert len(state.observation.evidence) >= 3
    assert state.observation.confidence == 0.88
    assert len(state.ranked_buyers) >= 3
    assert all(buyer.opted_in for buyer in state.ranked_buyers)


def run_b_path() -> DemoOrchestrator:
    orchestrator = DemoOrchestrator(Settings(mode="demo"))
    reach_inspection(orchestrator)
    economics = orchestrator.state.economics
    assert economics
    assert (economics.resale_price, economics.total_cost, economics.net_recovery) == (102.0, 12.0, 90.0)
    assert (economics.liquidation_recovery, economics.incremental_recovery, economics.recovery_multiple) == (30.0, 60.0, 3.0)
    orchestrator.approve(Grade.B)
    while not orchestrator.complete:
        orchestrator.step()
    state = orchestrator.state
    assert state.stage == Stage.ROUTED
    assert [offer.status for offer in state.offers[:2]] == ["declined", "accepted"]
    assert [offer.buyer_id for offer in state.offers[:2]] == ["Buyer Juniper", "Buyer Maple"]
    assert any("DYNAMIC_REPLAN" in event.reason_codes for event in state.audit)
    assert state.route and state.route.destination_id == "MTL-02"
    assert state.approval and state.approval.staff_grade == Grade.B
    return orchestrator


def run_c_path() -> DemoOrchestrator:
    orchestrator = DemoOrchestrator(Settings(mode="demo"))
    reach_inspection(orchestrator)
    before = [buyer.buyer_id for buyer in orchestrator.state.ranked_buyers]
    orchestrator.approve(Grade.C)
    state = orchestrator.state
    after = [buyer.buyer_id for buyer in state.ranked_buyers]
    assert state.final_grade == Grade.C
    assert state.approval and state.approval.grade_changed
    assert state.economics and state.economics.resale_price == 78.0
    assert before != after and after[0] == "Buyer Cedar"
    assert any("STAFF_GRADE_CHANGED" in event.reason_codes for event in state.audit)
    while not orchestrator.complete:
        orchestrator.step()
    assert orchestrator.state.stage == Stage.ROUTED
    assert orchestrator.state.offers[0].buyer_id == "Buyer Cedar"
    return orchestrator


def run_uncertainty_path() -> DemoOrchestrator:
    orchestrator = DemoOrchestrator(Settings(mode="demo"), scenario_variant="uncertain")
    orchestrator.run_until_checkpoint()
    state = orchestrator.state
    assert state.stage == Stage.CONDITION_REVIEW
    assert state.needs_human_review
    assert state.observation and state.observation.confidence == 0.61 and state.observation.mismatch
    assert not state.ranked_buyers
    grade_event = state.audit[-1]
    assert {"LOW_CONFIDENCE", "EVIDENCE_MISMATCH", "HUMAN_REVIEW_REQUIRED"}.issubset(grade_event.reason_codes)
    orchestrator.resolve_uncertainty()
    assert any("UNCERTAINTY_RESOLVED" in event.reason_codes for event in state.audit)
    orchestrator.run_until_checkpoint()
    assert state.stage == Stage.INSPECTION and len(state.ranked_buyers) >= 3
    return orchestrator


def run_fallback_path() -> DemoOrchestrator:
    orchestrator = DemoOrchestrator(Settings(mode="demo"), scenario_variant="fallback")
    reach_inspection(orchestrator)
    assert all(buyer.max_price < orchestrator.state.economics.price_floor for buyer in orchestrator.state.ranked_buyers)
    orchestrator.approve(Grade.B)
    while not orchestrator.complete:
        orchestrator.step()
    state = orchestrator.state
    assert state.stage == Stage.FALLBACK
    assert not state.offers
    reason_codes = {code for event in state.audit for code in event.reason_codes}
    assert {"BUYER_BELOW_FLOOR", "NO_BUYER_ABOVE_FLOOR", "SAFE_FALLBACK"}.issubset(reason_codes)
    return orchestrator


if __name__ == "__main__":
    b = run_b_path()
    c = run_c_path()
    uncertain = run_uncertainty_path()
    fallback = run_fallback_path()
    print(f"PASS demo B path: {len(b.state.audit)} audit events, decline -> re-plan -> acceptance -> route")
    print(f"PASS staff grade-change path: final grade C, ${c.state.economics.resale_price:.0f} re-price, re-match -> route")
    print("PASS uncertainty path: 61% + mismatch -> human checkpoint -> review -> matching")
    print(f"PASS fallback path: {len(fallback.state.ranked_buyers)} candidates below floor -> outlet/liquidation")
