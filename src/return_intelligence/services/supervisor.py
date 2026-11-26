from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from ..agents.early_warning import EarlyWarningAgent
from ..agents.fulfillment import FulfillmentLabelGenerationAgent
from ..agents.reason import ReasonClassificationAgent
from ..agents.retention import RetentionRecommendationAgent
from ..agents.routing import RoutingOptimizationAgent
from ..agents.visual import VisualConditionAssessmentAgent
from ..config import DEFAULT_DEMO_CLOCK
from ..db.connection import transaction
from ..db.repositories import canonical, now
from ..domain.enums import Decision, DestinationType, EligibilityState, FulfillmentMode, Grade
from ..domain.errors import ConflictError, NotFoundError, PolicyViolation, ValidationError
from ..domain.policy import needs_review
from ..domain.resolution import NOT_RECEIVED_PATHS, SERVICE, legacy_resolution_path
from ..domain.routing_matrix import route_type
from ..providers.simulated import SimulatedAIProvider
from .artifact_store import LocalPhotoStore
from .customer_copy import compose_solution_email, recipient_for
from .seasonality import SeasonalityService

# Staff-only demo override of the photo-confidence gate, persisted in demo_settings so it spans browser tabs.
CONFIDENCE_OVERRIDE_KEY = "visual_confidence_override"
CONFIDENCE_OVERRIDE_MODES = ("AI", "FORCE_95", "FORCE_75")
OVERRIDE_GATE_VALUES = {"FORCE_95": 0.95, "FORCE_75": 0.75}
# Staff may set the final destination once a route exists; this never changes the customer flow.
DESTINATION_DECISION_STATES = ("ROUTED", "AWAITING_ORIGINAL_RETURN", "COMPLETED_RETURN", "COMPLETED_EXCHANGE")
FINAL_DESTINATION_TYPES = ("RETAIL_STORE", "OUTLET", "COMPANY_WAREHOUSE")
# Suspected-pattern alerts move strictly forward; CLOSED is terminal.
ALERT_STATUS_TRANSITIONS = {"OPEN": "INVESTIGATING", "INVESTIGATING": "CLOSED"}


