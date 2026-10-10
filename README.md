# Travel Techie backend — now serving the frontend too

One command runs the whole app: FastAPI BFF, the multi-agent orchestrator,
and index.html itself, all from a single process.

## Run locally

```bash
python3 -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # only needed for the AI Planner tab
uvicorn main:app --reload
```

Then open **http://localhost:8000/** in your browser — that's it. No
separate frontend server, no CORS setup, no second terminal.

## What changed to make this "one file to run"

- `main.py` now serves `static/index.html` at `/`, and every API route
  lives under `/api/*` (`fastapi.staticfiles` + a `FileResponse` route).
- `index.html` already had this logic built in before this backend
  existed:
  ```js
  const API_BASE = (location.port === '8000') ? '/api' : 'http://localhost:8000/api';
  ```
  So the frontend just starts working the moment it's served from the
  same port 8000 process — no frontend changes were needed for the
  wiring itself.
- The Flights, Hotels, Trains, Buses, Cabs, and Smart Route tabs now call
  the real backend (`/api/bff/...`) instead of only generating random
  demo data. If the backend call fails for any reason (not running yet,
  network hiccup), each tab **automatically falls back** to the original
  demo generator — renamed to e.g. `searchFlightsDemo()` — so the page
  never just breaks.
- The AI Planner tab was already wired to `/planner/generate` (now
  `/api/planner/generate`) and needed no changes beyond the path prefix.

## What's real vs mocked

- **Real**: FastAPI app, orchestrator fan-out/fan-in, Smart Route ranking,
  budget-safeguard math, Planner agent (calls the actual Anthropic API),
  and now the full frontend↔backend wiring for every search tab.
- **Mocked**: flight/hotel/transit adapters return randomized sample data.
  Swap the body of each adapter's `search()` method for a real provider
  call (Amadeus, Booking.com, redBus, etc.) — the interface in
  `adapters/base.py` doesn't need to change, and neither does the frontend.

## Structure

```
main.py                  FastAPI app — /api/* routes + serves static/index.html at /
static/index.html        The frontend (now calling the real backend)
agents/orchestrator.py   Fan-out/fan-in across provider agents + Smart Route ranking
agents/planner_agent.py  LLM itinerary generation + critic check
agents/budget_agent.py   Server-side Micro-Budget Safeguard
adapters/                One class per provider, all implementing ProviderAdapter
db/cache.py              Redis-backed cache repository (falls back to in-memory)
models/schemas.py        Pydantic request/response schemas
```

## Known limitation worth knowing about

`/api/bff/trains/search`, `/api/bff/buses/search`, and `/api/bff/cabs/search`
all currently hit the *same* mock transit adapter (which returns one train +
one bus + one cab option per call) — the frontend filters the response down
to the relevant `vertical` for each tab. This is a Phase-1 shortcut; split
`MockTransitAdapter` into three separate adapters when you wire in real
train/bus/cab providers, since each has very different auth and
rate-limiting behavior.

## Next steps

1. Replace mock adapters with real provider calls one vertical at a time.
2. Split the combined transit adapter into train/bus/cab-specific ones.
3. Add PostgreSQL for bookings/users.
4. Add circuit breakers around each adapter's provider call.
5. Move Smart Route / Planner progress to Server-Sent Events so the
   frontend's "CHECKING ROUTES..." board reflects real agent completion.

## What's new since the last version

- Fixed a real bug: the AI Planner was calling an invalid model ID
  (claude-sonnet-4-6), which is why every itinerary generation failed.
  Now calls claude-sonnet-5.
- My Bookings tab: every Book/Select button across Flights, Hotels,
  Trains, Buses, Cabs, Smart Route, and the AI Planner ("Book This Trip")
  now creates a real booking via POST /api/bookings, and the My Bookings
  tab lists them back via GET /api/bookings, with a Cancel action.
  Identity is a random id generated once in the browser and kept in
  localStorage (tt_client_id) - there's no real auth yet, so this is a
  per-browser history, not a per-account one. See db/bookings_store.py.
- Destination showcase: a bento-grid section on the welcome screen with
  auto-scrolling image strips for Dubai and Singapore. This is a CSS
  animation (@keyframes dest-scroll), not actual video - nothing in this
  stack generates video. The photos are real Unsplash CDN images (Unsplash
  License permits hotlinking); swap the img src attributes in
  static/index.html's .dest-showcase block for different destinations.
- UI polish: subtle glass + claymorphism accents on the tab strip
  (.tab-btn.active) and the new bento cards - soft layered box-shadows,
  not a heavy redesign.

## Known limitations to know about

- Bookings and sessions are in-memory only - restarting the server clears
  them. Swap db/bookings_store.py for a real Postgres table when you add
  persistence (see Phase 1 note above).
- "Live booking" here means "creates a real record you can see and
  cancel" - it does not charge a card or hold real inventory. Wiring an
  actual payment/booking confirmation flow requires a real provider
  integration (Amadeus/Booking.com booking APIs, a payment gateway like
  Razorpay/Stripe, and PCI-compliant handling) - a substantially larger
  project than this scaffold, flagged clearly rather than faked.

## What's new (claymorphism + Cabs/Tours/Holidays agents)

