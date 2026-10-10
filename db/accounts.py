"""
Accounts: sign up, log in, sessions and saved plans.

Security basics implemented here (it is a student project, but these are the right habits):
  - passwords are never stored: PBKDF2-HMAC-SHA256 with a random salt per user
  - session tokens are random (secrets) and only their SHA-256 hash is stored
  - password checks use constant-time comparison; unknown emails cost the same time as wrong passwords
  - repeated failed logins for one email are temporarily locked
Not included (would be needed for real production): email verification, password reset,
HTTPS-only cookies, per-IP rate limiting, CSRF protection.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from db.database import tx

PBKDF2_ITERATIONS = 240_000
SESSION_DAYS = 30
MAX_PLANS_PER_USER = 100
MAX_PLAN_BYTES = 200_000
PLAN_KINDS = {"navigator", "ai_planner"}

LOCK_AFTER_FAILURES = 5
LOCK_SECONDS = 60
_failures: dict[str, tuple[int, float]] = {}   # email -> (failed count, locked_until epoch)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTaken(Exception):
    pass


class BadCredentials(Exception):
    pass


class LockedOut(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"Too many attempts. Try again in {seconds} seconds.")
        self.seconds = seconds


class PlanLimit(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_signup(name: str, email: str, password: str) -> str | None:
    """Return a human-readable problem, or None if everything is fine."""
    if not (name or "").strip():
        return "Please enter your name."
    if len(name.strip()) > 60:
        return "Name is too long (60 characters max)."
    email = normalize_email(email)
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if len(password or "") < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password is too long (128 characters max)."
    return None


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except Exception:
        return False


_DUMMY_HASH = hash_password("not-a-real-password")  # used to keep timing equal for unknown emails


# ---------------------------------------------------------------------------
# Users and sessions
# ---------------------------------------------------------------------------
def _public(row) -> dict:
    return {"name": row["name"], "email": row["email"], "client_id": row["client_id"], "created_at": row["created_at"]}


def create_user(name: str, email: str, password: str) -> dict:
    email = normalize_email(email)
    with tx() as db:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise EmailTaken()
        cur = db.execute(
            "INSERT INTO users(name, email, pw_hash, client_id, created_at) VALUES (?,?,?,?,?)",
            (name.strip(), email, hash_password(password), uuid.uuid4().hex, _now().isoformat()),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"id": row["id"], **_public(row)}


def authenticate(email: str, password: str) -> dict:
    email = normalize_email(email)
    fails, locked_until = _failures.get(email, (0, 0.0))
    if locked_until > time.time():
        raise LockedOut(int(locked_until - time.time()) + 1)

    with tx() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    ok = verify_password(password, row["pw_hash"] if row else _DUMMY_HASH)
    if not row or not ok:
        fails += 1
        if fails >= LOCK_AFTER_FAILURES:
            _failures[email] = (0, time.time() + LOCK_SECONDS)   # lock, and start counting afresh afterwards
        else:
            _failures[email] = (fails, 0.0)
        raise BadCredentials()
    _failures.pop(email, None)
    return {"id": row["id"], **_public(row)}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with tx() as db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))   # tidy up expired ones
        db.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (_hash_token(token), user_id, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
        )
    return token


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    with tx() as db:
        row = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (_hash_token(token), _now().isoformat()),
        ).fetchone()
    return {"id": row["id"], **_public(row)} if row else None


def delete_session(token: str) -> None:
    with tx() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


# ---------------------------------------------------------------------------
# Saved plans
# ---------------------------------------------------------------------------
def save_plan(user_id: int, kind: str, title: str, destination: str, payload: dict) -> dict:
    blob = json.dumps(payload, separators=(",", ":"))
    if len(blob.encode("utf-8")) > MAX_PLAN_BYTES:
        raise ValueError("This plan is too large to save.")
    if kind not in PLAN_KINDS:
        raise ValueError("Unknown plan type.")
    plan_id = uuid.uuid4().hex
    created = _now().isoformat()
    with tx() as db:
        count = db.execute("SELECT COUNT(*) FROM plans WHERE user_id = ?", (user_id,)).fetchone()[0]
        if count >= MAX_PLANS_PER_USER:
            raise PlanLimit()
        db.execute(
            "INSERT INTO plans(id, user_id, kind, title, destination, payload, created_at) VALUES (?,?,?,?,?,?,?)",
            (plan_id, user_id, kind, title.strip()[:120] or "Untitled plan", destination.strip()[:80], blob, created),
        )
    return {"id": plan_id, "kind": kind, "title": title.strip()[:120] or "Untitled plan", "destination": destination.strip()[:80], "created_at": created}


def list_plans(user_id: int) -> list[dict]:
    with tx() as db:
        rows = db.execute(
            "SELECT id, kind, title, destination, created_at FROM plans WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_plan(user_id: int, plan_id: str) -> dict | None:
    with tx() as db:
        row = db.execute("SELECT * FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "kind": row["kind"], "title": row["title"], "destination": row["destination"],
            "created_at": row["created_at"], "payload": json.loads(row["payload"])}


def delete_plan(user_id: int, plan_id: str) -> bool:
    with tx() as db:
        return db.execute("DELETE FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id)).rowcount > 0
