"""
The orchestrator agent: receives a search intent, fans work out to the
relevant provider agents in parallel, and merges whatever comes back within
the timeout budget. One slow/failed agent never blocks the others.
"""
from __future__ import annotations

import asyncio
import logging

from adapters.cab_adapter import MockCabAdapter
from adapters.flight_adapter import MockAmadeusAdapter
from adapters.hotel_adapter import MockBookingAdapter
from adapters.tours_adapter import MockToursAdapter
from adapters.transit_adapter import MockTransitAdapter
from models.schemas import NormalizedResult, SearchIntent

logger = logging.getLogger("orchestrator")

# In production these live behind a registry so you can add/disable a
# provider via config (see the "feature flags per provider" note in the
# implementation plan) instead of editing this list.
FLIGHT_ADAPTERS = [MockAmadeusAdapter()]
HOTEL_ADAPTERS = [MockBookingAdapter()]
TRANSIT_ADAPTERS = [MockTransitAdapter()]  # trains + buses (still combined — see README known limitation)
CAB_ADAPTERS = [MockCabAdapter()]
TOUR_ADAPTERS = [MockToursAdapter()]

DEFAULT_TIMEOUT_SECONDS = 8.0


async def _run_adapters(adapters, intent: SearchIntent) -> list[NormalizedResult]:
    """Run every adapter for one vertical in parallel, merge, and never let
    one adapter's exception take the others down with it."""
    outcomes = await asyncio.gather(
        *(a.search(intent) for a in adapters), return_exceptions=True
    )
    results: list[NormalizedResult] = []
    for adapter, outcome in zip(adapters, outcomes):
        if isinstance(outcome, Exception):
            logger.warning("adapter %s failed: %s", adapter.provider_name, outcome)
            continue
        results.extend(outcome)
    return results