- Claymorphism/glass treatment extended across every tab, not just the nav
  bar. Since Hotels, Trains, Buses, Cabs, Tours, Holiday Packages, Smart
  Route, and My Bookings all render through the shared .r-card and
  .search-card classes, one CSS pass (layered box-shadows, a subtle inset
  highlight) now applies everywhere consistently. AI Planner's overview
  card and day cards got the same treatment.
- Cabs now run as their own dedicated agent (adapters/cab_adapter.py),
  split out from the combined train/bus mock, so a real Uber/Ola partner
  API can be wired in without touching train/bus code.
- Tours & Attractions is now backed by a real agent for the first time
  (adapters/tours_adapter.py, standing in for Viator/GetYourGuide) instead
  of being frontend-only demo data.
- Holiday Packages is genuine multi-agent orchestration: the flight,
  hotel, and tour agents run in parallel (agents/orchestrator.py,
  build_holiday_packages), then a packaging step composes them into
  Budget/Comfort/Premium bundles pairing different flight/hotel/tour
  combinations per tier.
- No real Uber/Ola/Viator/GetYourGuide credentials were provided, so all
  of the above stays mock data, same as every other adapter in this
  project. The point of this pass was the orchestration wiring (parallel
  agents, packaging logic, dedicated adapters), which stays the same when
  real credentials go in later.

## What's new (hero background + bookings grand total)

- Hero header now has a scrolling background of India destination photos
  (Taj Mahal, Jaipur, Kerala, Goa, Manali, Varanasi, Ladakh, Udaipur),
  continuously animating left to right behind the title text, at reduced
  opacity with a light scrim so the existing text stays readable. Uses the
  same loremflickr keyword-image pattern already used elsewhere on the
  site (trending destinations grid), consistent with the rest of the app.
- My Bookings now shows a grand total card at the top: total spend across
  all active (non-cancelled) bookings, average per booking, and a
  per-vertical breakdown (flights vs hotels vs holiday packages, etc.).

## New features

**1. Live orchestration** (Holiday Packages + Trip Navigator): the server streams an event each time an
agent starts/finishes (Server-Sent Events). The page draws them as a live panel, then as a timeline so
you can see the flight / hotel / tours agents run in parallel. Code: `stream_holiday_packages()` in
`agents/orchestrator.py`, `plan_trip_events()` in `agents/navigator.py`, `streamPost()` in `static/features.js`.

**2. Live budget tracking** (Holiday Packages): enter a budget and nights; every package shows a meter
(green / amber / red). "Customise" lets you swap flight, stay, tour and nights, and totals + meters
update instantly. Pricing: flight x travelers, hotel x nights x rooms, tour x travelers.

**3. Trip Navigator** tab: pick a destination (Goa, Jaipur, Manali, Kerala, Hyderabad), budget, nights and
travelers -> stay + places that fit -> shortest visiting order per day (exact for <= 8 stops,
nearest-neighbour + 2-opt above) -> road directions from OSRM (falls back to straight-line estimates if
OSRM is unreachable). Transport cost is recomputed from the real distances shown.
*Customise* lets the user choose: stay (or auto by budget), pace (relaxed / balanced / packed), interests,
and must-see places (optionally "only my places"). Picks are never silently ignored: anything that can't
fit is dropped with a note, and an over-budget plan is flagged in red.
**GPS live tracker** uses the browser Geolocation API; reaching within 150 m of a stop ticks it off.
"Simulate trip" replays the route for demos.
Sample data lives in `data/places.py`; add a destination by adding a key there (same shape, nothing else changes).

Environment variables: `ANTHROPIC_API_KEY` (AI Planner only), `OSRM_URL` (optional own OSRM server).
Tests (no internet or key needed): `python tests/test_features.py`

## Accounts, profile, themes

**Login and profile.** Sign up / log in from the header. The Profile page (avatar menu > My Trips) shows
booking history (filter, cancel) and saved plans (details, delete, reopen on the map), plus Settings.
Plans are saved with the "Save to My Trips" button (Trip Navigator and AI Planner results).
Everything lives in one SQLite file, `travel_techie.db`, created next to `main.py` on first run
(set `TT_DB_PATH` to use another location). Bookings, plans and logins survive a server restart.
Passwords are stored as salted PBKDF2 hashes; login tokens are stored hashed; 5 wrong passwords lock
an account for a minute. Code: `db/database.py`, `db/accounts.py`, `db/bookings_store.py`, `account_routes.py`,
`static/account.js`.

**How it plugs into the old page.** The existing code keys bookings by `localStorage.tt_client_id`.
On login, guest bookings are moved into the account and `tt_client_id` becomes the account's id, so the
existing "My Bookings" tab and all Book buttons keep working. Logging out gives the browser a fresh id.

**Dark / light mode.** Toggle in the header; remembered per browser; follows the system setting until
you choose. `static/dark-auto.css` is GENERATED from the page's own CSS by `tools/make_dark_css.py`
(`pip install tinycss2`, then `python tools/make_dark_css.py`). Re-run it if you change colours in
`index.html`, `features.css` or `account.css`. Hand-tuned exceptions live in `static/theme.css`.

**Cursor-following logos.** `static/theme.js`: floating logos turn toward the cursor and the header
logo tilts. Turned off on touch screens and for "reduce motion".

Tests (no internet or API key needed): `python tests/test_features.py` and `python tests/test_accounts.py`
