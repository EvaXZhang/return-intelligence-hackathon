"""Additive column migrations applied after schema.sql on every boot, seed and reset.

Existing CREATE TABLE statements are never edited; new nullable columns are added here so
legacy demo databases and freshly created ones converge through the same path.
"""
from __future__ import annotations

import sqlite3

# (table, column, SQL type). Every column is nullable so existing rows stay valid.
COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("return_requests", "staff_solution_json", "TEXT"),
    ("visual_assessments", "ai_confidence", "REAL"),
    ("visual_assessments", "confidence_source", "TEXT"),
    ("visual_assessments", "lifecycle_json", "TEXT"),
    ("review_queue", "ai_eligibility_state", "TEXT"),
    ("early_warning_alerts", "updated_at", "TEXT"),
    ("early_warning_alerts", "status_updated_at", "TEXT"),
    ("early_warning_alerts", "status_updated_by", "TEXT"),
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def apply_migrations(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Add any missing COLUMN_MIGRATIONS columns; return the (table, column) pairs added."""
    added: list[tuple[str, str]] = []
    for table, column, sql_type in COLUMN_MIGRATIONS:
        if column in _columns(conn, table):
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            added.append((table, column))
        except sqlite3.OperationalError as exc:
            # A concurrent Streamlit session may have added it between the check and the ALTER.
            if "duplicate column name" not in str(exc).lower():
                raise
    return added
