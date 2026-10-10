"""
Backend tests for the live orchestration stream, holiday pricing and Trip Navigator.
No internet or API key needed. Run from the project folder:  python tests/test_features.py
"""
import asyncio
import itertools
import tempfile
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TT_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))  # never touch the real database

from fastapi.testclient import TestClient

from agents import navigator as nav
from agents import orchestrator
from data.places import DESTINATIONS
from main import app

c = TestClient(app)
PLACES = DESTINATIONS["Goa"]["places"]
STAY = (15.4989, 73.8278)


def sse(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


# 1) exact solver really is the shortest (compare with brute force on random subsets)
random.seed(1)
for _ in range(25):
    subset = random.sample(PLACES, random.randint(2, 6))
    best = min(nav._tour_length(STAY, list(p)) for p in itertools.permutations(subset))
    got = nav._tour_length(STAY, nav.shortest_order(STAY, subset))
    assert abs(best - got) < 1e-9
print("1) exact shortest-route solver matches brute force")

# 2) heuristic (>8 stops) is valid and no worse than the naive order
many = PLACES[:12]
h = nav.shortest_order(STAY, many)
assert sorted(s["id"] for s in h) == sorted(s["id"] for s in many)
assert nav._tour_length(STAY, h) <= nav._tour_length(STAY, many)
print("2) nearest-neighbour + 2-opt valid and improves on naive order")

# 3) budget changes the plan, never exceeds the budget, each day is short enough
seen_stays = set()
for budget in (25000, 30000, 50000, 80000, 150000):
    for nights in (2, 3, 5):
        p = nav.build_plan("Goa", budget, nights, 2)
        bd = p["breakdown"]
        assert bd["spent"] + bd["buffer"] <= budget + 1, (budget, nights, bd)
        assert len(p["days"]) == nights
        assert all(len(d["stops"]) <= nav.PACE["balanced"][0] for d in p["days"])
        assert all(d["est_hours"] <= nav.PACE["balanced"][1] or len(d["stops"]) <= 1 for d in p["days"])
        seen_stays.add(p["stay"]["id"])
assert seen_stays == {"budget", "mid", "resort"}, seen_stays
print("3) plans fit the budget; stay tier scales with budget ->", sorted(seen_stays))

# 4) OSRM response parsing (shape taken from the OSRM docs) incl. turn instructions
osrm = {"code": "Ok", "routes": [{
    "distance": 5200.4, "duration": 780.0,
    "geometry": {"type": "LineString", "coordinates": [[73.82, 15.49], [73.83, 15.50], [73.84, 15.51]]},
    "legs": [{"distance": 5200.4, "duration": 780.0, "steps": [
        {"distance": 900, "name": "NH66", "maneuver": {"type": "depart", "bearing_after": 10}},
        {"distance": 1500, "name": "Candolim Road", "maneuver": {"type": "turn", "modifier": "left"}},
        {"distance": 300, "name": "", "maneuver": {"type": "roundabout", "exit": 2}},
        {"distance": 0, "name": "", "maneuver": {"type": "arrive"}}]}]}]}
r = nav.parse_osrm(osrm, ["Hotel", "Fort Aguada"])
steps = [s["instruction"] for s in r["legs"][0]["steps"]]
assert steps == ["Head north on NH66", "Turn left onto Candolim Road",
                 "At the roundabout, take exit 2 onto the road", "Arrive at Fort Aguada"], steps
assert r["geometry"][0] == [15.49, 73.82] and r["distance_km"] == 5.2 and r["duration_min"] == 13
print("4) OSRM parsing + instructions OK")

# 5) offline fallback produces a usable route
e = nav.estimate_route([(15.5, 73.8), (15.6, 73.7), (15.5, 73.8)], ["Hotel", "Chapora Fort", "Hotel"])
assert e["source"] == "estimate" and len(e["legs"]) == 2 and e["distance_km"] > 10
print("5) offline straight-line fallback OK")

# 6) navigator stream end-to-end. Make the network call fail on purpose -> must degrade, not crash.
async def boom(*a, **k):
    raise ConnectionError("no internet")
real_fetch = nav.httpx.AsyncClient
class Dead:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, *a, **k): raise ConnectionError("no internet")
nav.httpx.AsyncClient = Dead
nav._ROUTE_CACHE.clear()
ev = sse(c.post("/api/bff/navigator/plan/stream", json={"budget": 50000, "nights": 3, "travelers": 2}))
nav.httpx.AsyncClient = real_fetch
kinds = [x["event"] for x in ev]
assert kinds[0] == "start" and kinds[-1] == "done" and "plan" in kinds, kinds
done_agents = [x["name"] for x in ev if x["event"] == "agent" and x["status"] == "done"]
assert done_agents == ["budget", "selector", "optimizer", "directions"], done_agents
plan = next(x for x in ev if x["event"] == "plan")["data"]
assert plan["routing_source"] == "estimate" and len(plan["days"]) == 3
assert all(d["route"]["geometry"] for d in plan["days"] if d["stops"])
print("6) navigator stream OK (routing_source =", plan["routing_source"], ")")

