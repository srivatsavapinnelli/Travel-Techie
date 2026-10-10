"""
Travel Techie BFF — Phase 1/3 implementation, now serving the frontend too.

Run with: uvicorn main:app --reload
Then open http://localhost:8000/ — the same process serves index.html AND
the /api/* endpoints it calls, so there's nothing else to start separately.

index.html already contains this logic (written before this backend
existed, but designed for exactly this setup):
    const API_BASE = (location.port === '8000') ? '/api' : 'http://localhost:8000/api';
That's why every route below lives under /api — it's matching what the
frontend was already built to call when served from port 8000.
"""
from __future__ import annotations

import json
import logging
import os
import uuid

import anthropic
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents import budget_agent, navigator, orchestrator, planner_agent
from db.cache import cache, cache_key
from data.places import DESTINATIONS
from db import bookings_store
from account_routes import router as account_router
from models.schemas import (
    BFFEnvelope,
    BookingRequest,
    HolidayStreamRequest,
    Itinerary,
    LogSpendRequest,
    NavigatorRequest,
    PlannerRequest,
    SearchIntent,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Travel Techie BFF")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your actual frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# All endpoints below are attached to this router, then mounted under /api.
api = APIRouter(prefix="/api")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# In-memory session store for the budget safeguard demo. Swap for
# PostgreSQL-backed sessions once auth/persistence is wired (Phase 1 note).
_sessions: dict[str, dict] = {}


def _envelope(data, providers_used=None, partial=False) -> BFFEnvelope:
    return BFFEnvelope(
        data=data,
        meta={"providers_used": providers_used or [], "partial": partial},
    )


# ---------------------------------------------------------------------------
# Single-vertical searches — orchestrator fans out, but only one vertical
# is requested so this is really just "parallel across providers", not
# across verticals. Kept as separate endpoints to match the frontend's tabs.
# ---------------------------------------------------------------------------
@api.post("/bff/flights/search", response_model=BFFEnvelope)
async def search_flights(intent: SearchIntent):
    key = cache_key("flights", dest=intent.destination, date=str(intent.depart_date))
    if cached := await cache.get(key):
        return _envelope(cached, partial=False)

    outcome = await orchestrator.search_all_verticals(intent, ["flights"])
    results = [r.model_dump() for r in outcome["results"].get("flights", [])]
    await cache.set(key, results)
    return _envelope(results, outcome["providers_used"], outcome["partial"])


@api.post("/bff/hotels/search", response_model=BFFEnvelope)
async def search_hotels(intent: SearchIntent):
    outcome = await orchestrator.search_all_verticals(intent, ["hotels"])
    results = [r.model_dump() for r in outcome["results"].get("hotels", [])]
    return _envelope(results, outcome["providers_used"], outcome["partial"])


@api.post("/bff/trains/search", response_model=BFFEnvelope)
@api.post("/bff/buses/search", response_model=BFFEnvelope)
async def search_transit(intent: SearchIntent):
    outcome = await orchestrator.search_all_verticals(intent, ["transit"])
    results = [r.model_dump() for r in outcome["results"].get("transit", [])]
    return _envelope(results, outcome["providers_used"], outcome["partial"])


# Cabs now run as their own agent (agents/../adapters/cab_adapter.py)
# instead of sharing the combined train/bus mock — a real Uber/Ola partner
# API plugs in here without touching anything else.
@api.post("/bff/cabs/search", response_model=BFFEnvelope)
async def search_cabs(intent: SearchIntent):
    outcome = await orchestrator.search_all_verticals(intent, ["cabs"])
    results = [r.model_dump() for r in outcome["results"].get("cabs", [])]
    return _envelope(results, outcome["providers_used"], outcome["partial"])


# Tours & Attractions — previously frontend-only demo data, now backed by
# its own agent (adapters/tours_adapter.py, standing in for Viator/GetYourGuide).
@api.post("/bff/tours/search", response_model=BFFEnvelope)
async def search_tours(intent: SearchIntent):
    outcome = await orchestrator.search_all_verticals(intent, ["tours"])
    results = [r.model_dump() for r in outcome["results"].get("tours", [])]
    return _envelope(results, outcome["providers_used"], outcome["partial"])


# ---------------------------------------------------------------------------
# Smart Route — the clear multi-agent case: fan out to flights + transit
# in parallel, then hand the merged results to the route-ranking agent.
# ---------------------------------------------------------------------------
@api.post("/bff/smart-route/compare", response_model=BFFEnvelope)
async def smart_route_compare(intent: SearchIntent):
    outcome = await orchestrator.search_all_verticals(intent, ["flights", "transit"])
    ranked = orchestrator.rank_smart_route(outcome["results"], intent.priority)
    return _envelope(
        [r.model_dump() for r in ranked],
        outcome["providers_used"],
        outcome["partial"],
    )


# ---------------------------------------------------------------------------
# Holiday Packages — flight, hotel, and tour agents run in parallel, then a
# packaging step composes them into Budget/Comfort/Premium bundles.
# ---------------------------------------------------------------------------
@api.post("/bff/holidays/search", response_model=BFFEnvelope)
async def search_holidays(intent: SearchIntent):
    result = await orchestrator.build_holiday_packages(intent)
    return _envelope(result["packages"], result["providers_used"], result["partial"])




# ---------------------------------------------------------------------------
# Live streams (Server-Sent Events). Each line the browser receives is
#   data: {json event}\n\n
# Events: start -> agent (running/done/failed, many) -> result -> done.
# ---------------------------------------------------------------------------
def _sse(events) -> StreamingResponse:
    async def body():
        try:
            async for ev in events:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as e:  # never leave the browser hanging on a broken stream
            logging.exception("stream failed")
            yield f"data: {json.dumps({'event': 'error', 'detail': str(e)[:200]})}\n\n"

    return StreamingResponse(
        body(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.post("/bff/holidays/stream")
async def holidays_stream(req: HolidayStreamRequest):
    return _sse(orchestrator.stream_holiday_packages(req, req.nights, req.rooms))


# ---------------------------------------------------------------------------
# Trip Navigator: budget -> itinerary -> shortest route -> road directions
# ---------------------------------------------------------------------------
@api.get("/bff/navigator/destinations")
async def navigator_destinations():
    return {"destinations": [
        {"name": name, "tagline": d["tagline"], "center": d["center"]} for name, d in DESTINATIONS.items()
    ]}


@api.get("/bff/navigator/places")
async def navigator_places(destination: str):
    """Everything the page needs to let the user customise a trip: places, stays, areas, categories."""
    d = DESTINATIONS.get(destination)
    if not d:
        raise HTTPException(status_code=404, detail=f"Unknown destination. Choose from: {', '.join(DESTINATIONS)}")
    return {
        "destination": destination, "tagline": d["tagline"], "center": d["center"],
        "region_labels": d["region_labels"],
        "categories": sorted({p["category"] for p in d["places"]}),
        "stays": d["stays"], "places": d["places"],
    }


@api.post("/bff/navigator/plan/stream")
async def navigator_plan_stream(req: NavigatorRequest):
    d = DESTINATIONS.get(req.destination)
    if not d:
        raise HTTPException(status_code=422, detail=f"Sample data is only available for: {', '.join(DESTINATIONS)}")
    place_ids = {p["id"] for p in d["places"]}
    bad = [i for i in req.must_ids if i not in place_ids]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown place(s) for {req.destination}: {', '.join(bad)}")
    if req.stay_id and req.stay_id not in {s["id"] for s in d["stays"]}:
        raise HTTPException(status_code=422, detail=f"Unknown stay '{req.stay_id}' for {req.destination}")
    cats = {p["category"] for p in d["places"]}
    badc = [c for c in req.interests if c not in cats]
    if badc:
        raise HTTPException(status_code=422, detail=f"Unknown interest(s) for {req.destination}: {', '.join(badc)}")
    return _sse(navigator.plan_trip_events(
        req.destination, req.budget, req.nights, req.travelers,
        must_ids=req.must_ids, stay_id=req.stay_id, interests=req.interests,
        pace=req.pace, only_mine=req.only_mine,
    ))


# ---------------------------------------------------------------------------
# AI Planner — matches handlePlan()/renderAIResults() in the frontend
# ---------------------------------------------------------------------------
@api.post("/planner/generate", response_model=Itinerary)
async def planner_generate(req: PlannerRequest):
    try:
        itinerary = await planner_agent.generate_itinerary(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except anthropic.AuthenticationError as e:
        raise HTTPException(
            status_code=502,
            detail="Anthropic rejected the API key — check ANTHROPIC_API_KEY is set correctly.",
        ) from e
    except anthropic.PermissionDeniedError as e:
        raise HTTPException(
            status_code=502,
            detail="Anthropic denied this request — the account may need billing set up.",
        ) from e
    except anthropic.RateLimitError as e:
        raise HTTPException(
            status_code=502, detail="Rate limited by Anthropic — wait a moment and try again."
        ) from e
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {e}") from e

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {"itinerary": itinerary, "logs": {}}
    # session_id isn't in the current frontend's fetch, but is returned in
    # the header for a future client update so /planner/log-spend can be
    # session-scoped instead of client-side window.dayLogs.
    return itinerary


@api.post("/bff/planner/log-spend", response_model=BFFEnvelope)
async def planner_log_spend(req: LogSpendRequest):
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    session["logs"][req.day] = req.amount
    result = budget_agent.recalculate(session["itinerary"], session["logs"])
    return _envelope(result)


@api.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Bookings — backs the "My Bookings" tab and every Book/Select button
# across the search tabs. client_id is generated in the browser and kept in
# localStorage, standing in for real auth until that's wired up (Phase 1).
# ---------------------------------------------------------------------------
@api.post("/bookings", response_model=BFFEnvelope)
async def create_booking(req: BookingRequest):
    record = bookings_store.create_booking(req)
    return _envelope(record.model_dump())


@api.get("/bookings", response_model=BFFEnvelope)
async def get_bookings(client_id: str):
    records = bookings_store.list_bookings(client_id)
    return _envelope([r.model_dump() for r in records])


@api.post("/bookings/{booking_id}/cancel", response_model=BFFEnvelope)
async def cancel_booking(client_id: str, booking_id: str):
    record = bookings_store.cancel_booking(client_id, booking_id)
    if not record:
        raise HTTPException(status_code=404, detail="Booking not found")
    return _envelope(record.model_dump())



app.include_router(api)
app.include_router(account_router)


# ---------------------------------------------------------------------------
# Serve the frontend from the SAME process. Registered after api routes so
# it never shadows them — Starlette matches routes in the order they were
# added, and every /api/* path above is already registered by this point.
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Any other static asset referenced from index.html (there currently are
# none — fonts load from Google's CDN — but this covers you if you add any).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
