from __future__ import annotations

import hashlib
import json
import textwrap
import uuid
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ..db.connection import transaction
from ..db.repositories import canonical, now
from ..domain.models import ArtifactResult
from ..domain.policy import can_fulfill
from ..providers.simulated import SimulatedAIProvider


class FulfillmentLabelGenerationAgent:
    name = "Fulfillment & Label Generation Agent"

    def __init__(self, repo, artifact_root: Path, provider=None):
        self.repo = repo
        self.root = Path(artifact_root)
        self.provider = provider or SimulatedAIProvider()

    def generate(self, return_id: str) -> ArtifactResult:
        row = self.repo.get_return(return_id)
        route = self.repo.route(return_id)
        can_fulfill(row, bool(self.repo.open_review(return_id)), route)
        decision = self.repo.one(
            "SELECT decision,selected_option_json FROM decision_events WHERE return_id=? ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        )
        exchange = (
            json.loads(decision["selected_option_json"])
            if decision and decision["decision"] == "EXCHANGE" and decision["selected_option_json"]
            else None
        )
        from ..services.customer_copy import customer_safe, fallback_fulfillment_text

        raw_instructions = self.provider.compose_fulfillment_instructions(
            {
                "return_id": return_id,
                "customer_decision": row["current_decision"],
                "exchange_replacement": exchange,
                "fulfillment_mode": row["fulfillment_mode"],
                "return_fee": row["return_fee"],
                "customer_return_store": {
                    "id": row["dropoff_location_id"],
                    "name": row["return_store_name"],
                    "address": row["return_store_address"],
                },
                "demo_marking": "DEMO / NOT VALID FOR SHIPPING",
            }
        )
        # AI text is customer-facing: any internal destination wording falls back to a fixed template.
        instructions = customer_safe(
            raw_instructions,
            fallback_fulfillment_text(row["fulfillment_mode"], row["return_store_name"], row["return_store_address"]),
        )

        artifact_id = f"SYN-ART-{uuid.uuid4().hex[:12]}"
        folder = self.root / return_id
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder / f"{artifact_id}.pdf"
        qr_path = None
        try:
            canvas = Canvas(str(pdf), pagesize=LETTER, pageCompression=0)
            width, height = LETTER
            canvas.setFont("Helvetica-Bold", 26)
            canvas.drawCentredString(width / 2, height - 70, "DEMO / NOT VALID FOR SHIPPING")
            canvas.setFont("Helvetica", 12)
            lines = [
                f"Synthetic return: {return_id}",
                f"Customer return store: {row['return_store_name']}",
                f"Store address: {row['return_store_address']}",
            ]
            if row["fulfillment_mode"] == "DROPOFF":
                lines.append("Return method: Store drop-off — FREE (recommended)")
            else:
                lines.append("Return method: Ship to this store with prepaid label — $9")
                lines.append("Free alternative: drop off at this store.")
            lines.append("Mock logistics only — no carrier request was made.")
            if exchange:
                lines.extend(
                    [
                        "DEMO EXCHANGE RESERVATION",
                        f"Replacement: {exchange['sku']} · size {exchange['size']} · {exchange['color']}",
                        "Replacement releases after the original return is received in this demo.",
                    ]
                )
            for paragraph in textwrap.wrap(instructions, width=82):
                lines.append(paragraph.encode("latin-1", "replace").decode("latin-1"))
            y = height - 130
            for line in lines:
                canvas.drawString(60, y, line)
                y -= 22

            if row["fulfillment_mode"] == "DROPOFF":
                token = uuid.uuid4().hex
                qr_path = folder / f"{artifact_id}.png"
                qrcode.make(f"LOCAL-DEMO:{token}").save(qr_path)
                canvas.drawImage(str(qr_path), 60, max(70, y - 170), 150, 150)
                artifact_type = "DEMO_EXCHANGE_DROPOFF_CONFIRMATION" if exchange else "DEMO_DROPOFF_CONFIRMATION"
            else:
                artifact_type = "DEMO_EXCHANGE_RETURN_LABEL" if exchange else "DEMO_SHIPPING_LABEL"
            canvas.save()
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            result = ArtifactResult(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                local_path=str(pdf),
                sha256=digest,
                customer_instructions=instructions,
            )
            next_state = "AWAITING_ORIGINAL_RETURN" if exchange else "COMPLETED_RETURN"
            with transaction(self.repo.db_path, True) as connection:
                connection.execute(
                    "INSERT INTO fulfillment_artifacts VALUES(?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        return_id,
                        artifact_type,
                        str(pdf),
                        digest,
                        result.demo_marking,
                        instructions,
                        now(),
                    ),
                )
                self.repo.update_return(connection, return_id, row["version"], state=next_state)
                self.repo.activity(
                    connection,
                    return_id,
                    self.name,
                    "DEMO_ARTIFACT_GENERATED",
                    f"All deterministic gates passed; {self.provider.display_label} wrote customer instructions only.",
                    {"mode": row["fulfillment_mode"], "decision": row["current_decision"]},
                    {
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "marking": result.demo_marking,
                        "next_state": next_state,
                        "exchange_status": exchange.get("exchange_status") if exchange else None,
                        "instruction_provider": self.provider.provider_kind,
                    },
                )
            return result
        except Exception:
            pdf.unlink(missing_ok=True)
            if qr_path:
                qr_path.unlink(missing_ok=True)
            raise
