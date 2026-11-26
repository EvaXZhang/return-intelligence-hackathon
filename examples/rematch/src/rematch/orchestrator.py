"""Single resumable orchestrator with deterministic and credential-gated AWS modes."""

from __future__ import annotations

import json
from typing import Any

from .audit import record_event
from .config import Settings
from .models import BedrockGradeProposal, ConditionObservation, Grade, GuardrailCheck, ScenarioState, Stage
from .synthetic_data import load_demo_data
from .tools import LocalToolAdapter


_TERMINAL = {Stage.ROUTED, Stage.FALLBACK, Stage.BLOCKED}
_CHECKPOINTS = {Stage.CONDITION_REVIEW, Stage.INSPECTION}
_VARIANTS = {"standard", "uncertain", "fallback"}


class DemoOrchestrator:
    mode = "demo"

    def __init__(self, settings: Settings, data: dict[str, Any] | None = None, scenario_variant: str = "standard"):
        self.settings = settings
        self.data = data or load_demo_data()
        self.tools = LocalToolAdapter(settings, self.data)
        self.scenario_variant = self._validate_variant(scenario_variant)
        self.state = self._new_state()

    def _validate_variant(self, scenario_variant: str) -> str:
        if scenario_variant not in _VARIANTS:
            raise ValueError(f"Unknown synthetic scenario: {scenario_variant}")
        return scenario_variant

    def _new_state(self) -> ScenarioState:
        return ScenarioState(item=self.data["returns"][0], mode=self.mode, scenario_variant=self.scenario_variant)

    def reset(self) -> ScenarioState:
        self.state = self._new_state()
        return self.state

    def set_scenario_variant(self, scenario_variant: str) -> ScenarioState:
        self.scenario_variant = self._validate_variant(scenario_variant)
        return self.reset()

    def step(self) -> ScenarioState:
        stage = self.state.stage
        if stage == Stage.START:
            self.tools.check_return(self.state)
        elif stage == Stage.ELIGIBILITY:
            self.tools.grade_condition(self.state)
        elif stage == Stage.GRADED:
            self.tools.find_buyers(self.state)
        elif stage == Stage.BUYERS:
            self.tools.calculate_offer(self.state)
        elif stage == Stage.PRICED:
            self.state.stage = Stage.INSPECTION
            self.state.status_message = "Paused: store staff must confirm or change the preliminary A/B/C grade."
        elif stage == Stage.READY:
            self.tools.send_offer(self.state)
        elif stage == Stage.REPLANNING:
            self.tools.record_replan(self.state)
        elif stage == Stage.ACCEPTED:
            self.tools.route_item(self.state)
        return self.state

    def run_until_checkpoint(self, max_steps: int = 20) -> ScenarioState:
        for _ in range(max_steps):
            if self.state.stage in _TERMINAL or self.state.stage in _CHECKPOINTS:
                break
            self.step()
        return self.state

    def resolve_uncertainty(self) -> ScenarioState:
        self.tools.resolve_condition_review(self.state)
        return self.state

    def approve(self, grade: Grade | str) -> ScenarioState:
        if self.state.stage != Stage.INSPECTION:
            raise ValueError("Grade confirmation is only available at the staff inspection checkpoint")
        self.tools.approve_inspection(self.state, Grade(grade))
        return self.state

    @property
    def complete(self) -> bool:
        return self.state.stage in _TERMINAL


