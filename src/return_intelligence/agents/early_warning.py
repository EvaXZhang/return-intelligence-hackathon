from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from ..config import DEFAULT_DEMO_CLOCK
from ..db.connection import transaction
from ..db.repositories import canonical, now
from ..domain.early_warning_rules import THRESHOLDS, evaluate_thresholds
from ..domain.models import AlertEvaluation
from ..providers.simulated import SimulatedAIProvider

SKU_SIZE = "SKU_SIZE"
MODEL = "MODEL"
ACTIVE_STATUSES = ("OPEN", "INVESTIGATING")
NOT_CONFIRMED = " Suspected pattern only—investigation is required; this is not a confirmed defect."
# Window filters: whole days from window_start through window_end (inclusive) on the business clock.
_IN_WINDOW = "julianday({col})>=julianday(?) AND julianday({col})<julianday(?,'+1 day')"
_SALES_OVERLAP = "date(s.period_end)>=date(?) AND date(s.period_start)<=date(?)"


class EarlyWarningAgent:
    name = "Early Warning & Product Issue Detection Agent"
    thresholds = THRESHOLDS

    def __init__(self, repo, provider=None, clock=None):
        self.repo = repo
        self.provider = provider or SimulatedAIProvider()
        # Business clock (callable -> aware datetime); sets the 90-day evaluation window.
        self.clock = clock or (lambda: datetime.fromisoformat(DEFAULT_DEMO_CLOCK))

    def window(self) -> tuple[str, str]:
        end = self.clock().astimezone(timezone.utc).date()
        start = end - timedelta(days=THRESHOLDS["window_days"])
        return start.isoformat(), end.isoformat()

    def evaluate(self, return_id: str) -> tuple[AlertEvaluation, ...]:
        row = self.repo.get_return(return_id)
        event = self.repo.one("SELECT * FROM complaint_events WHERE return_id=?", (return_id,))
        if not event:
            return ()
        product = self.repo.one("SELECT name,similar_group FROM products WHERE sku=?", (row["sku"],)) or {}
        labels = self.repo.all(
            "SELECT category,COALESCE(detail_code,'') detail FROM complaint_event_labels WHERE event_id=? ORDER BY category,detail",
            (event["event_id"],),
        )
        window = self.window()
        results = []
        # Every label of a multi-label request, at both levels.
        for label in labels:
            for level in (SKU_SIZE, MODEL):
                results.append(self._evaluate_level(return_id, row, product, label["category"], label["detail"], level, window))
        return tuple(results)

    def _group(self, row, product, level):
        """SQL filters (historical h / current e / sales s, each joined to products p) for a group and its baseline."""
        if level == SKU_SIZE:
            return {
                "dimension_value": f"{row['sku']}|{row['size']}",
                "group": ("h.sku=? AND h.size=?", "e.sku=? AND e.size=?", "s.sku=? AND s.size=?", (row["sku"], row["size"])),
                "baseline": ("h.sku=? AND h.size<>?", "e.sku=? AND e.size<>?", "s.sku=? AND s.size<>?", (row["sku"], row["size"])),
                "baseline_basis": "same SKU, other sizes",
                "fingerprint": f"{row['sku']}|{row['size']}",
            }
        group = product.get("similar_group")
        return {
            "dimension_value": row["model_id"],
            "group": ("p.model_id=?", "e.model_id=?", "p.model_id=?", (row["model_id"],)),
            "baseline": (
                "p.similar_group=? AND p.model_id<>?",
                "p.similar_group=? AND e.model_id<>?",
                "p.similar_group=? AND p.model_id<>?",
                (group, row["model_id"]),
            ),
            "baseline_basis": f"other models in similar group {group}",
            "fingerprint": f"MODEL|{row['model_id']}",
        }

    def _counts(self, filters, category, detail, window):
        historical_filter, current_filter, sales_filter, args = filters
        start, end = window
        label_args = (*args, category, detail, start, end)
        historical = self.repo.one(
            f"""SELECT count(*) n FROM historical_complaints h JOIN products p ON p.sku=h.sku
            WHERE {historical_filter} AND h.category=? AND COALESCE(h.detail_code,'')=? AND {_IN_WINDOW.format(col='h.occurred_at')}""",
            label_args,
        )["n"]
        current = self.repo.one(
            f"""SELECT count(*) n FROM complaint_events e JOIN complaint_event_labels l USING(event_id) JOIN products p ON p.sku=e.sku
            WHERE {current_filter} AND l.category=? AND COALESCE(l.detail_code,'')=? AND {_IN_WINDOW.format(col='e.occurred_at')}""",
            label_args,
        )["n"]
        sold = self.repo.one(
            f"""SELECT COALESCE(sum(s.units_sold),0) n FROM sales_volume s JOIN products p ON p.sku=s.sku
            WHERE {sales_filter} AND {_SALES_OVERLAP}""",
            (*args, start, end),
        )["n"]
        return historical, current, sold

    def _evaluate_level(self, return_id, row, product, category, detail, level, window):
        spec = self._group(row, product, level)
        historical, current, sold = self._counts(spec["group"], category, detail, window)
        base_historical, base_current, base_sold = self._counts(spec["baseline"], category, detail, window)
        count = historical + current
        base_count = base_historical + base_current
        rule = evaluate_thresholds(count, sold, base_count, base_sold)
        common = {
            "complaint_count": count,
            "units_sold": sold,
            "complaint_rate": rule["rate"],
            "baseline_rate": rule["baseline_rate"],
            "lift": rule["lift"],
            "level": level,
            "dimension_value": spec["dimension_value"],
            "category": category,
            "detail_code": detail,
            "baseline_available": rule["baseline_available"],
        }
        if not rule["alerted"]:
            return AlertEvaluation(alerted=False, **common)

        fingerprint = hashlib.sha256(f"{spec['fingerprint']}|{category}|{detail}".encode()).hexdigest()[:24]
        evidence = {
            "return_id": return_id,
            "sku": row["sku"],
            "size": row["size"] if level == SKU_SIZE else None,
            "model_id": row["model_id"],
            "product_name": product.get("name"),
            "similar_group": product.get("similar_group"),
            "level": level,
            "baseline_basis": spec["baseline_basis"],
            "baseline_available": rule["baseline_available"],
            "historical_count": historical,
            "current_count": current,
            "baseline_count": base_count,
            "baseline_units_sold": base_sold,
            "window": {"start": window[0], "end": window[1]},
        }
        # NOT NULL legacy columns: 0 stands for "no comparable baseline"; evidence_json carries the truth.
        stored_baseline = rule["baseline_rate"] or 0
        stored_lift = rule["lift"] or 0
        active = self.repo.one(
            f"SELECT * FROM early_warning_alerts WHERE fingerprint=? AND status IN({','.join('?' * len(ACTIVE_STATUSES))}) ORDER BY created_at DESC LIMIT 1",
            (fingerprint, *ACTIVE_STATUSES),
        )
        if active:
            # Same pattern still active: refresh the metrics, no new AI call.
            with transaction(self.repo.db_path, True) as connection:
                connection.execute(
                    """UPDATE early_warning_alerts SET complaint_count=?,units_sold=?,complaint_rate=?,baseline_rate=?,lift=?,
                    evidence_json=?,dimension_type=?,dimension_value=?,updated_at=? WHERE alert_id=?""",
                    (count, sold, rule["rate"], stored_baseline, stored_lift, canonical(evidence), level,
                     spec["dimension_value"], now(), active["alert_id"]),
                )
                self._log(connection, return_id, "PATTERN_UPDATED", common, active["alert_id"],
                          "Deterministic safeguards still crossed; the active suspected-pattern alert's metrics were refreshed.")
            return AlertEvaluation(alerted=True, recommendation=active["recommendation"], alert_id=active["alert_id"], **common)
        closed = self.repo.one(
            "SELECT alert_id,recommendation FROM early_warning_alerts WHERE fingerprint=? AND window_end=?",
            (fingerprint, window[1]),
        )
        if closed:
            # Closed by staff within this window: not re-raised.
            return AlertEvaluation(alerted=True, recommendation=closed["recommendation"], alert_id=closed["alert_id"], **common)

        facts = {
            **common,
            "sku": row["sku"],
            "model_id": row["model_id"],
            "size": row["size"] if level == SKU_SIZE else None,
            "baseline_basis": spec["baseline_basis"],
            "window": evidence["window"],
            "thresholds": self.thresholds,
        }
        explanation = self.provider.explain_alert(facts).strip()
        recommendation = f"{explanation}{NOT_CONFIRMED}"
        alert_id = f"SYN-ALERT-{fingerprint}-{window[1].replace('-', '')}"
        with transaction(self.repo.db_path, True) as connection:
            connection.execute(
                """INSERT INTO early_warning_alerts(alert_id,fingerprint,window_start,window_end,dimension_type,
                dimension_value,category,detail_code,complaint_count,units_sold,complaint_rate,baseline_rate,lift,
                threshold_json,evidence_json,recommendation,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
                (
                    alert_id,
                    fingerprint,
                    window[0],
                    window[1],
                    level,
                    spec["dimension_value"],
                    category,
                    detail,
                    count,
                    sold,
                    rule["rate"],
                    stored_baseline,
                    stored_lift,
                    canonical(self.thresholds),
                    canonical(evidence),
                    recommendation,
                    now(),
                    now(),
                ),
            )
            self._log(connection, return_id, "PATTERN_EVALUATED", common, alert_id,
                      f"Deterministic safeguards triggered; {self.provider.display_label} explained the suspected pattern.")
        return AlertEvaluation(
            alerted=True,
            recommendation=recommendation,
            provider_kind=self.provider.provider_kind,
            alert_id=alert_id,
            **common,
        )

    def _log(self, connection, return_id, action, metrics, alert_id, rationale):
        self.repo.activity(
            connection,
            return_id,
            self.name,
            action,
            rationale,
            {"level": metrics["level"], "dimension": metrics["dimension_value"], "category": metrics["category"]},
            {
                "alerted": True,
                "alert_id": alert_id,
                "count": metrics["complaint_count"],
                "units_sold": metrics["units_sold"],
                "rate": metrics["complaint_rate"],
                "lift": metrics["lift"],
                "baseline_available": metrics["baseline_available"],
                "explanation_provider": self.provider.provider_kind if action == "PATTERN_EVALUATED" else "none",
            },
        )