class SupervisorService:
    name = "Supervisor"

    def __init__(self, repo, artifact_root, season=None, provider=None, upload_root=None, clock=None):
        self.repo = repo
        self.provider = provider or SimulatedAIProvider()
        # Business clock (callable -> aware datetime); defaults to the fixed demo clock for determinism.
        self.clock = clock or (lambda: datetime.fromisoformat(DEFAULT_DEMO_CLOCK))
        self.reason = ReasonClassificationAgent(self.provider)
        self.retention = RetentionRecommendationAgent(repo, self.provider)
        self.warning = EarlyWarningAgent(repo, self.provider, clock=self.clock)
        self.visual = VisualConditionAssessmentAgent(self.provider)
        self.routing = RoutingOptimizationAgent(repo, self.provider)
        self.fulfillment = FulfillmentLabelGenerationAgent(repo, artifact_root, self.provider)
        self.seasonality = SeasonalityService(season, self.clock)
        self.photo_store = LocalPhotoStore(upload_root or Path(artifact_root).parent / "uploads")

    @property
    def runtime_info(self) -> dict[str, object]:
        return {
            "provider_kind": self.provider.provider_kind,
            "provider_label": self.provider.display_label,
            "live_ai": self.provider.is_live,
        }

    def start_return(self, order_id: str, order_item_id: str | None = None, operation_id: str | None = None):
        if not order_id or len(order_id) > 64:
            raise ValidationError("valid synthetic order ID required")
        item = self.repo.get_order_item(order_id.strip(), order_item_id)
        return_id = f"SYN-R-{uuid.uuid4().hex[:12]}"
        row = self.repo.create_return(return_id, item["order_item_id"])
        with transaction(self.repo.db_path, True) as connection:
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "RETURN_STARTED",
                "Synthetic order and selected shoe item validated locally.",
                {"order_id": order_id, "order_item_id": item["order_item_id"]},
                {"return_id": return_id, "state": "DRAFT"},
            )
        return self.repo.get_return(return_id)

    def submit_reason(self, return_id, text, operation_id=None):
        row = self.repo.get_return(return_id)
        if row["state"] != "DRAFT":
            raise PolicyViolation("reason requires DRAFT state")
        classification = self.reason.classify(text)
        item = dict(row)
        item["similar_group"] = self.repo.one(
            "SELECT similar_group FROM products WHERE sku=?", (row["sku"],)
        )["similar_group"]
        recommendation = self.retention.recommend(item, classification)
        class_data = classification.model_dump(mode="json")
        recommendation_data = recommendation.model_dump(mode="json")
        digest = hashlib.sha256(text.encode()).hexdigest()
        message_id = f"SYN-MSG-{uuid.uuid4().hex[:12]}"
        recipient = recipient_for(row["order_id"])
        subject, body = compose_solution_email(return_id, row["order_id"], class_data, recommendation_data)
        staff_solution = self._staff_solution(class_data, recommendation_data, message_id)
        with transaction(self.repo.db_path, True) as connection:
            self.repo.update_return(
                connection,
                return_id,
                row["version"],
                state="OPTIONS_READY",
                raw_reason=text,
                classification_json=canonical(class_data),
                recommendation_json=canonical(recommendation_data),
                staff_solution_json=canonical(staff_solution),
            )
            connection.execute(
                """INSERT INTO customer_messages(message_id,return_id,message_type,channel,recipient,subject,body,status,sent_at)
                VALUES(?,?,'SOLUTION','EMAIL',?,?,?,'MOCK_SENT',?)""",
                (message_id, return_id, recipient, subject, body, now()),
            )
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "SPECIALISTS_COORDINATED",
                "Supervisor delegated reason classification and retention recommendation to their specialized agents.",
                {"workflow_stage": "reason_and_retention", "text_sha256": digest},
                {
                    "specialists": [self.reason.name, self.retention.name],
                    "provider": self.provider.provider_kind,
                },
            )
            self.repo.activity(
                connection,
                return_id,
                self.reason.name,
                "REASON_CLASSIFIED",
                f"{self.provider.display_label} produced structured multi-label output.",
                {"text_sha256": digest, "text_length": len(text)},
                {
                    "categories": [value.value for value in classification.categories],
                    "details": classification.details,
                    "provider": classification.provider_kind,
                },
            )
            self.repo.activity(
                connection,
                return_id,
                self.retention.name,
                "OPTIONS_PREPARED",
                "Deterministic inventory filtering constrained the AI customer explanation; refund/keep access remains available.",
                {"sku": row["sku"], "reason_categories": [value.value for value in classification.categories]},
                {
                    "options": len(recommendation.options),
                    "choices": recommendation.choices,
                    "recommended_action": recommendation.recommended_action,
                    "resolution_path": recommendation.resolution_path,
                    "provider": recommendation.provider_kind,
                },
            )
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "CUSTOMER_MESSAGE_MOCK_SENT",
                "Customer copy of the solution recorded as a simulated email; the staff copy was stored with the request.",
                {"message_type": "SOLUTION", "channel": "EMAIL"},
                {"message_id": message_id, "channel": "EMAIL", "status": "MOCK_SENT"},
            )
        return {
            "classification": class_data,
            "recommendation": recommendation_data,
            "request": self.repo.get_return(return_id),
        }

    @staticmethod
    def _staff_solution(classification: dict, recommendation: dict, message_id: str | None) -> dict:
        """Staff copy of the AI solution, kept with the request for analysis (never shown to customers)."""
        return {
            "categories": classification.get("categories", []),
            "detail_codes": classification.get("details", {}),
            "resolution_path": recommendation.get("resolution_path"),
            "recommended_action": recommendation.get("recommended_action"),
            "offered_options": recommendation.get("options", []),
            "allowed_choices": recommendation.get("choices", []),
            "customer_message_id": message_id,
            "customer_final_decision": None,
            "selected_option": None,
            "decided_at": None,
        }

    def _persist_complaint(self, connection, row, classification):
        event_id = f"SYN-E-{row['return_id']}"
        connection.execute(
            "INSERT OR IGNORE INTO complaint_events VALUES(?,?,?,?,?,?,?,?)",
            (
                event_id,
                row["return_id"],
                self.clock().isoformat(),
                row["sku"],
                row["model_id"],
                row["size"],
                row["color"],
                row["batch_id"],
            ),
        )
        details = classification.get("details", {})
        for category in classification["categories"]:
            value = category if isinstance(category, str) else category.value
            code = (
                details.get("size_direction")
                if value == "Wrong Size"
                else details.get("quality_symptom")
                if value == "Quality Issue"
                else details.get("fulfillment_issue")
                if value == "Missing Item/Wrong Item"
                else ""
            )
            connection.execute(
                "INSERT OR IGNORE INTO complaint_event_labels VALUES(?,?,?)",
                (event_id, value, code or ""),
            )

    def record_decision(self, return_id, decision: str, option_id: str | None = None, operation_id: str | None = None):
        row = self.repo.get_return(return_id)
        operation = operation_id or f"op-{uuid.uuid4().hex}"
        existing = self.repo.one("SELECT result_json FROM processed_operations WHERE operation_id=?", (operation,))
        if existing:
            return json.loads(existing["result_json"])
        if row["state"] != "OPTIONS_READY":
            raise PolicyViolation("decision requires OPTIONS_READY state")
        decision_value = Decision(decision)
        classification = json.loads(row["classification_json"])
        recommendation = json.loads(row["recommendation_json"])
        if decision_value.value not in recommendation.get("choices", ()):
            raise ValidationError("decision is not one of the offered choices")
        # Legacy rows without a stored path keep the pre-v2 rule.
        path = recommendation.get("resolution_path") or legacy_resolution_path(
            classification["categories"], row["delivered"]
        )
        selected = None
        if decision_value in (Decision.EXCHANGE, Decision.RESHIP):
            selected_match = next(
                (value for value in recommendation["options"] if value["option_id"] == option_id),
                None,
            )
            if not selected_match:
                if decision_value == Decision.EXCHANGE:
                    raise ValidationError("select an offered in-stock exchange option")
                raise ValidationError("select an offered in-stock item to ship")
            selected = dict(selected_match)
            available = self.repo.one(
                "SELECT on_hand-reserved available FROM inventory WHERE sku=? AND size=? AND color=? AND destination_id=?",
                (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
            )
            if not available or available["available"] <= 0:
                raise ConflictError("selected inventory is no longer available; refresh options")
            if decision_value == Decision.EXCHANGE:
                selected["exchange_status"] = "RESERVED_PENDING_ORIGINAL_RETURN"
                selected["reservation_type"] = "LOCAL_DEMO"
            else:
                selected["reship_status"] = "RESHIP_RELEASED_DEMO"
        service_resolution = None
        if decision_value == Decision.KEEP:
            state = "COMPLETED_KEEP"
        elif decision_value == Decision.RESHIP:
            state = "COMPLETED_SERVICE"
            service_resolution = {
                "resolution": "RESHIP",
                "resolution_path": path,
                "item": {"sku": selected["sku"], "size": selected["size"], "color": selected["color"]},
                "status": "RESHIP_RELEASED_DEMO",
                "photos_required": False,
            }
        elif path in NOT_RECEIVED_PATHS:
            state = "COMPLETED_SERVICE"
            service_resolution = {"resolution": "REFUND_NOT_RECEIVED", "resolution_path": path, "photos_required": False}
        elif path == SERVICE or decision_value == Decision.SERVICE_RESOLUTION:
            state = "COMPLETED_SERVICE"
            service_resolution = {"status": "synthetic service case recorded", "photos_required": False}
        else:
            state = "AWAITING_PHOTOS"
        result = {
            "return_id": return_id,
            "decision": decision_value.value,
            "state": state,
            "photos_required": state == "AWAITING_PHOTOS",
            "exchange": selected if decision_value == Decision.EXCHANGE else None,
            "reship": selected if decision_value == Decision.RESHIP else None,
            "resolution_path": path,
        }
        staff_solution = (
            json.loads(row["staff_solution_json"])
            if row.get("staff_solution_json")
            else self._staff_solution(classification, recommendation, None)
        )
        staff_solution.update(
            customer_final_decision=decision_value.value,
            selected_option=selected,
            decided_at=now(),
        )
        with transaction(self.repo.db_path, True) as connection:
            if decision_value == Decision.EXCHANGE and selected:
                reservation = connection.execute(
                    """UPDATE inventory SET reserved=reserved+1
                    WHERE sku=? AND size=? AND color=? AND destination_id=? AND on_hand-reserved>0""",
                    (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
                )
                if reservation.rowcount != 1:
                    raise ConflictError("exchange inventory changed before reservation; refresh options")
            if decision_value == Decision.RESHIP and selected:
                shipped = connection.execute(
                    """UPDATE inventory SET on_hand=on_hand-1
                    WHERE sku=? AND size=? AND color=? AND destination_id=? AND on_hand-reserved>0""",
                    (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
                )
                if shipped.rowcount != 1:
                    raise ConflictError("reship inventory changed before release; refresh options")
            self.repo.update_return(
                connection,
                return_id,
                row["version"],
                state=state,
                current_decision=decision_value.value,
                service_resolution_json=canonical(service_resolution) if service_resolution else None,
                staff_solution_json=canonical(staff_solution),
            )
            connection.execute(
                "INSERT INTO decision_events VALUES(?,?,?,?,?,?)",
                (f"SYN-D-{uuid.uuid4().hex[:12]}", return_id, decision_value.value, canonical(selected), now(), operation),
            )
            self._persist_complaint(connection, row, classification)
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "CUSTOMER_DECISION_RECORDED",
                "Customer choice persisted before independent early-warning analytics.",
                {"decision": decision_value.value, "option_id": option_id},
                {
                    "state": state,
                    "photos_required": result["photos_required"],
                    "exchange_status": selected.get("exchange_status") if selected else None,
                    "resolution_path": path,
                },
            )
            connection.execute(
                "INSERT INTO processed_operations VALUES(?,?,?,?,?)",
                (operation, return_id, "record_decision", canonical(result), now()),
            )
        try:
            self.warning.evaluate(return_id)
        except Exception as exc:
            with transaction(self.repo.db_path, True) as connection:
                self.repo.activity(
                    connection,
                    return_id,
                    self.warning.name,
                    "ANALYTICS_RETRY_NEEDED",
                    "Customer decision remains committed; independent analytics or its AI explanation can be retried.",
                    {},
                    {"status": "retry_needed", "error_type": type(exc).__name__},
                )
        return result

    def get_confidence_override(self) -> str:
        """Staff-only demo override of the photo-confidence gate ('AI' = use the AI value)."""
        value = self.repo.get_setting(CONFIDENCE_OVERRIDE_KEY, "AI")
        return value if value in CONFIDENCE_OVERRIDE_MODES else "AI"

    def set_confidence_override(self, mode: str, staff_id: str) -> str:
        if mode not in CONFIDENCE_OVERRIDE_MODES:
            raise ValidationError("confidence override must be AI, FORCE_95 or FORCE_75")
        staff = self._staff_id(staff_id)
        self.repo.set_setting(CONFIDENCE_OVERRIDE_KEY, mode, staff)
        return mode

    @staticmethod
    def _staff_id(staff_id) -> str:
        value = (staff_id or "").strip()
        if not 1 <= len(value) <= 64:
            raise ValidationError("staff ID must be 1-64 characters")
        return value

    def _release_exchange_reservation(self, connection, return_id):
        """Release a still-pending exchange reservation when the exchange cannot proceed; returns the updated option."""
        decision = connection.execute(
            "SELECT decision_id,selected_option_json FROM decision_events WHERE return_id=? AND decision='EXCHANGE' ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        ).fetchone()
        if not decision or not decision["selected_option_json"]:
            return None
        selected = json.loads(decision["selected_option_json"])
        if selected.get("exchange_status") != "RESERVED_PENDING_ORIGINAL_RETURN":
            return None
        connection.execute(
            """UPDATE inventory SET reserved=reserved-1
            WHERE sku=? AND size=? AND color=? AND destination_id=? AND reserved>0""",
            (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
        )
        selected["exchange_status"] = "RESERVATION_RELEASED_NOT_PROCEEDING"
        selected["released_at"] = now()
        connection.execute(
            "UPDATE decision_events SET selected_option_json=? WHERE decision_id=?",
            (canonical(selected), decision["decision_id"]),
        )
        return selected

    def _lifecycle(self, season_profile) -> dict:
        season = self.seasonality.evaluate(season_profile)
        return {
            "current_season": season.season,
            "season_source": season.source,
            "as_of": season.as_of,
            "product_season_profile": season.profile,
            "in_season": season.flag == 0,
            "seasonality_flag": season.flag,
            "reason": season.reason,
        }

    def submit_photos(
        self,
        return_id,
        fixture_key,
        angles=("front", "left", "right"),
        uploads: dict[str, bytes] | None = None,
    ):
        row = self.repo.get_return(return_id)
        if row["state"] not in ("AWAITING_PHOTOS", "RETAKE_REQUIRED"):
            raise PolicyViolation("photos are not accepted in this state")

        photo_records = []
        if uploads:
            photo_records = self.photo_store.save(return_id, uploads)
            angles = tuple(uploads)
        try:
            assessment = self.visual.assess(fixture_key, tuple(angles), images=uploads)
        except Exception:
            for record in photo_records:
                Path(record["local_path"]).unlink(missing_ok=True)
            raise

        assessment_id = f"SYN-VA-{uuid.uuid4().hex[:12]}"
        ai_confidence = assessment.confidence
        gate = None
        source = None
        lifecycle = None
        if not assessment.evidence_sufficient:
            # Retake: no gate, no source, whatever the staff override says.
            state = "RETAKE_REQUIRED"
            fields = {
                "condition_state": None,
                "preliminary_grade": None,
                "final_grade": None,
                "simulated_calibrated_confidence": None,
                "evidence_sufficient": 0,
            }
        else:
            override = self.get_confidence_override()
            if override in OVERRIDE_GATE_VALUES:
                gate, source = OVERRIDE_GATE_VALUES[override], "DEMO_OVERRIDE"
            else:
                gate, source = ai_confidence, "AI"
            eligibility = assessment.eligibility_state
            grade = assessment.preliminary_grade.value if assessment.preliminary_grade else None
            lifecycle = self._lifecycle(row["season_profile"])
            fields = {
                "condition_state": eligibility.value,
                "preliminary_grade": grade,
                "final_grade": None,
                "simulated_calibrated_confidence": gate,
                "evidence_sufficient": 1,
            }
            if needs_review(gate):
                # Below 0.85 (or missing/invalid confidence) goes to staff for every eligibility state, worn and defect included.
                state = "AWAITING_REVIEW"
            elif eligibility == EligibilityState.WORN_INELIGIBLE:
                state = "INELIGIBLE_CLOSED"
            elif eligibility == EligibilityState.SUSPECTED_DEFECT:
                state = "DEFECT_HOLD"
            else:
                state = "READY_TO_ROUTE"
                fields["final_grade"] = grade

        with transaction(self.repo.db_path, True) as connection:
            self.repo.update_return(connection, return_id, row["version"], state=state, **fields)
            released = self._release_exchange_reservation(connection, return_id) if state == "INELIGIBLE_CLOSED" else None
            for record in photo_records:
                connection.execute(
                    "INSERT INTO photo_submissions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"SYN-PHOTO-{uuid.uuid4().hex[:12]}",
                        return_id,
                        record["angle"],
                        record["local_path"],
                        record["media_type"],
                        record["bytes"],
                        record["width"],
                        record["height"],
                        record["sha256"],
                        fixture_key,
                        now(),
                    ),
                )
            connection.execute(
                """INSERT INTO visual_assessments(assessment_id,return_id,evidence_sufficient,eligibility_state,preliminary_grade,
                simulated_calibrated_confidence,ai_confidence,confidence_source,lifecycle_json,evidence_json,uncertainty_json,
                retakes_json,fixture_key,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    assessment_id,
                    return_id,
                    int(assessment.evidence_sufficient),
                    assessment.eligibility_state.value if assessment.eligibility_state else None,
                    assessment.preliminary_grade.value if assessment.preliminary_grade else None,
                    gate,
                    ai_confidence,
                    source,
                    canonical(lifecycle) if lifecycle else None,
                    canonical(assessment.evidence),
                    canonical(assessment.uncertainty),
                    canonical(assessment.retakes),
                    fixture_key,
                    now(),
                ),
            )
            if state == "AWAITING_REVIEW":
                connection.execute(
                    """INSERT INTO review_queue(review_id,return_id,assessment_id,status,preliminary_grade,resolution,final_grade,
                    reviewer_note,created_at,resolved_at,ai_eligibility_state) VALUES(?,?,?,'OPEN',?,NULL,NULL,NULL,?,NULL,?)""",
                    (
                        f"SYN-REV-{uuid.uuid4().hex[:12]}",
                        return_id,
                        assessment_id,
                        fields["preliminary_grade"],
                        now(),
                        fields["condition_state"],
                    ),
                )
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "VISUAL_SPECIALIST_COORDINATED",
                "Supervisor delegated image evidence to the Visual Condition Assessment Agent; deterministic policy applied its result.",
                {"angles": list(angles), "provider": self.provider.provider_kind},
                {"state": state, "specialist": self.visual.name},
            )
            self.repo.activity(
                connection,
                return_id,
                self.visual.name,
                "VISUAL_EVIDENCE_ASSESSED",
                (
                    f"{self.provider.display_label} assessed image evidence; deterministic policy applied the >=0.85 confidence gate "
                    "(below 0.85 or missing/invalid confidence goes to staff review)."
                ),
                {"fixture_key": fixture_key, "angles": list(angles)},
                {
                    "state": state,
                    "eligibility": fields["condition_state"],
                    "grade": fields["preliminary_grade"],
                    "gate_confidence": gate,
                    "ai_confidence": ai_confidence,
                    "confidence_source": source,
                    "lifecycle": lifecycle,
                    "retakes": assessment.retakes,
                    "provider": assessment.provider_kind,
                },
            )
            if released:
                self.repo.activity(
                    connection,
                    return_id,
                    self.name,
                    "EXCHANGE_RESERVATION_RELEASED",
                    "Worn shoes cannot be exchanged, so the reserved replacement was returned to available stock.",
                    {"state": state},
                    {"exchange_status": released["exchange_status"]},
                )
        return {"assessment": assessment.model_dump(mode="json"), "state": state}

    def resolve_review(self, return_id, resolution: str, note="", staff_id: str | None = None):
        row = self.repo.get_return(return_id)
        review = self.repo.open_review(return_id)
        if row["state"] != "AWAITING_REVIEW" or not review:
            raise PolicyViolation("open review required")
        if len(note) > 500:
            raise ValidationError("review note must be at most 500 characters")
        # Optional for older callers; the Staff Dashboard always passes the Staff controls ID.
        staff = self._staff_id(staff_id) if staff_id is not None else None
        if resolution == "APPROVE":
            # Confirms the AI eligibility; legacy reviews without one were eligible/unworn.
            condition = review.get("ai_eligibility_state") or EligibilityState.ELIGIBLE_UNWORN.value
            if condition == EligibilityState.WORN_INELIGIBLE.value:
                grade, state = None, "INELIGIBLE_CLOSED"
            elif condition == EligibilityState.SUSPECTED_DEFECT.value:
                grade, state = None, "DEFECT_HOLD"
            else:
                grade, state = review["preliminary_grade"], "READY_TO_ROUTE"
        elif resolution in ("OVERRIDE_A", "OVERRIDE_B", "OVERRIDE_C"):
            grade = resolution[-1]
            condition = "ELIGIBLE_UNWORN"
            state = "READY_TO_ROUTE"
        elif resolution == "WORN_INELIGIBLE":
            grade = None
            condition = resolution
            state = "INELIGIBLE_CLOSED"
        elif resolution == "SUSPECTED_DEFECT":
            grade = None
            condition = resolution
            state = "DEFECT_HOLD"
        else:
            raise ValidationError("invalid review resolution")
        with transaction(self.repo.db_path, True) as connection:
            self.repo.update_return(
                connection,
                return_id,
                row["version"],
                state=state,
                condition_state=condition,
                final_grade=grade,
                preliminary_grade=review["preliminary_grade"] if grade else None,
            )
            connection.execute(
                "UPDATE review_queue SET status='RESOLVED',resolution=?,final_grade=?,reviewer_note=?,resolved_at=? WHERE review_id=?",
                (resolution, grade, note.strip() or None, now(), review["review_id"]),
            )
            released = self._release_exchange_reservation(connection, return_id) if state == "INELIGIBLE_CLOSED" else None
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "STAFF_REVIEW_RESOLVED",
                "Authorized staff resolution persisted and routing gate recalculated.",
                {"resolution": resolution, "staff_id": staff, "note_present": bool(note), "note_length": len(note)},
                {
                    "state": state,
                    "condition_state": condition,
                    "final_grade": grade,
                    "exchange_status": released["exchange_status"] if released else None,
                },
            )
        return self.repo.get_return(return_id)

    def resolve_defect_hold(self, return_id, resolution: str, staff_id: str, grade: str | None = None, note: str = ""):
        """Staff resolve a suspected-defect hold. Confirmed defects are never routed or resold."""
        row = self.repo.get_return(return_id)
        if row["state"] != "DEFECT_HOLD":
            raise PolicyViolation("defect-hold resolution requires DEFECT_HOLD state")
        staff = self._staff_id(staff_id)
        note = note or ""
        if len(note) > 500:
            raise ValidationError("note must be at most 500 characters")
        if resolution not in ("NOT_DEFECT", "CONFIRMED_DEFECT"):
            raise ValidationError("resolution must be NOT_DEFECT or CONFIRMED_DEFECT")
        if resolution == "NOT_DEFECT" and grade not in ("A", "B", "C"):
            raise ValidationError("NOT_DEFECT requires a staff grade A, B or C")
        decided_at = now()
        with transaction(self.repo.db_path, True) as connection:
            if resolution == "NOT_DEFECT":
                state, outcome = "READY_TO_ROUTE", f"NOT_DEFECT_GRADE_{grade}"
                # Any exchange reservation is kept: the normal exchange flow continues.
                self.repo.update_return(
                    connection,
                    return_id,
                    row["version"],
                    state=state,
                    condition_state=EligibilityState.ELIGIBLE_UNWORN.value,
                    preliminary_grade=None,
                    final_grade=grade,
                )
            else:
                state = "DEFECT_RESOLVED"
                service_resolution = None
                if row["current_decision"] == "EXCHANGE":
                    decision = connection.execute(
                        "SELECT decision_id,selected_option_json FROM decision_events WHERE return_id=? AND decision='EXCHANGE' ORDER BY created_at DESC LIMIT 1",
                        (return_id,),
                    ).fetchone()
                    selected = json.loads(decision["selected_option_json"]) if decision and decision["selected_option_json"] else None
                    if selected and selected.get("exchange_status") == "RESERVED_PENDING_ORIGINAL_RETURN":
                        released = connection.execute(
                            """UPDATE inventory SET on_hand=on_hand-1,reserved=reserved-1
                            WHERE sku=? AND size=? AND color=? AND destination_id=? AND on_hand>0 AND reserved>0""",
                            (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
                        )
                        if released.rowcount != 1:
                            raise ConflictError("reserved replacement inventory is no longer available")
                        selected["exchange_status"] = "REPLACEMENT_RELEASED_DEMO"
                        selected["released_at"] = decided_at
                        connection.execute(
                            "UPDATE decision_events SET selected_option_json=? WHERE decision_id=?",
                            (canonical(selected), decision["decision_id"]),
                        )
                        service_resolution = {
                            "resolution": "CONFIRMED_DEFECT_REPLACEMENT",
                            "replacement": {"sku": selected["sku"], "size": selected["size"], "color": selected["color"]},
                            "decided_by": staff,
                            "decided_at": decided_at,
                            "resale": False,
                        }
                if service_resolution is None:
                    self._release_exchange_reservation(connection, return_id)
                    service_resolution = {
                        "resolution": "CONFIRMED_DEFECT_REFUND",
                        "decided_by": staff,
                        "decided_at": decided_at,
                        "resale": False,
                    }
                outcome = service_resolution["resolution"]
                # Condition stays SUSPECTED_DEFECT; no route is ever created for a confirmed defect.
                self.repo.update_return(
                    connection,
                    return_id,
                    row["version"],
                    state=state,
                    service_resolution_json=canonical(service_resolution),
                )
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "DEFECT_HOLD_RESOLVED",
                (
                    "Staff found no defect and set the grade; the normal return flow continues."
                    if resolution == "NOT_DEFECT"
                    else "Staff confirmed the defect; the request closes without routing or resale."
                ),
                {"resolution": resolution, "staff_id": staff, "note_present": bool(note.strip()), "note_length": len(note)},
                {"state": state, "outcome": outcome},
            )
        return self.repo.get_return(return_id)

    def select_fulfillment_mode(self, return_id, mode: str):
        row = self.repo.get_return(return_id)
        if row["state"] not in ("READY_TO_ROUTE", "ROUTING_BLOCKED"):
            raise PolicyViolation("mode selection requires a return ready to route")
        mode_value = FulfillmentMode(mode)
        with transaction(self.repo.db_path, True) as connection:
            self.repo.update_return(connection, return_id, row["version"], fulfillment_mode=mode_value.value)
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "FULFILLMENT_MODE_SELECTED",
                "Customer return method selected before deterministic route scoring.",
                {"mode": mode_value.value},
                {"state": row["state"]},
            )
        return self.repo.get_return(return_id)

    def route_return(self, return_id):
        row = self.repo.get_return(return_id)
        if row["state"] not in ("READY_TO_ROUTE", "ROUTING_BLOCKED"):
            raise PolicyViolation("routing requires READY_TO_ROUTE")
        if row["condition_state"] != "ELIGIBLE_UNWORN" or row["final_grade"] not in ("A", "B", "C"):
            raise PolicyViolation("eligible/unworn final A/B/C required")
        season = self.seasonality.evaluate(row["season_profile"])
        mode = row["fulfillment_mode"] or "SHIP"
        decision = self.routing.route(row["final_grade"], season.flag, row["customer_zone"], mode)
        state = "ROUTED" if decision.destination_id else "ROUTING_BLOCKED"
        combined_reason = decision.rationale
        if decision.ai_explanation:
            combined_reason += f" AI explanation: {decision.ai_explanation}"
        route_details = {
            **decision.score_components,
            "customer_return_method": mode,
            "return_fee": decision.return_fee,
            "customer_return_store_id": decision.intake_location_id,
            "customer_return_store_name": decision.intake_location_name,
            "customer_return_store_address": decision.intake_location_address,
        }
        with transaction(self.repo.db_path, True) as connection:
            self.repo.update_return(
                connection,
                return_id,
                row["version"],
                state=state,
                seasonality_flag=season.flag,
                destination_type=decision.destination_type.value,
                selected_destination_id=decision.destination_id,
                routing_reason=combined_reason,
                routing_score_json=canonical(route_details),
                fulfillment_mode=mode,
                dropoff_location_id=decision.intake_location_id,
                return_store_name=decision.intake_location_name,
                return_store_address=decision.intake_location_address,
                return_fee=decision.return_fee,
            )
            if decision.destination_id:
                connection.execute(
                    "INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"SYN-ROUTE-{uuid.uuid4().hex[:12]}",
                        return_id,
                        row["final_grade"],
                        row["final_grade"],
                        season.flag,
                        decision.destination_type.value,
                        decision.destination_id,
                        mode,
                        decision.score,
                        canonical(route_details),
                        combined_reason,
                        now(),
                    ),
                )
            self.repo.activity(
                connection,
                return_id,
                self.routing.name,
                "DETERMINISTIC_ROUTE_SELECTED",
                "Locked condition/seasonality matrix and transparent score selected the route; AI only explained the fixed result.",
                {"final_grade": row["final_grade"], "seasonality_flag": season.flag, "mode": mode},
                {
                    "state": state,
                    "destination_type": decision.destination_type.value,
                    "destination_id": decision.destination_id,
                    "customer_return_store_id": decision.intake_location_id,
                    "customer_return_store_name": decision.intake_location_name,
                    "customer_return_store_address": decision.intake_location_address,
                    "return_fee": decision.return_fee,
                    "score": decision.score,
                    "seasonality_reason": season.reason,
                    "ai_explanation": decision.ai_explanation,
                    "provider": self.provider.provider_kind,
                },
            )
        return {"decision": decision.model_dump(mode="json"), "seasonality": season.model_dump(mode="json"), "state": state}

    def available_fulfillment_modes(self, return_id) -> tuple[str, ...]:
        row = self.repo.get_return(return_id)
        if row["condition_state"] != "ELIGIBLE_UNWORN" or row["final_grade"] not in ("A", "B", "C"):
            raise PolicyViolation("eligible/unworn final A/B/C required before selecting a return method")
        dropoff_locations = self.repo.destinations(DestinationType.RETAIL_STORE.value, row["customer_zone"], dropoff=True)
        return ("SHIP", "DROPOFF") if dropoff_locations else ("SHIP",)

    def generate_artifact(self, return_id):
        return self.fulfillment.generate(return_id)

    def complete_exchange(self, return_id):
        row = self.repo.get_return(return_id)
        if row["state"] != "AWAITING_ORIGINAL_RETURN" or row["current_decision"] != "EXCHANGE":
            raise PolicyViolation("exchange completion requires a generated return artifact and the original-item return checkpoint")
        decision = self.repo.one(
            "SELECT decision_id,selected_option_json FROM decision_events WHERE return_id=? AND decision='EXCHANGE' ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        )
        if not decision or not decision["selected_option_json"]:
            raise PolicyViolation("exchange replacement reservation is missing")
        selected = json.loads(decision["selected_option_json"])
        with transaction(self.repo.db_path, True) as connection:
            released = connection.execute(
                """UPDATE inventory SET on_hand=on_hand-1,reserved=reserved-1
                WHERE sku=? AND size=? AND color=? AND destination_id=? AND on_hand>0 AND reserved>0""",
                (selected["sku"], selected["size"], selected["color"], selected["destination_id"]),
            )
            if released.rowcount != 1:
                raise ConflictError("reserved replacement inventory is no longer available")
            selected["exchange_status"] = "REPLACEMENT_RELEASED_DEMO"
            selected["released_at"] = now()
            connection.execute(
                "UPDATE decision_events SET selected_option_json=? WHERE decision_id=?",
                (canonical(selected), decision["decision_id"]),
            )
            self.repo.update_return(connection, return_id, row["version"], state="COMPLETED_EXCHANGE")
            self.repo.activity(
                connection,
                return_id,
                self.fulfillment.name,
                "EXCHANGE_REPLACEMENT_RELEASED",
                "The demo original-item receipt checkpoint was confirmed; the locally reserved replacement was released for simulated fulfillment.",
                {"original_return_received": True},
                {
                    "state": "COMPLETED_EXCHANGE",
                    "replacement": {
                        "sku": selected["sku"],
                        "size": selected["size"],
                        "color": selected["color"],
                        "status": selected["exchange_status"],
                    },
                },
            )
        return self.get_customer_view(return_id)

    def _require_destination_decidable(self, row, route):
        if not route or not route.get("destination_id"):
            raise PolicyViolation("a routed destination suggestion is required before staff decide")
        if row["condition_state"] != "ELIGIBLE_UNWORN" or row["final_grade"] not in ("A", "B", "C"):
            raise PolicyViolation("only eligible/unworn A/B/C returns get a final destination")
        if row["state"] not in DESTINATION_DECISION_STATES:
            raise PolicyViolation("final destination can be decided only after routing")

    def decide_destination(self, return_id, destination_id: str, staff_id: str, reason: str = ""):
        """Record the staff final-destination decision; the routed suggestion, state and customer flow are untouched."""
        row = self.repo.get_return(return_id)
        route = self.repo.route(return_id)
        self._require_destination_decidable(row, route)
        destination = self.repo.destination(destination_id) if destination_id else None
        if (
            not destination
            or destination["active"] != 1
            or destination["operational_status"] != "OPEN"
            or destination["destination_type"] not in FINAL_DESTINATION_TYPES
        ):
            raise ValidationError("choose an active, open store, outlet or company warehouse")
        staff = self._staff_id(staff_id)
        reason = (reason or "").strip()
        if len(reason) > 500:
            raise ValidationError("reason must be at most 500 characters")
        deviates = destination["destination_id"] != route["destination_id"]
        if deviates and not reason:
            raise ValidationError("a reason is required when the final destination differs from the suggestion")
        decision_id = f"SYN-SDD-{uuid.uuid4().hex[:12]}"
        with transaction(self.repo.db_path, True) as connection:
            connection.execute(
                """INSERT INTO staff_destination_decisions(decision_id,return_id,suggested_destination_id,suggested_destination_type,
                chosen_destination_id,chosen_destination_type,deviates_from_suggestion,reason,decided_by,decided_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    return_id,
                    route["destination_id"],
                    route["destination_type"],
                    destination["destination_id"],
                    destination["destination_type"],
                    int(deviates),
                    reason or None,
                    staff,
                    now(),
                ),
            )
            self.repo.activity(
                connection,
                return_id,
                self.name,
                "STAFF_DESTINATION_DECIDED",
                "Staff confirmed where the returned pair goes; the system suggestion is kept for comparison.",
                {
                    "suggested_destination_id": route["destination_id"],
                    "chosen_destination_id": destination["destination_id"],
                    "deviates": deviates,
                    "reason_present": bool(reason),
                    "reason_length": len(reason),
                },
                {
                    "final_destination_id": destination["destination_id"],
                    "final_destination_type": destination["destination_type"],
                },
            )
        return self.final_destination(return_id)

    def update_alert_status(self, alert_id: str, to_status: str, staff_id: str, note: str = ""):
        """Staff move a suspected-pattern alert strictly OPEN -> INVESTIGATING -> CLOSED, with an audit row per change."""
        alert = self.repo.alert(alert_id)
        if not alert:
            raise NotFoundError("early-warning alert not found")
        staff = self._staff_id(staff_id)
        note = (note or "").strip()
        if len(note) > 500:
            raise ValidationError("note must be at most 500 characters")
        from_status = alert["status"]
        if ALERT_STATUS_TRANSITIONS.get(from_status) != to_status:
            raise PolicyViolation(f"alert status cannot move from {from_status} to {to_status}")
        changed_at = now()
        with transaction(self.repo.db_path, True) as connection:
            updated = connection.execute(
                "UPDATE early_warning_alerts SET status=?,status_updated_at=?,status_updated_by=? WHERE alert_id=? AND status=?",
                (to_status, changed_at, staff, alert_id, from_status),
            )
            if updated.rowcount != 1:
                raise ConflictError("alert changed; reload and retry")
            connection.execute(
                """INSERT INTO alert_status_events(event_id,alert_id,from_status,to_status,changed_by,note,changed_at)
                VALUES(?,?,?,?,?,?,?)""",
                (f"SYN-ASE-{uuid.uuid4().hex[:12]}", alert_id, from_status, to_status, staff, note or None, changed_at),
            )
        return self.repo.alert(alert_id)

    def final_destination(self, return_id) -> dict:
        """Staff-only: the system suggestion plus the latest staff decision (latest row wins)."""
        row = self.repo.get_return(return_id)
        route = self.repo.route(return_id)
        suggested = None
        if route and route.get("destination_id"):
            destination = self.repo.destination(route["destination_id"])
            suggested = {
                "id": route["destination_id"],
                "name": destination["name"] if destination else None,
                "type": route["destination_type"],
                "score": route["total_score"],
            }
        decision = self.repo.latest_destination_decision(return_id)
        if decision:
            status = "STAFF_DECIDED"
        else:
            try:
                self._require_destination_decidable(row, route)
                status = "PENDING_STAFF_DECISION"
            except PolicyViolation:
                status = "NOT_APPLICABLE"
        return {"status": status, "suggested": suggested, "decision": decision}

    def get_customer_view(self, return_id, include_internal: bool = False):
        row = self.repo.get_return(return_id)
        row["classification"] = json.loads(row["classification_json"]) if row["classification_json"] else None
        row["recommendation"] = json.loads(row["recommendation_json"]) if row["recommendation_json"] else None
        internal_route = self.repo.route(return_id)
        row["route"] = internal_route if include_internal else None
        row["artifacts"] = self.repo.all("SELECT * FROM fulfillment_artifacts WHERE return_id=?", (return_id,))
        latest_decision = self.repo.one(
            "SELECT * FROM decision_events WHERE return_id=? ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        )
        row["exchange"] = (
            json.loads(latest_decision["selected_option_json"])
            if latest_decision and latest_decision["decision"] == "EXCHANGE" and latest_decision["selected_option_json"]
            else None
        )
        latest = self.repo.one(
            "SELECT * FROM visual_assessments WHERE return_id=? ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        )
        if latest:
            latest["evidence"] = json.loads(latest["evidence_json"])
            latest["uncertainty"] = json.loads(latest["uncertainty_json"])
            latest["retakes"] = json.loads(latest["retakes_json"])
            if include_internal:
                latest["lifecycle"] = json.loads(latest["lifecycle_json"]) if latest.get("lifecycle_json") else None
            else:
                # Lifecycle and every confidence value (AI, gate/override, source) are staff-only.
                latest["lifecycle_json"] = None
                latest["ai_confidence"] = None
                latest["confidence_source"] = None
                latest["simulated_calibrated_confidence"] = None
        row["latest_assessment"] = latest
        row["messages"] = self.repo.customer_messages(return_id)
        row["staff_solution"] = (
            json.loads(row["staff_solution_json"]) if include_internal and row.get("staff_solution_json") else None
        )
        if not include_internal:
            row["destination_type"] = None
            row["selected_destination_id"] = None
            row["routing_reason"] = None
            row["routing_score_json"] = None
            row["staff_solution_json"] = None
            row["seasonality_flag"] = None
            # The gate value would reveal an active Force 95%/75% staff override.
            row["simulated_calibrated_confidence"] = None
        return row

    def get_staff_view(self, return_id=None):
        if not return_id:
            return self.repo.dashboard()
        request = self.get_customer_view(return_id, include_internal=True)
        return {
            "request": request,
            "staff_solution": request["staff_solution"],
            "final_destination": self.final_destination(return_id),
            "reviews": self.repo.all("SELECT * FROM review_queue WHERE return_id=?", (return_id,)),
            "decisions": self.repo.all("SELECT * FROM decision_events WHERE return_id=?", (return_id,)),
            "activity": self.repo.activities(return_id),
        }
