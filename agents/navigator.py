"""
Trip Navigator: budget -> itinerary -> shortest route -> road directions.

Pipeline (each step is an "agent" that reports progress to the live panel):

  1. Budget agent       picks the stay (auto by budget, or the one you chose) and splits the budget:
                        stay / food / buffer / what's left for activities
  2. Stop selector      builds each day from ONE area of the destination: your must-see picks first,
                        then (optionally) the best-rated places matching your interests that still fit
  3. Route optimizer    finds the SHORTEST visiting order for each day. For <= 8 stops it
                        tries every order (exact answer); above that it falls back to
                        nearest-neighbour + 2-opt improvement
  4. Directions agent   asks the public OSRM server for real road geometry and turn-by-turn
                        steps. If OSRM is unreachable we fall back to straight-line legs so
                        the plan still works offline. Transport cost is then recomputed from the
                        REAL distances so the numbers match the directions you see.

Your choices never get silently ignored: a place that cannot fit (day too long, over the pace
limit) is dropped WITH a note explaining why, and an over-budget plan is flagged, not hidden.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import math
import os
import time
from typing import AsyncIterator

import httpx

from data.places import DESTINATIONS

logger = logging.getLogger("navigator")

# Public OSRM demo server by default (fine for a project, not for production).
# Override with the OSRM_URL environment variable to use your own server.
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org/route/v1/driving")
OSRM_TIMEOUT = 8.0

BUFFER_FRACTION = 0.10        # keep 10% of the budget unspent for surprises
STAY_MAX_FRACTION = 0.40      # auto-chosen stay never costs more than 40% of the budget
ROAD_FACTOR = 1.35            # only used to compare routes; scaling distances never changes the best order

# pace -> (max stops per day, max hours per day)
PACE = {"relaxed": (3, 8.0), "balanced": (4, 11.0), "packed": (5, 13.0)}

DEFAULT_CFG = {"avg_speed_kmh": 35.0, "road_factor": 1.35, "cab_rate_per_km": 14.0, "cab_reserve_per_day": 800}

_ROUTE_CACHE: dict[str, dict] = {}


def dest_cfg(destination: str) -> dict:
    return {**DEFAULT_CFG, **DESTINATIONS[destination].get("config", {})}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lng) points in km."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _road_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a, b) * ROAD_FACTOR


def _pt(item: dict) -> tuple[float, float]:
    return (item["lat"], item["lng"])


# ---------------------------------------------------------------------------
# Step 3: shortest visiting order
# ---------------------------------------------------------------------------
def _tour_length(start: tuple, order: list[dict]) -> float:
    """Length of: start -> stops in order -> back to start."""
    pts = [start, *map(_pt, order), start]
    return sum(_road_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def shortest_order(start: tuple[float, float], stops: list[dict]) -> list[dict]:
    """Shortest round trip from `start` through every stop.

    Exact (tries all orders) for up to 8 stops: 8! = 40,320 orders, instant.
    Beyond that: nearest-neighbour, then 2-opt swaps until no swap helps.
    """
    if len(stops) <= 1:
        return list(stops)
    if len(stops) <= 8:
        return list(min(itertools.permutations(stops), key=lambda p: _tour_length(start, list(p))))

    # nearest neighbour
    remaining, order, here = list(stops), [], start
    while remaining:
        nxt = min(remaining, key=lambda s: _road_km(here, _pt(s)))
        order.append(nxt)
        remaining.remove(nxt)
        here = _pt(nxt)
    # 2-opt: reverse a segment whenever that makes the tour shorter
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                candidate = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if _tour_length(start, candidate) + 1e-9 < _tour_length(start, order):
                    order, improved = candidate, True
    return order


# ---------------------------------------------------------------------------
# Steps 1 & 2: stay + budget split + stop selection + day grouping
# ---------------------------------------------------------------------------
def choose_stay(stays: list[dict], budget: float, nights: int, rooms: int) -> dict:
    """Best stay whose total fits within STAY_MAX_FRACTION of the budget;
    if none fit, the cheapest one."""
    affordable = [s for s in stays if s["price_per_night"] * nights * rooms <= budget * STAY_MAX_FRACTION]
    if affordable:
        return max(affordable, key=lambda s: (s["price_per_night"], s["rating"]))
    return min(stays, key=lambda s: s["price_per_night"])


def _centroid(items: list[dict]) -> tuple[float, float]:
    return (sum(p["lat"] for p in items) / len(items), sum(p["lng"] for p in items) / len(items))


def day_slots(places: list[dict], nights: int, must_ids: frozenset = frozenset(),
              interests: frozenset = frozenset(), max_stops: int = 4) -> list[list[dict]]:
    """Decide which places each day may use. Each day sticks to ONE area (region) so a day never
    zig-zags across the whole destination.

    - more areas than days  -> keep the areas with the best score (must-see picks and interest
                               matches count most); must-see places from dropped areas are folded
                               into the nearest kept area
    - fewer areas than days -> split the busiest area into parts along its longer axis
    Days are ordered north -> south."""
    by_region: dict[str, list[dict]] = {}
    for p in places:
        by_region.setdefault(p["region"], []).append(p)

    def score(items: list[dict]) -> float:
        top = sorted(items, key=lambda p: (p["id"] in must_ids, p["category"] in interests, p["rating"]), reverse=True)[:max_stops]
        return sum((100 if p["id"] in must_ids else 0) + (5 if p["category"] in interests else 0) + p["rating"] for p in top)

    ranked = sorted(by_region, key=lambda r: -score(by_region[r]))
    chosen = ranked[:nights]
    for r in ranked[nights:]:
        movers = [p for p in by_region[r] if p["id"] in must_ids]
        if movers:
            target = min(chosen, key=lambda c: haversine_km(_centroid(by_region[r]), _centroid(by_region[c])))
            by_region[target] = by_region[target] + movers

    parts = {r: 1 for r in chosen}
    while sum(parts.values()) < nights:
        splittable = [r for r in parts if len(by_region[r]) > parts[r]]
        if not splittable:
            break
        r = max(splittable, key=lambda r: len(by_region[r]) / parts[r])
        parts[r] += 1

    slots: list[list[dict]] = []
    for r, m in parts.items():
        items = by_region[r]
        lat_span = max(p["lat"] for p in items) - min(p["lat"] for p in items)
        lng_span = (max(p["lng"] for p in items) - min(p["lng"] for p in items)) * math.cos(math.radians(items[0]["lat"]))
        key = (lambda p: -p["lat"]) if lat_span >= lng_span else (lambda p: p["lng"])
        items = sorted(items, key=key)
        size = math.ceil(len(items) / m)
        slots += [items[i * size:(i + 1) * size] for i in range(m)]
    slots = [s for s in slots if s]
    slots.sort(key=lambda items: -_centroid(items)[0])
    return slots


def _day_estimate(stay_pt: tuple, stops: list[dict], cfg: dict) -> tuple[list[dict], float, float]:
    """(best order, estimated road km, estimated hours) for one day, before real routing."""
    order = shortest_order(stay_pt, stops)
    km = _tour_length(stay_pt, order) * cfg["road_factor"] / ROAD_FACTOR if order else 0.0
    hours = km / cfg["avg_speed_kmh"] + sum(s["visit_min"] for s in order) / 60.0
    return order, km, hours


def advice_notes(budget: float, spent: float, buffer: float, stay: dict, stay_was_auto: bool) -> list[str]:
    """Plain-English remarks about the final numbers."""
    notes = []
    unspent = budget - spent - buffer
    if unspent < 0:
        notes.append(f"Over budget by about INR {-unspent:,.0f} (counting the 10% safety buffer). Try a cheaper stay, fewer paid activities, fewer nights or a higher budget.")
    elif unspent > budget * 0.30:
        notes.append(f"You have about INR {unspent:,.0f} to spare: room for a stay upgrade, an extra night or more paid activities.")
    if stay_was_auto and stay["id"] == "budget":
        notes.append("This budget fits the budget stay; a higher budget unlocks better stays.")
    return notes


def build_plan(destination: str, budget: float, nights: int, travelers: int, *,
               must_ids=(), stay_id: str | None = None, interests=(), pace: str = "balanced",
               only_mine: bool = False) -> dict:
    """Steps 1-3. Returns the plan WITHOUT road directions (those come from OSRM)."""
    data = DESTINATIONS[destination]
    cfg = dest_cfg(destination)
    max_stops, max_hours = PACE.get(pace, PACE["balanced"])
    rooms = math.ceil(travelers / 2)

    stay = next((s for s in data["stays"] if s["id"] == stay_id), None)
    stay_was_auto = stay is None
    if stay is None:
        stay = choose_stay(data["stays"], budget, nights, rooms)
    stay_cost = stay["price_per_night"] * nights * rooms
    food_cost = stay["food_per_person_day"] * travelers * nights
    buffer = budget * BUFFER_FRACTION
    stay_pt = (stay["lat"], stay["lng"])

    by_id = {p["id"]: p for p in data["places"]}
    must = [by_id[i] for i in dict.fromkeys(must_ids) if i in by_id]
    must_set = frozenset(p["id"] for p in must)
    interest_set = frozenset(interests)
    warnings: list[str] = []

    def priority(p: dict):
        return (p["id"] in must_set, p["category"] in interest_set, p["rating"], -p["cost"])

    pool_places = must if (only_mine and must) else data["places"]
    slots = day_slots(pool_places, nights, must_set, interest_set, max_stops)
    if len(slots) < nights:
        warnings.append(f"Only {len(slots)} day(s) of sightseeing could be planned from the available places; the other night(s) are free days.")

    activity_pool = max(0.0, budget - stay_cost - food_cost - buffer - nights * cfg["cab_reserve_per_day"])

    # Pass 1: your must-see places go in first (up to the pace limit per day).
    chosen: list[list[dict]] = []
    for items in slots:
        mine = sorted((p for p in items if p["id"] in must_set), key=priority, reverse=True)
        for p in mine[max_stops:]:
            warnings.append(f"{p['name']} did not fit on its day at a {pace} pace ({max_stops} stops max). Add a night or pick a busier pace.")
        chosen.append(mine[:max_stops])
    activity_cost = sum(p["cost"] for st in chosen for p in st) * travelers

    # Pass 2: fill with the best remaining places while the activity money lasts.
    if not (only_mine and must):
        for st, items in zip(chosen, slots):
            for p in sorted((p for p in items if p["id"] not in must_set), key=priority, reverse=True):
                if len(st) >= max_stops:
                    break
                if activity_cost + p["cost"] * travelers <= activity_pool:
                    st.append(p)
                    activity_cost += p["cost"] * travelers

    # Plan, then trim until the whole thing fits the budget and no day is too long.
    # Non-must places are always dropped before any must-see place.
    while True:
        days = []
        for stops in chosen:
            order, km, hours = _day_estimate(stay_pt, stops, cfg)
            days.append({"stops": order, "est_km": km, "est_hours": hours})
        transport = sum(d["est_km"] for d in days) * cfg["cab_rate_per_km"]
        activity_cost = sum(s["cost"] for d in days for s in d["stops"]) * travelers
        total = stay_cost + food_cost + activity_cost + transport + buffer
        too_long = [d for d in days if d["est_hours"] > max_hours and len(d["stops"]) > 1]
        if total <= budget and not too_long:
            break
        if too_long:
            day = max(too_long, key=lambda d: d["est_hours"])
            candidates = [s for s in day["stops"] if s["id"] not in must_set] or day["stops"]
        else:
            candidates = [s for d in days for s in d["stops"] if s["id"] not in must_set]
        if not candidates:
            break  # over budget with only your must-see places left: keep them and say so
        victim = min(candidates, key=lambda p: (p["id"] in must_set, p["rating"], -p["cost"]))
        if victim["id"] in must_set:
            warnings.append(f"{victim['name']} was dropped because that day would run over {max_hours:.0f} hours. Add a night or pick a relaxed pace with fewer places per day.")
        chosen = [[s for s in st if s["id"] != victim["id"]] for st in chosen]

    for i, d in enumerate(days, 1):
        if d["est_hours"] > max_hours and len(d["stops"]) == 1:
            warnings.append(f"Day {i} is a long day (about {d['est_hours']:.0f} hours) because of {d['stops'][0]['name']}.")

    spent = stay_cost + food_cost + activity_cost + transport
    return {
        "destination": destination, "budget": budget, "nights": nights, "travelers": travelers, "rooms": rooms,
        "pace": pace, "interests": sorted(interest_set), "only_mine": bool(only_mine and must),
        "selected_ids": sorted(must_set),
        "stay": {**stay, "total": stay_cost}, "stay_was_auto": stay_was_auto,
        "breakdown": {
            "stay": round(stay_cost), "food": round(food_cost), "activities": round(activity_cost),
            "local_transport": round(transport), "buffer": round(buffer), "spent": round(spent),
            "remaining": round(budget - spent),             # cash left, buffer included
            "unspent": round(budget - spent - buffer),      # left AFTER the safety buffer (can be negative)
        },
        "days": [{"day": i + 1, "stops": d["stops"], "est_km": d["est_km"], "est_hours": d["est_hours"]} for i, d in enumerate(days)],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Step 4: road directions (OSRM) with offline fallback
# ---------------------------------------------------------------------------
_TURN_WORDS = {
    "left": "left", "right": "right", "slight left": "slight left", "slight right": "slight right",
    "sharp left": "sharp left", "sharp right": "sharp right", "straight": "straight", "uturn": "U-turn",
}


def _compass(bearing: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int(((bearing % 360) + 22.5) // 45) % 8]


def step_instruction(step: dict, arrive_label: str | None = None) -> str:
    """Turn one OSRM step into a plain-English instruction."""
    m = step.get("maneuver", {})
    kind, mod = m.get("type", ""), m.get("modifier", "")
    road = step.get("name") or "the road"
    if kind == "depart":
        return f"Head {_compass(m.get('bearing_after', 0))} on {road}"
    if kind == "arrive":
        return f"Arrive at {arrive_label}" if arrive_label else "Arrive at your destination"
    if kind in ("roundabout", "rotary"):
        return f"At the roundabout, take exit {m['exit']} onto {road}" if m.get("exit") else f"Enter the roundabout towards {road}"
    if kind in ("exit roundabout", "exit rotary"):
        return f"Exit the roundabout onto {road}"
    if kind == "merge":
        return f"Merge onto {road}"
    if kind in ("on ramp", "off ramp"):
        return f"Take the ramp onto {road}"
    if kind == "fork":
        return f"Keep {_TURN_WORDS.get(mod, 'straight')} at the fork onto {road}"
    if kind == "end of road":
        return f"At the end of the road, turn {_TURN_WORDS.get(mod, 'ahead')} onto {road}"
    if kind in ("continue", "new name") or mod == "straight":
        return f"Continue onto {road}"
    if mod in _TURN_WORDS:
        return f"Turn {_TURN_WORDS[mod]} onto {road}"
    return f"Continue on {road}"


def parse_osrm(payload: dict, labels: list[str]) -> dict:
    """Convert an OSRM /route response into our route shape.
    `labels` = names of the waypoints in order (hotel, stop 1, ..., hotel)."""
    route = payload["routes"][0]
    legs = []
    for i, leg in enumerate(route["legs"]):
        steps = [
            {
                "instruction": step_instruction(s, labels[i + 1] if s.get("maneuver", {}).get("type") == "arrive" else None),
                "distance_m": round(s.get("distance", 0)),
            }
            for s in leg.get("steps", [])
        ]
        legs.append({
            "from": labels[i], "to": labels[i + 1],
            "distance_km": round(leg["distance"] / 1000, 1),
            "duration_min": round(leg["duration"] / 60),
            "steps": steps,
        })
    return {
        "source": "osrm",
        "distance_km": round(route["distance"] / 1000, 1),
        "duration_min": round(route["duration"] / 60),
        # GeoJSON is [lng, lat]; Leaflet wants [lat, lng]
        "geometry": [[c[1], c[0]] for c in route["geometry"]["coordinates"]],
        "legs": legs,
    }


def estimate_route(points: list[tuple[float, float]], labels: list[str], cfg: dict | None = None) -> dict:
    """Offline fallback: straight lines between waypoints, with rough distances/times
    and a one-line instruction per leg (compass direction + distance)."""
    cfg = cfg or DEFAULT_CFG
    legs, total_km, total_min = [], 0.0, 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        km = haversine_km(a, b) * cfg["road_factor"]
        minutes = km / cfg["avg_speed_kmh"] * 60
        bearing = math.degrees(math.atan2(
            math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0])),
            math.cos(math.radians(a[0])) * math.sin(math.radians(b[0]))
            - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1])),
        ))
        legs.append({
            "from": labels[i], "to": labels[i + 1],
            "distance_km": round(km, 1), "duration_min": round(minutes),
            "steps": [
                {"instruction": f"Head {_compass(bearing)} for about {km:.1f} km towards {labels[i + 1]}", "distance_m": round(km * 1000)},
                {"instruction": f"Arrive at {labels[i + 1]}", "distance_m": 0},
            ],
        })
        total_km += km
        total_min += minutes
    return {
        "source": "estimate",
        "distance_km": round(total_km, 1),
        "duration_min": round(total_min),
        "geometry": [[p[0], p[1]] for p in points],
        "legs": legs,
    }


async def fetch_route(points: list[tuple[float, float]], labels: list[str], cfg: dict | None = None) -> dict:
    """Road route through the waypoints, or the offline estimate if OSRM fails."""
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    if coords in _ROUTE_CACHE:
        return _ROUTE_CACHE[coords]
    try:
        async with httpx.AsyncClient(timeout=OSRM_TIMEOUT) as client:
            r = await client.get(f"{OSRM_URL}/{coords}", params={"overview": "full", "geometries": "geojson", "steps": "true"})
            r.raise_for_status()
            payload = r.json()
        if payload.get("code") != "Ok":
            raise ValueError(f"OSRM said {payload.get('code')}")
        route = parse_osrm(payload, labels)
        if len(route["legs"]) != len(points) - 1 or not route["geometry"]:
            raise ValueError("OSRM returned an incomplete route")
        _ROUTE_CACHE[coords] = route
        return route
    except Exception as e:  # network down, rate limited, bad response ...
        logger.warning("OSRM unavailable (%s); using straight-line estimate", e)
        return estimate_route(points, labels, cfg)


# ---------------------------------------------------------------------------
# Streaming entry point: yields one event per pipeline stage so the UI can show
# the agents working live.
# ---------------------------------------------------------------------------
def _stop_public(s: dict, selected: set) -> dict:
    out = {k: s[k] for k in ("id", "name", "lat", "lng", "cost", "visit_min", "rating", "category", "region")}
    out["selected"] = s["id"] in selected
    return out


async def plan_trip_events(destination: str, budget: float, nights: int, travelers: int, *,
                           must_ids=(), stay_id: str | None = None, interests=(),
                           pace: str = "balanced", only_mine: bool = False) -> AsyncIterator[dict]:
    t0 = time.perf_counter()
    now = lambda: int((time.perf_counter() - t0) * 1000)

    def stage_done(name: str, started: int, detail: str) -> dict:
        return {"event": "agent", "name": name, "status": "done", "start_ms": started, "end_ms": now(), "detail": detail}

    yield {"event": "start", "agents": [
        {"name": "budget", "label": "Budget agent", "icon": "💰"},
        {"name": "selector", "label": "Stop selector", "icon": "📍"},
        {"name": "optimizer", "label": "Route optimizer", "icon": "🧮"},
        {"name": "directions", "label": "Directions agent", "icon": "🧭"},
    ]}

    cfg = dest_cfg(destination)
    # Steps 1-3 are fast local computation; we still report them as separate stages.
    yield {"event": "agent", "name": "budget", "status": "running", "start_ms": now()}
    s = now()
    plan = build_plan(destination, budget, nights, travelers, must_ids=must_ids, stay_id=stay_id,
                      interests=interests, pace=pace, only_mine=only_mine)
    bd = plan["breakdown"]
    yield stage_done("budget", s, f"Stay: {plan['stay']['label']}" + (" (your choice)" if not plan["stay_was_auto"] else ""))

    yield {"event": "agent", "name": "selector", "status": "running", "start_ms": now()}
    s = now()
    n_stops = sum(len(d["stops"]) for d in plan["days"])
    picked = len(plan["selected_ids"])
    yield stage_done("selector", s, f"{n_stops} stops across {len(plan['days'])} day(s)" + (f", {picked} of your picks" if picked else ""))

    yield {"event": "agent", "name": "optimizer", "status": "running", "start_ms": now()}
    s = now()
    yield stage_done("optimizer", s, "Shortest visiting order found for each day")

    # Step 4: directions for every day in parallel
    yield {"event": "agent", "name": "directions", "status": "running", "start_ms": now()}
    s = now()
    stay_pt = (plan["stay"]["lat"], plan["stay"]["lng"])

    async def day_route(day: dict) -> dict:
        if not day["stops"]:
            return {"source": "none", "distance_km": 0, "duration_min": 0, "geometry": [], "legs": []}
        pts = [stay_pt, *[(x["lat"], x["lng"]) for x in day["stops"]], stay_pt]
        labels = [plan["stay"]["label"], *[x["name"] for x in day["stops"]], plan["stay"]["label"]]
        return await fetch_route(pts, labels, cfg)

    routes = await asyncio.gather(*(day_route(d) for d in plan["days"]))
    sources = {r["source"] for r in routes if r["source"] != "none"}
    source = "osrm" if sources == {"osrm"} else ("estimate" if sources else "none")
    yield stage_done("directions", s, "Road directions from OSRM" if source == "osrm" else "OSRM unreachable: using straight-line estimates")

    # Recompute transport from the distances actually shown to the user.
    total_km = sum(r["distance_km"] for r in routes)
    transport = total_km * cfg["cab_rate_per_km"]
    spent = bd["stay"] + bd["food"] + bd["activities"] + transport
    bd["local_transport"] = round(transport)
    bd["spent"] = round(spent)
    bd["remaining"] = round(budget - spent)
    bd["unspent"] = round(budget - spent - bd["buffer"])
    bd["total_km"] = round(total_km, 1)

    selected = set(plan["selected_ids"])
    days_out = []
    for d, route in zip(plan["days"], routes):
        driving_h = route["duration_min"] / 60
        visit_h = sum(x["visit_min"] for x in d["stops"]) / 60
        days_out.append({
            "day": d["day"], "stops": [_stop_public(x, selected) for x in d["stops"]],
            "route": route, "total_hours": round(driving_h + visit_h, 1),
        })

    data = DESTINATIONS[destination]
    result = {
        "destination": destination, "budget": budget, "nights": nights, "travelers": travelers, "rooms": plan["rooms"],
        "pace": plan["pace"], "interests": plan["interests"], "only_mine": plan["only_mine"],
        "center": data["center"], "region_labels": data["region_labels"],
        "stay": {k: plan["stay"][k] for k in ("id", "label", "lat", "lng", "price_per_night", "rating", "total")},
        "breakdown": bd,
        "over_budget": bd["unspent"] < 0,
        "notes": plan["warnings"] + advice_notes(budget, spent, bd["buffer"], plan["stay"], plan["stay_was_auto"]),
        "days": days_out,
        "routing_source": source,
        "note": "Sample data: coordinates are approximate and costs are rough estimates.",
    }
    yield {"event": "plan", "data": result}
    yield {"event": "done", "total_ms": now()}