async def search_all_verticals(
    intent: SearchIntent, verticals: list[str], timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> dict:
    """Fan out to every requested vertical in parallel. Returns whichever
    verticals completed in time; the rest are marked partial=True so the
    BFF can tell the frontend what's still missing."""
    vertical_tasks = {}
    if "flights" in verticals:
        vertical_tasks["flights"] = _run_adapters(FLIGHT_ADAPTERS, intent)
    if "hotels" in verticals:
        vertical_tasks["hotels"] = _run_adapters(HOTEL_ADAPTERS, intent)
    if "transit" in verticals:
        vertical_tasks["transit"] = _run_adapters(TRANSIT_ADAPTERS, intent)
    if "cabs" in verticals:
        vertical_tasks["cabs"] = _run_adapters(CAB_ADAPTERS, intent)
    if "tours" in verticals:
        vertical_tasks["tours"] = _run_adapters(TOUR_ADAPTERS, intent)

    try:
        outcomes = await asyncio.wait_for(
            asyncio.gather(*vertical_tasks.values(), return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Nothing came back at all within budget — return an explicit
        # partial response rather than raising a 500.
        return {
            "results": {k: [] for k in vertical_tasks},
            "partial": True,
            "providers_used": [],
        }

    results: dict[str, list[NormalizedResult]] = {}
    partial = False
    providers_used: set[str] = set()

    for vertical, outcome in zip(vertical_tasks.keys(), outcomes):
        if isinstance(outcome, Exception):
            logger.warning("vertical %s failed: %s", vertical, outcome)
            results[vertical] = []
            partial = True
        else:
            results[vertical] = outcome
            providers_used.update(r.provider for r in outcome)

    return {
        "results": results,
        "partial": partial,
        "providers_used": sorted(providers_used),
    }


def rank_smart_route(results: dict[str, list[NormalizedResult]], priority: str) -> list[NormalizedResult]:
    """The route-ranking agent: takes normalized results across verticals
    and scores them against the user's stated priority. This is the
    judgment call that separates Smart Route from a plain merge."""
    combined = [r for bucket in results.values() for r in bucket]

    if priority == "cheapest":
        return sorted(combined, key=lambda r: r.price)
    if priority == "fastest":
        return sorted(combined, key=lambda r: r.duration_minutes or float("inf"))

    # balanced: normalize price and duration to 0-1 and blend
    prices = [r.price for r in combined] or [1]
    durations = [r.duration_minutes or 0 for r in combined] or [1]
    p_min, p_max = min(prices), max(prices) or 1
    d_min, d_max = min(durations), max(durations) or 1

    def score(r: NormalizedResult) -> float:
        p_norm = (r.price - p_min) / (p_max - p_min) if p_max > p_min else 0
        d_norm = ((r.duration_minutes or 0) - d_min) / (d_max - d_min) if d_max > d_min else 0
        return 0.5 * p_norm + 0.5 * d_norm

    return sorted(combined, key=score)


async def build_holiday_packages(intent: SearchIntent, tiers: int = 3) -> dict:
    """The Holiday Packages agent. Genuinely parallel multi-agent
    orchestration: the flight, hotel, and tour agents all run at the same
    time (not one after another), and once all three land, a packaging
    step composes them into ready-made bundles — pairing the Nth-cheapest
    flight with the Nth-cheapest hotel and a rotating tour pick, so
    "Budget / Comfort / Premium" tiers reflect genuinely different
    combinations rather than the same flight three times over."""
    outcome = await search_all_verticals(intent, ["flights", "hotels", "tours"])
    flights = sorted(outcome["results"].get("flights", []), key=lambda r: r.price)
    hotels = sorted(outcome["results"].get("hotels", []), key=lambda r: r.price)
    tours = outcome["results"].get("tours", [])

    packages = []
    tier_labels = ["Budget", "Comfort", "Premium"]
    for i in range(min(tiers, len(flights), len(hotels)) or 0):
        flight = flights[min(i, len(flights) - 1)]
        hotel = hotels[min(i, len(hotels) - 1)]
        tour = tours[i % len(tours)] if tours else None
        total = flight.price + hotel.price + (tour.price if tour else 0)
        packages.append({
            "tier": tier_labels[i] if i < len(tier_labels) else f"Tier {i+1}",
            "flight": flight.model_dump(),
            "hotel": hotel.model_dump(),
            "tour": tour.model_dump() if tour else None,
            "total_price": round(total, 2),
            "currency": "INR",
        })

    return {
        "packages": packages,
        "partial": outcome["partial"],
        "providers_used": outcome["providers_used"],
    }


# ---------------------------------------------------------------------------
# Live (streamed) holiday orchestration.
#
# Same three agents as build_holiday_packages(), but instead of waiting for all
# of them and returning once, this yields an event the moment each agent starts
# and finishes. The frontend draws those events as a live orchestration panel,
# so you can SEE the flight/hotel/tour agents run in parallel, then the
# packaging agent assemble the result.
#
# Pricing is explicit so the UI's live budget tracker can recompute it:
#   flight  = price x travelers          (priced per person)
#   hotel   = price x nights x rooms     (priced per room per night)
#   tour    = price x travelers          (priced per person)
# ---------------------------------------------------------------------------
import time as _time


def package_total(flight, hotel, tour, travelers: int, nights: int, rooms: int) -> float:
    total = flight["price"] * travelers + hotel["price"] * nights * rooms
    if tour:
        total += tour["price"] * travelers
    return round(total, 2)


async def stream_holiday_packages(intent: SearchIntent, nights: int, rooms: int):
    t0 = _time.perf_counter()
    now = lambda: int((_time.perf_counter() - t0) * 1000)

    specs = [
        ("flights", "Flight agent", "✈️", FLIGHT_ADAPTERS),
        ("hotels", "Hotel agent", "🏨", HOTEL_ADAPTERS),
        ("tours", "Tours agent", "🎟️", TOUR_ADAPTERS),
    ]
    yield {"event": "start", "agents": [
        *({"name": k, "label": label, "icon": icon} for k, label, icon, _ in specs),
        {"name": "packaging", "label": "Packaging agent", "icon": "📦"},
    ]}

    queue: asyncio.Queue = asyncio.Queue()
    results: dict[str, list] = {}

    async def run(key: str, adapters) -> None:
        start = now()
        await queue.put({"event": "agent", "name": key, "status": "running", "start_ms": start})
        try:
            found = await asyncio.wait_for(_run_adapters(adapters, intent), DEFAULT_TIMEOUT_SECONDS)
            results[key] = found
            providers = sorted({r.provider for r in found})
            await queue.put({"event": "agent", "name": key, "status": "done", "start_ms": start, "end_ms": now(),
                             "detail": f"{len(found)} options" + (f" from {', '.join(providers)}" if providers else "")})
        except Exception as e:  # timeout or adapter failure: this agent fails, the others continue
            results[key] = []
            await queue.put({"event": "agent", "name": key, "status": "failed", "start_ms": start, "end_ms": now(),
                             "detail": "timed out" if isinstance(e, asyncio.TimeoutError) else str(e)[:80]})

    tasks = [asyncio.create_task(run(k, a)) for k, _, _, a in specs]
    finished = 0
    while finished < len(tasks):
        ev = await queue.get()
        if ev["status"] != "running":
            finished += 1
        yield ev
    await asyncio.gather(*tasks)

    # Packaging agent: pair the Nth-cheapest flight with the Nth-cheapest hotel, rotate tours.
    yield {"event": "agent", "name": "packaging", "status": "running", "start_ms": now()}
    start = now()
    flights = sorted((r.model_dump() for r in results["flights"]), key=lambda r: r["price"])
    hotels = sorted((r.model_dump() for r in results["hotels"]), key=lambda r: r["price"])
    tours = sorted((r.model_dump() for r in results["tours"]), key=lambda r: r["price"])

    packages = []
    labels = ["Budget", "Comfort", "Premium"]
    for i in range(min(3, len(flights), len(hotels))):
        tour_i = i % len(tours) if tours else -1
        total = package_total(flights[i], hotels[i], tours[tour_i] if tour_i >= 0 else None,
                              intent.travelers, nights, rooms)
        packages.append({"tier": labels[i], "flight_i": i, "hotel_i": i, "tour_i": tour_i, "total_price": total})

    yield {"event": "agent", "name": "packaging", "status": "done", "start_ms": start, "end_ms": now(),
           "detail": f"{len(packages)} packages built"}
    yield {"event": "packages", "data": {
        "packages": packages,
        "options": {"flights": flights, "hotels": hotels, "tours": tours},
        "travelers": intent.travelers, "nights": nights, "rooms": rooms,
    }}
    yield {"event": "done", "total_ms": now()}
