"""
Bookings, stored in SQLite so history survives restarts.
Same functions as the old in-memory version, so main.py's endpoints are unchanged.
Guests are keyed by the random id in their browser; logged-in users by their account's client_id.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from db.database import tx
from models.schemas import BookingRecord, BookingRequest

_COLS = "booking_id, client_id, vertical, title, subtitle, price, currency, provider, status, created_at"


def _record(row) -> BookingRecord:
    return BookingRecord(**{k: row[k] for k in row.keys()})


def create_booking(req: BookingRequest) -> BookingRecord:
    record = BookingRecord(
        **req.model_dump(),
        booking_id=str(uuid.uuid4()),
        status="confirmed",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with tx() as db:
        db.execute(
            f"INSERT INTO bookings({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (record.booking_id, record.client_id, record.vertical, record.title, record.subtitle,
             record.price, record.currency, record.provider, record.status, record.created_at),
        )
    return record


def list_bookings(client_id: str) -> list[BookingRecord]:
    with tx() as db:
        rows = db.execute(f"SELECT {_COLS} FROM bookings WHERE client_id = ? ORDER BY created_at DESC", (client_id,)).fetchall()
    return [_record(r) for r in rows]


def cancel_booking(client_id: str, booking_id: str) -> Optional[BookingRecord]:
    with tx() as db:
        cur = db.execute("UPDATE bookings SET status = 'cancelled' WHERE client_id = ? AND booking_id = ?", (client_id, booking_id))
        if cur.rowcount == 0:
            return None
        row = db.execute(f"SELECT {_COLS} FROM bookings WHERE booking_id = ?", (booking_id,)).fetchone()
    return _record(row)


def move_bookings(from_client_id: str, to_client_id: str) -> int:
    """Hand a guest's bookings to an account (used right after login). Returns how many moved."""
    if from_client_id == to_client_id:
        return 0
    with tx() as db:
        return db.execute("UPDATE bookings SET client_id = ? WHERE client_id = ?", (to_client_id, from_client_id)).rowcount
