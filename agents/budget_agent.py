"""
Budget-safeguard agent — server-side equivalent of dayTier() /
renderBudgetSafeguard() in the frontend's <script>. Moving this server-side
means the recalculated budget survives a page refresh and can't be tampered
with client-side, and makes the same logic reusable from a future mobile app.
"""
from __future__ import annotations

from models.schemas import Itinerary

_TIGHT, _TRIM, _ONTRACK = 0.6, 0.9, 1.15


def day_tier(ratio: float) -> dict:
    if ratio < _TIGHT:
        return {"key": "tight", "label": "Budget tight",
                "note": "Budget-friendly dining suggested, one paid stop trimmed, "
                        "prefer local transit over cabs today."}
    if ratio < _TRIM:
        return {"key": "trim", "label": "Running a bit over",
                "note": "Consider one lower-cost meal and shared/public transit today."}
    if ratio < _ONTRACK:
        return {"key": "ontrack", "label": "On track",
                "note": "No changes needed — this day matches the original plan."}
    return {"key": "surplus", "label": "Ahead of budget",
            "note": "Room today for a nicer dinner or an extra paid experience."}


def recalculate(itinerary: Itinerary, logs: dict[int, float]) -> dict:
    """logs: {day_number: actual_amount_spent}. Mirrors window.dayLogs in
    the frontend, but held server-side per session instead."""
    days = itinerary.days
    duration = len(days) or 1
    bb = itinerary.budget_breakdown
    variable_pool = bb.food + bb.activities
    base_daily = variable_pool / duration

    logged_days = [d for d in days if d.day in logs]
    unlogged_days = [d for d in days if d.day not in logs]
    spent_so_far = sum(logs[d.day] for d in logged_days)
    allocated_so_far = base_daily * len(logged_days)
    run_delta = spent_so_far - allocated_so_far
    remaining_pool = max(0.0, variable_pool - spent_so_far)
    new_daily = remaining_pool / len(unlogged_days) if unlogged_days else base_daily
    ratio = (new_daily / base_daily) if base_daily > 0 else 1.0

    return {
        "base_daily": round(base_daily, 2),
        "new_daily": round(new_daily, 2),
        "run_delta": round(run_delta, 2),
        "logged_days": len(logged_days),
        "duration": duration,
        "tier": day_tier(ratio) if logged_days else None,
    }
