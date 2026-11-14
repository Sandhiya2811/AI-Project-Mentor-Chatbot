from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from config import DB_PATH, STORAGE_DIR
from database.models import SCHEMA
from utils.helpers import now_iso


def connect() -> sqlite3.Connection:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    """One short-lived connection per operation -> safe to call from worker threads."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute("INSERT INTO users(name, created_at) VALUES('Student', ?)", (now_iso(),))
        conn.commit()
    finally:
        conn.close()