class AwsStrandsOrchestrator(DemoOrchestrator):
    """Strands chooses registered tools; deterministic adapters validate and enforce them."""

    mode = "aws"

    def __init__(self, settings: Settings, data: dict[str, Any] | None = None):
        super().__init__(settings, data)
        self._agent = None
        self.uploaded_photo: bytes | None = None
        self.uploaded_photo_format = "jpeg"

    def _create_agent(self):
        error = self.settings.aws_readiness_error()
        if error:
            raise RuntimeError(error)
        try:
            from strands import Agent, tool
            from strands.hooks.events import AfterToolsEvent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError("Strands Agents SDK is not installed. Install pinned requirements or switch to Demo mode.") from exc

        object_schema = lambda properties, required: {  # noqa: E731
            "json": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
        }

        @tool(
            name="check_return",
            description="Check the selected synthetic return against deterministic policy.",
            inputSchema=object_schema({"return_id": {"type": "string"}}, ["return_id"]),
        )
        def check_return(return_id: str) -> dict[str, Any]:
            return self._execute_governed_action("check_return", return_id=return_id)

        @tool(
            name="grade_condition",
            description="Submit a preliminary visible-condition proposal; deterministic confidence rules decide escalation.",
            inputSchema=object_schema(
                {
                    "grade": {"type": "string", "enum": ["A", "B", "C"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                },
                ["grade", "confidence", "evidence"],
            ),
        )
        def grade_condition(grade: str, confidence: float, evidence: list[str]) -> dict[str, Any]:
            return self._execute_governed_action("grade_condition", grade=grade, confidence=confidence, evidence=evidence)

        @tool(
            name="find_buyers",
            description="Rank opted-in synthetic demand using deterministic product, condition, price, and proximity rules.",
            inputSchema=object_schema({"grade": {"type": "string", "enum": ["A", "B", "C"]}}, ["grade"]),
        )
        def find_buyers(grade: str) -> dict[str, Any]:
            return self._execute_governed_action("find_buyers", grade=grade)

        @tool(
            name="calculate_offer",
            description="Calculate or re-check guarded economics without changing deterministic floors.",
            inputSchema=object_schema({"grade": {"type": "string", "enum": ["A", "B", "C"]}}, ["grade"]),
        )
        def calculate_offer(grade: str) -> dict[str, Any]:
            return self._execute_governed_action("calculate_offer", grade=grade)

        @tool(
            name="send_offer",
            description="Send an offer only to the current permissible opted-in candidate and above the price floor.",
            inputSchema=object_schema({"buyer_id": {"type": "string"}}, ["buyer_id"]),
        )
        def send_offer(buyer_id: str) -> dict[str, Any]:
            return self._execute_governed_action("send_offer", buyer_id=buyer_id)

        @tool(
            name="approve_inspection",
            description="Human-only final condition grade; autonomous calls are rejected.",
            inputSchema=object_schema({"grade": {"type": "string", "enum": ["A", "B", "C"]}}, ["grade"]),
        )
        def approve_inspection(grade: str) -> dict[str, Any]:
            return self._execute_governed_action("approve_inspection", grade=grade)

        @tool(
            name="route_item",
            description="Route an accepted item to the buyer's deterministic nearby destination.",
            inputSchema=object_schema({"destination_id": {"type": "string"}}, ["destination_id"]),
        )
        def route_item(destination_id: str) -> dict[str, Any]:
            return self._execute_governed_action("route_item", destination_id=destination_id)

        class StopAfterGovernedTool:
            def register_hooks(self, registry) -> None:
                registry.add_callback(AfterToolsEvent, self.end_turn)

            @staticmethod
            def end_turn(event) -> None:
                event.end_turn = "Governed tool execution complete."

        model = BedrockModel(model_id=self.settings.bedrock_model_id, region_name=self.settings.aws_region)
        self._agent = Agent(
            model=model,
            tools=[check_return, grade_condition, find_buyers, calculate_offer, send_offer, approve_inspection, route_item],
            callback_handler=None,
            hooks=[StopAfterGovernedTool()],
            system_prompt=(
                "You are the ReMatch orchestrator. For each turn, call exactly one explicitly permitted registered tool. "
                "Never call approve_inspection: the final condition grade belongs to store staff only. Never invent buyers, waive checks, change prices, or call a tool that is not permitted for the current state. "
                "All calls are schema-validated and then checked against deterministic state permissions. Return only a concise reviewable summary; never reveal private chain-of-thought."
            ),
        )
        return self._agent

    def _expected_action(self) -> str | None:
        return {
            Stage.START: "check_return",
            Stage.ELIGIBILITY: "grade_condition",
            Stage.GRADED: "find_buyers",
            Stage.BUYERS: "calculate_offer",
            Stage.READY: "send_offer",
            Stage.REPLANNING: "calculate_offer",
            Stage.ACCEPTED: "route_item",
        }.get(self.state.stage)

    def _current_grade(self) -> Grade:
        return self.state.final_grade or (self.state.observation.grade if self.state.observation else Grade.B)

    def _execute_governed_action(self, action: str, **arguments: Any) -> dict[str, Any]:
        """Validate a model-selected action before any deterministic adapter executes."""
        expected = self._expected_action()
        if action != expected:
            raise ValueError(f"Action {action!r} is impermissible in state {self.state.stage.value}; only {expected!r} is allowed")

        if action == "check_return":
            if arguments["return_id"] != self.state.item.return_id:
                raise ValueError("Return ID does not match the selected synthetic return")
            self.tools.check_return(self.state)
        elif action == "grade_condition":
            proposal = BedrockGradeProposal.model_validate(arguments)
            observation = ConditionObservation(
                grade=proposal.grade,
                confidence=proposal.confidence,
                evidence=proposal.evidence,
                source="Amazon Bedrock multimodal proposal",
                preliminary=True,
            )
            low_confidence = observation.confidence < self.settings.confidence_threshold
            checks = [
                GuardrailCheck(name="preliminary_only", passed=True, detail="Bedrock cannot finalize refund or listing condition."),
                GuardrailCheck(name="confidence_threshold", passed=not low_confidence, detail=f"{observation.confidence:.0%} confidence vs {self.settings.confidence_threshold:.0%} threshold."),
                GuardrailCheck(name="evidence_consistency", passed=True, detail="No structured evidence mismatch was proposed."),
            ]
            self.state.observation = observation
            self.state.needs_human_review = low_confidence
            self.state.guardrails.extend(checks)
            self.state.stage = Stage.CONDITION_REVIEW if low_confidence else Stage.GRADED
            self.state.status_message = (
                "Paused: Bedrock confidence is below threshold; staff review is required before matching."
                if low_confidence
                else "Bedrock proposed a preliminary grade; staff confirmation is still required."
            )
            reason_codes = ["BEDROCK_PROVISIONAL_GRADE", "HUMAN_CONFIRMATION_REQUIRED"]
            if low_confidence:
                reason_codes.extend(["LOW_CONFIDENCE", "HUMAN_REVIEW_REQUIRED"])
            record_event(
                self.state,
                tool="grade_condition",
                safe_input={"return_id": self.state.item.return_id, "photo_provided": bool(self.uploaded_photo)},
                safe_output={"preliminary_grade": observation.grade.value, "evidence": observation.evidence, "human_review": low_confidence},
                rationale="Bedrock interpreted only allowlisted synthetic context and the optional uploaded photo; deterministic confidence rules control progression.",
                confidence=observation.confidence,
                reason_codes=reason_codes,
                guardrails=checks,
            )
        elif action == "find_buyers":
            if Grade(arguments["grade"]) != self._current_grade():
                raise ValueError("Proposed grade does not match the reviewed workflow grade")
            self.tools.find_buyers(self.state)
        elif action == "calculate_offer":
            if Grade(arguments["grade"]) != self._current_grade():
                raise ValueError("Proposed grade does not match the reviewed workflow grade")
            if self.state.stage == Stage.REPLANNING:
                self.tools.record_replan(self.state)
            else:
                self.tools.calculate_offer(self.state)
        elif action == "send_offer":
            if self.state.candidate_index >= len(self.state.ranked_buyers):
                expected_buyer = "fallback"
            else:
                expected_buyer = self.state.ranked_buyers[self.state.candidate_index].buyer_id
            if arguments["buyer_id"] != expected_buyer:
                raise ValueError("Proposed buyer is not the next deterministic eligible candidate")
            self.tools.send_offer(self.state)
        elif action == "route_item":
            accepted = next((offer for offer in reversed(self.state.offers) if offer.status == "accepted"), None)
            buyer = next((candidate for candidate in self.state.ranked_buyers if accepted and candidate.buyer_id == accepted.buyer_id), None)
            if buyer is None or arguments["destination_id"] != buyer.store_id:
                raise ValueError("Proposed route does not match the accepted buyer's governed destination")
            self.tools.route_item(self.state)
        else:
            raise ValueError("Final condition grading can only be submitted by store staff at the human checkpoint")

        return {
            "accepted": True,
            "new_state": self.state.stage.value,
            "status": self.state.status_message,
            "candidate_count": len(self.state.ranked_buyers),
        }

    def _agent_content(self, expected_action: str) -> list[dict[str, Any]]:
        context: dict[str, Any] = {
            "task": f"Call exactly the {expected_action} tool now.",
            "current_state": self.state.stage.value,
            "selected_return": {
                "return_id": self.state.item.return_id,
                "sku": self.state.item.sku,
                "style": self.state.item.style,
                "size": self.state.item.size,
                "retail_price": self.state.item.retail_price,
            },
            "current_grade": self._current_grade().value if self.state.observation else None,
        }
        if expected_action == "grade_condition":
            context["instruction"] = "Inspect visible wear only and call grade_condition with grade A/B/C, confidence 0..1, and 1..5 concise evidence strings."
        elif expected_action == "send_offer":
            context["permitted_buyer_id"] = (
                self.state.ranked_buyers[self.state.candidate_index].buyer_id
                if self.state.candidate_index < len(self.state.ranked_buyers)
                else "fallback"
            )
        elif expected_action == "route_item":
            accepted = next(offer for offer in reversed(self.state.offers) if offer.status == "accepted")
            buyer = next(candidate for candidate in self.state.ranked_buyers if candidate.buyer_id == accepted.buyer_id)
            context["permitted_destination_id"] = buyer.store_id
        content: list[dict[str, Any]] = [{"text": json.dumps(context)}]
        if expected_action == "grade_condition" and self.uploaded_photo:
            content.append({"image": {"format": self.uploaded_photo_format, "source": {"bytes": self.uploaded_photo}}})
        return content

    def step(self) -> ScenarioState:
        if self.state.stage == Stage.PRICED:
            return super().step()
        expected_action = self._expected_action()
        if expected_action is None:
            return self.state
        agent = self._agent or self._create_agent()
        previous_stage = self.state.stage
        previous_events = len(self.state.audit)
        try:
            agent(self._agent_content(expected_action))
        except Exception as exc:
            raise RuntimeError(f"Bedrock orchestration failed: {exc}. No guardrail was bypassed; switch to Demo mode to continue safely.") from exc
        if self.state.stage == previous_stage or len(self.state.audit) == previous_events:
            raise RuntimeError("Bedrock did not execute the required governed tool. No state changed; switch to Demo mode to continue safely.")
        return self.state


def create_orchestrator(settings: Settings | None = None) -> DemoOrchestrator:
    settings = settings or Settings.from_env()
    if settings.mode == "aws":
        return AwsStrandsOrchestrator(settings)
    return DemoOrchestrator(settings)
