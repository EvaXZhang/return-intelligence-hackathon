from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    conn=sqlite3.connect(str(path),timeout=5)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

@contextmanager
def transaction(path: Path | str, write: bool=False):
    conn=connect(path)
    try:
        if write: conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write: conn.commit()
    except Exception:
        if write: conn.rollback()
        raise
    finally: conn.close()
