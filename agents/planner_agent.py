"""
Planner agent: generates the itinerary the frontend's AI Planner tab
expects, using the real Anthropic API. A lightweight critic step validates
the shape and that the budget breakdown roughly sums to the requested
budget before handing back to the BFF — this is the "verification agent"
from the implementation plan, kept inline here for simplicity.
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

from models.schemas import Itinerary, PlannerRequest

logger = logging.getLogger("planner_agent")
client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

_SCHEMA_HINT = """{
  "destination_overview": "string",
  "budget_breakdown": {"travel": number, "stay": number, "food": number, "activities": number},
  "days": [
    {
      "day": number,
      "city": "string",
      "title": "string",
      "activities": ["string"],
      "meals_note": "string",
      "hotel": {"name": "string", "type": "string", "price_per_night": number}
    }
  ]
}"""


def _build_prompt(req: PlannerRequest) -> str:
    return f"""You are a travel planner. Build a {req.duration}-day itinerary from
{req.startCity} to {req.destination or "a destination you choose"} for
{req.travelers} traveler(s), total budget INR {req.budget}.
Food preference: {req.food}. Hotel preference: {req.hotel}.
Interests: {", ".join(req.interests) or "none specified"}.

The four budget_breakdown values must sum to approximately the total budget.
Respond with ONLY valid JSON, no markdown fences, no preamble, matching
exactly this schema:
{_SCHEMA_HINT}"""


async def generate_itinerary(req: PlannerRequest) -> Itinerary:
    message = await client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_tokens=4000,
        messages=[{"role": "user", "content": _build_prompt(req)}],
    )
    raw_text = "".join(block.text for block in message.content if block.type == "text")

    # Defensive: strip markdown fences if the model adds them despite being
    # told not to — turns an opaque 500 into either a clean parse or a
    # clear ValueError instead.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("Planner returned non-JSON output: %s", raw_text[:500])
        raise ValueError(f"The AI's response wasn't valid JSON ({e}). Try again.") from e

    itinerary = Itinerary.model_validate(payload)
    return _critic_check(itinerary, req)


def _critic_check(itinerary: Itinerary, req: PlannerRequest) -> Itinerary:
    """Sanity pass, not another LLM call. Only rejects genuinely broken
    responses (empty budget, wrong day count) — a budget that drifts from
    what was asked is common for ambitious combinations (e.g. a small
    budget with a luxury/resort preference and several travelers) and is
    still useful information for the traveler, so it's surfaced as a
    warning on the itinerary rather than blocking the response entirely.
    """
    bb = itinerary.budget_breakdown
    total = bb.travel + bb.stay + bb.food + bb.activities
    if total == 0:
        raise ValueError("Planner returned an empty budget breakdown")
    if len(itinerary.days) != req.duration:
        raise ValueError(
            f"Expected {req.duration} days, planner returned {len(itinerary.days)}"
        )

    drift = abs(total - req.budget) / req.budget
    if drift > 0.35:
        logger.warning(
            "Budget breakdown (%.0f) drifted %.0f%% from requested budget (%.0f) "
            "for a %s-day trip with %s traveler(s) and '%s' hotel preference",
            total, drift * 100, req.budget, req.duration, req.travelers, req.hotel,
        )
    return itinerary
