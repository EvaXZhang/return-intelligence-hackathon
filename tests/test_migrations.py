import sqlite3
from pathlib import Path

import pytest

from return_intelligence.db import migrations
from return_intelligence.db.migrations import COLUMN_MIGRATIONS, apply_migrations
from return_intelligence.db.repositories import Repository
from return_intelligence.db.seed import reset_database, seed_database
from return_intelligence.services.supervisor import SupervisorService
from tests.conftest import advance_to_photos

LEGACY_SCHEMA = Path(__file__).parent / "fixtures" / "legacy_schema_v1.sql"
V2_TABLES = ("customer_messages", "staff_destination_decisions", "alert_status_events", "demo_settings")
V2_INDEXES = ("idx_customer_messages_return", "idx_staff_destination_return", "idx_alert_status_events")
STAMP = "2026-01-10T12:00:00+00:00"


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _assert_v2_shape(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        for table, column, _ in COLUMN_MIGRATIONS:
            assert column in _columns(conn, table), f"{table}.{column} missing"
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
        assert set(V2_TABLES) <= names
        assert set(V2_INDEXES) <= names
    finally:
        conn.close()


@pytest.fixture
def legacy_db(tmp_path):
    """A DB created from the frozen v1 schema with one legacy request and one legacy alert."""
    db = tmp_path / "data" / "legacy.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(LEGACY_SCHEMA.read_text())
        conn.execute("INSERT INTO products VALUES('SYN-RUNNER-100','SYN-MODEL-RUNNER','Everyday Runner','SHOES','YEAR_ROUND','RUNNER',1)")
        conn.execute("INSERT INTO batches VALUES('SYN-B-SYN-RUNNER-100','SYN-RUNNER-100','2025-10-01',1)")
        conn.execute("INSERT INTO orders VALUES('SYN-O-SIZE-001','2025-12-15','DELIVERED','SYN-ZONE-1',1)")
        conn.execute("INSERT INTO order_items VALUES('SYN-OI-001','SYN-O-SIZE-001','SYN-RUNNER-100','SYN-B-SYN-RUNNER-100','8','Blue',1,1,1)")
        conn.execute(
            "INSERT INTO return_requests(return_id,order_item_id,state,raw_reason,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("SYN-R-LEGACY", "SYN-OI-001", "DRAFT", "legacy reason", STAMP, STAMP),
        )
        # Positional insert exactly as v1 wrote alerts (18 columns).
        conn.execute(
            "INSERT INTO early_warning_alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("SYN-ALERT-LEGACY", "fp-legacy", "2025-10-17", "2026-01-15", "MODEL_SIZE", "SYN-MODEL-RUNNER|8", "Wrong Size",
             "too_small", 5, 25, 0.2, 0.01, 20.0, "{}", "{}", "Suspected pattern only.", "OPEN", STAMP),
        )
        conn.commit()
        assert "staff_solution_json" not in _columns(conn, "return_requests")
    finally:
        conn.close()
    return db


def test_seed_migrates_legacy_db_and_legacy_rows_still_read(legacy_db, tmp_path):
    seed_database(legacy_db, tmp_path)
    _assert_v2_shape(legacy_db)
    repo = Repository(legacy_db)
    legacy = repo.get_return("SYN-R-LEGACY")
    assert legacy["state"] == "DRAFT" and legacy["raw_reason"] == "legacy reason"
    assert legacy["staff_solution_json"] is None
    alert = repo.one("SELECT * FROM early_warning_alerts WHERE alert_id='SYN-ALERT-LEGACY'")
    assert alert["complaint_count"] == 5 and alert["updated_at"] is None and alert["status_updated_by"] is None


def test_full_refund_flow_on_migrated_db(legacy_db, tmp_path):
    seed_database(legacy_db, tmp_path)
    repo = Repository(legacy_db)
    service = SupervisorService(repo, tmp_path / "artifacts")
    rid = advance_to_photos(service, "SYN-O-A95-001", "wrong color", "REFUND")
    assert service.submit_photos(rid, "eligible_a_95")["state"] == "READY_TO_ROUTE"
    service.select_fulfillment_mode(rid, "SHIP")
    assert service.route_return(rid)["state"] == "ROUTED"
    artifact = service.generate_artifact(rid)
    assert Path(artifact.local_path).exists()
    assert service.get_customer_view(rid)["state"] == "COMPLETED_RETURN"
    assessment = repo.one("SELECT * FROM visual_assessments WHERE return_id=?", (rid,))
    assert assessment["simulated_calibrated_confidence"] == 0.95 and assessment["ai_confidence"] == 0.95
    assert assessment["confidence_source"] == "AI"


def test_initialize_is_idempotent(legacy_db):
    repo = Repository(legacy_db)
    repo.initialize()
    repo.initialize()
    _assert_v2_shape(legacy_db)
    conn = sqlite3.connect(str(legacy_db))
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(visual_assessments)")]
        assert len(columns) == len(set(columns))
    finally:
        conn.close()


def test_reset_database_produces_v2_shape(tmp_path):
    db = tmp_path / "data" / "reset.db"
    seed_database(db, tmp_path)
    reset_database(db, tmp_path, True)
    _assert_v2_shape(db)


def test_apply_migrations_rerun_and_duplicate_race_are_safe(legacy_db, tmp_path, monkeypatch):
    seed_database(legacy_db, tmp_path)
    conn = sqlite3.connect(str(legacy_db))
    try:
        assert apply_migrations(conn) == []
        # Simulate a concurrent session adding the columns between the check and the ALTER.
        monkeypatch.setattr(migrations, "_columns", lambda *_: set())
        assert apply_migrations(conn) == []
    finally:
        conn.close()


def test_demo_settings_round_trip(repo):
    assert repo.get_setting("visual_confidence_override") is None
    assert repo.get_setting("visual_confidence_override", "AI") == "AI"
    repo.set_setting("visual_confidence_override", "0.95", "staff-demo")
    repo.set_setting("visual_confidence_override", "0.75", "staff-demo")
    assert repo.get_setting("visual_confidence_override") == "0.75"
    row = repo.one("SELECT * FROM demo_settings WHERE setting_key='visual_confidence_override'")
    assert row["updated_by"] == "staff-demo" and row["updated_at"]
