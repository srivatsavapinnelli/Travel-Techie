"""
SQLite storage (standard library, no extra install).

One small file, `travel_techie.db`, next to main.py, holds users, login sessions,
bookings and saved plans, so everything survives a server restart.
Set TT_DB_PATH to use a different file (the tests do this).

A single shared connection guarded by a lock is plenty for this app's traffic and
keeps the code simple. For real production you'd move to PostgreSQL.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "travel_techie.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    pw_hash     TEXT NOT NULL,
    client_id   TEXT NOT NULL UNIQUE,   -- unguessable id the existing booking endpoints key on
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash  TEXT PRIMARY KEY,       -- sha256 of the token; the token itself is never stored
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings(
    booking_id  TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    vertical    TEXT NOT NULL,
    title       TEXT NOT NULL,
    subtitle    TEXT NOT NULL DEFAULT '',
    price       REAL NOT NULL DEFAULT 0,
    currency    TEXT NOT NULL DEFAULT 'INR',
    provider    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_client ON bookings(client_id, created_at);
CREATE TABLE IF NOT EXISTS plans(
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,          -- 'navigator' | 'ai_planner'
    title       TEXT NOT NULL,
    destination TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL,          -- JSON
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_user ON plans(user_id, created_at);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_path: str | None = None


def _db_path() -> str:
    return os.environ.get("TT_DB_PATH") or DEFAULT_PATH


def get_conn() -> sqlite3.Connection:
    """Open (once) and return the shared connection. Re-opens if TT_DB_PATH changed (tests)."""
    global _conn, _path
    path = _db_path()
    if _conn is None or path != _path:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        _path = path
    return _conn


@contextmanager
def tx():
    """Run a block of SQL as one transaction: committed on success, rolled back on error."""
    with _lock:
        conn = get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