bad = c.post("/api/bff/navigator/plan/stream", json={"destination": "Paris", "budget": 50000})
assert bad.status_code == 422
print("7) unsupported destination rejected")

# ---------------------------------------------------------------------------
# NEW: more destinations + user choices
# ---------------------------------------------------------------------------
import math

def km(a, b):
    return nav.haversine_km(a, b)

# 3b) every destination: data sanity + plans at several budgets, nights and paces
assert set(DESTINATIONS) == {"Goa", "Jaipur", "Manali", "Kerala", "Hyderabad"}, list(DESTINATIONS)
for name, d in DESTINATIONS.items():
    ids = [p["id"] for p in d["places"]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate place ids"
    assert len(d["stays"]) == 3 and {x["id"] for x in d["stays"]} == {"budget", "mid", "resort"}
    cats = {p["category"] for p in d["places"]}
    assert all(p["region"] in d["region_labels"] for p in d["places"]), f"{name}: place with unlabelled region"
    for it in [*d["places"], *d["stays"]]:
        assert 6 < it["lat"] < 36 and 68 < it["lng"] < 98, f"{name}: {it} is outside India (lat/lng swapped?)"
        assert km(d["center"], (it["lat"], it["lng"])) < 80, f"{name}: {it.get('name') or it.get('label')} is too far from the centre"
    for budget in (20000, 50000, 120000):
        for nights in (1, 2, 3, 5):
            for pace in ("relaxed", "balanced", "packed"):
                p = nav.build_plan(name, budget, nights, 2, pace=pace)
                cap, hours = nav.PACE[pace]
                assert len(p["days"]) <= nights
                assert all(len(x["stops"]) <= cap for x in p["days"]), (name, budget, nights, pace)
                assert all(x["est_hours"] <= hours or len(x["stops"]) <= 1 for x in p["days"]), (name, budget, nights, pace)
                seen = [s["id"] for x in p["days"] for s in x["stops"]]
                assert len(seen) == len(set(seen)), "a place appears on two days"
print("3b) all 5 destinations: data sane, plans valid for every budget / nights / pace")

# 3c) must-see picks are honoured (when they fit) and flagged
for name, picks in {"Jaipur": ["amber", "hawamahal", "birla"], "Goa": ["palolem", "basilica"], "Hyderabad": ["charminar", "golconda", "ramoji"]}.items():
    p = nav.build_plan(name, 80000, 4, 2, must_ids=picks)
    got = {s["id"] for x in p["days"] for s in x["stops"]}
    assert set(picks) <= got, (name, picks, got)
only = nav.build_plan("Jaipur", 80000, 3, 2, must_ids=["amber", "hawamahal"], only_mine=True)
assert {s["id"] for x in only["days"] for s in x["stops"]} == {"amber", "hawamahal"}
print("3c) your picks always appear; 'only my picks' adds nothing else")

# 3d) too many picks for the pace -> dropped WITH a note, never silently
big = [p["id"] for p in DESTINATIONS["Jaipur"]["places"]][:10]
p = nav.build_plan("Jaipur", 80000, 1, 2, must_ids=big, pace="relaxed")
assert sum(len(x["stops"]) for x in p["days"]) <= 3 and p["warnings"], p["warnings"]
print("3d) overflow picks are dropped with an explanation ->", p["warnings"][0][:70], "...")

# 3e) chosen stay is respected; auto stay changes with budget
p = nav.build_plan("Manali", 50000, 3, 2, stay_id="resort")
assert p["stay"]["id"] == "resort" and not p["stay_was_auto"]
assert nav.build_plan("Manali", 20000, 3, 2)["stay"]["id"] != nav.build_plan("Manali", 150000, 3, 2)["stay"]["id"]
print("3e) your stay choice respected; auto stay scales with budget")

# 3f) interests steer the selection (more stops of the chosen category, never fewer)
def count(plan, cat):
    return sum(1 for x in plan["days"] for s in x["stops"] if s["category"] == cat)
results = []
for dest, budget, nights, cat in [("Manali", 50000, 2, "adventure"), ("Goa", 50000, 2, "culture")]:
    plain = nav.build_plan(dest, budget, nights, 2)
    liked = nav.build_plan(dest, budget, nights, 2, interests=[cat])
    assert count(liked, cat) > count(plain, cat), (dest, cat, count(plain, cat), count(liked, cat))
    results.append(f"{dest}/{cat} {count(plain, cat)}->{count(liked, cat)}")
print("3f) interests steer picks:", ", ".join(results))

# 3g) over-budget is flagged honestly (resort on a tiny budget)
async def run_stream(**payload):
    body = {"destination": "Goa", "budget": 50000, "nights": 3, "travelers": 2, **payload}
    return sse(c.post("/api/bff/navigator/plan/stream", json=body))
nav.httpx.AsyncClient = Dead
tiny = [x for x in asyncio.run(run_stream(budget=9000, stay_id="resort")) if x["event"] == "plan"][0]["data"]
assert tiny["over_budget"] and any("Over budget" in n for n in tiny["notes"])
print("3g) over-budget plan flagged ->", [n for n in tiny["notes"] if "Over budget" in n][0][:60], "...")

# 3h) end-to-end with choices: flags picks, recomputes transport from the shown distances
full = [x for x in asyncio.run(run_stream(destination="Jaipur", budget=60000, must_ids=["amber", "citypalace"], interests=["food"], pace="packed")) if x["event"] == "plan"][0]["data"]
flat = [s for d in full["days"] for s in d["stops"]]
assert {s["id"] for s in flat if s["selected"]} == {"amber", "citypalace"}
km_total = sum(d["route"]["distance_km"] for d in full["days"])
assert abs(full["breakdown"]["local_transport"] - km_total * 12) <= 1, (full["breakdown"]["local_transport"], km_total * 12)
assert full["region_labels"]["amber"] == "Amer & hill forts" and len(full["center"]) == 2
b = full["breakdown"]
assert abs(b["stay"] + b["food"] + b["activities"] + b["local_transport"] - b["spent"]) <= 2
assert abs(b["spent"] + b["buffer"] + b["unspent"] - 60000) <= 2
print("3h) stream with choices OK: picks flagged, transport cost matches shown km, numbers add up")

# 3i) validation + new endpoints
assert c.post("/api/bff/navigator/plan/stream", json={"destination": "Jaipur", "budget": 50000, "must_ids": ["nope"]}).status_code == 422
assert c.post("/api/bff/navigator/plan/stream", json={"destination": "Jaipur", "budget": 50000, "stay_id": "palace"}).status_code == 422
assert c.post("/api/bff/navigator/plan/stream", json={"destination": "Jaipur", "budget": 50000, "interests": ["beach"]}).status_code == 422
assert c.post("/api/bff/navigator/plan/stream", json={"destination": "Jaipur", "budget": 50000, "pace": "turbo"}).status_code == 422
dests = c.get("/api/bff/navigator/destinations").json()["destinations"]
assert [d["name"] for d in dests] == ["Goa", "Jaipur", "Manali", "Kerala", "Hyderabad"]
pl = c.get("/api/bff/navigator/places", params={"destination": "Kerala"}).json()
assert len(pl["places"]) >= 12 and len(pl["stays"]) == 3 and "beach" in pl["categories"] and pl["region_labels"]
assert c.get("/api/bff/navigator/places", params={"destination": "Paris"}).status_code == 404
nav.httpx.AsyncClient = real_fetch
print("3i) validation rejects bad ids/stay/interest/pace; places + destinations endpoints OK")

# 8) holiday stream: agents run in PARALLEL, packages priced with the documented formula
ev = sse(c.post("/api/bff/holidays/stream", json={
    "origin": "Hyderabad", "destination": "Goa", "depart_date": "2026-11-10",
    "travelers": 2, "rooms": 1, "nights": 3}))
kinds = [x["event"] for x in ev]
assert kinds[0] == "start" and kinds[-1] == "done"
starts = {x["name"]: x["start_ms"] for x in ev if x["event"] == "agent" and x["status"] == "running"}
ends = {x["name"]: x["end_ms"] for x in ev if x["event"] == "agent" and x["status"] == "done"}
assert max(starts[k] for k in ("flights", "hotels", "tours")) < min(ends[k] for k in ("flights", "hotels", "tours")), "agents did not overlap"
data = next(x for x in ev if x["event"] == "packages")["data"]
o = data["options"]
for pkg in data["packages"]:
    f, h = o["flights"][pkg["flight_i"]], o["hotels"][pkg["hotel_i"]]
    t = o["tours"][pkg["tour_i"]] if pkg["tour_i"] >= 0 else None
    expect = f["price"] * 2 + h["price"] * 3 * 1 + (t["price"] * 2 if t else 0)
    assert abs(pkg["total_price"] - expect) < 0.02, (pkg, expect)
assert [p["tier"] for p in data["packages"]] == ["Budget", "Comfort", "Premium"]
assert data["packages"][0]["total_price"] < data["packages"][2]["total_price"]
print("8) holiday stream OK: parallel agents, totals =", [round(p["total_price"]) for p in data["packages"]])

# 9) one failing agent must not kill the stream
class Boom(orchestrator.MockToursAdapter):
    async def search(self, intent): raise RuntimeError("tours provider down")
saved = orchestrator.TOUR_ADAPTERS
orchestrator.TOUR_ADAPTERS = [Boom()]
orchestrator.__dict__["TOUR_ADAPTERS"] = orchestrator.TOUR_ADAPTERS
ev = sse(c.post("/api/bff/holidays/stream", json={"origin": "Hyderabad", "destination": "Goa", "depart_date": "2026-11-10"}))
orchestrator.TOUR_ADAPTERS = saved
data = next(x for x in ev if x["event"] == "packages")["data"]
assert data["packages"] and all(p["tour_i"] == -1 for p in data["packages"])
print("9) failed tours agent -> packages still built without a tour")

# 10) old endpoints untouched
assert c.post("/api/bff/holidays/search", json={"origin": "A", "destination": "Goa", "depart_date": "2026-11-10"}).status_code == 200
print("10) existing endpoints still work")
print("\nALL FEATURE TESTS PASSED")
