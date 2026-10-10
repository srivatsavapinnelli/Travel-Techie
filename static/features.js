/*
 * Travel Techie - new features (loaded after the main page script):
 *   1. Live orchestration panel   (agents running in parallel, drawn from a server stream)
 *   2. Holiday Packages: live budget tracking + customise-and-recalculate
 *   3. Trip Navigator tab: budget -> shortest route -> directions, GPS live tracker,
 *      itinerary tracking (auto tick-off when you reach a stop)
 *
 * The main page's own code is untouched except: one extra tab button, one extra
 * panel, two inputs in the Holidays form, and searchHolidays() now tries the live
 * version first and falls back to the original.
 */
(function () {
  'use strict';

  const API = (typeof API_BASE !== 'undefined')
    ? API_BASE
    : ((location.port === '8000') ? '/api' : 'http://localhost:8000/api');

  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inr = (n) => '₹' + Math.round(n).toLocaleString('en-IN');
  const toast = (m) => { if (typeof showToast === 'function') showToast(m); };

  /* =====================================================================
   * Server-Sent-Events over POST. EventSource can't POST, so we read the
   * response body as a stream and split it on blank lines ("\n\n"), which is
   * how SSE separates events. Each event line looks like:  data: {json}
   * ===================================================================== */
  async function streamPost(path, payload, onEvent) {
    const res = await fetch(API + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        if (chunk.startsWith('data: ')) onEvent(JSON.parse(chunk.slice(6)));
      }
    }
  }

  /* =====================================================================
   * 1. LIVE ORCHESTRATION PANEL
   *    Rows = agents. While an agent runs its bar shimmers; when everything
   *    finishes the bars become a timeline (Gantt chart), so overlapping bars
   *    visibly prove the agents ran in parallel.
   * ===================================================================== */
  function createOrchPanel(container, title) {
    const el = document.createElement('div');
    el.className = 'tt-orch';
    el.innerHTML = `
      <div class="tt-orch-head"><b>${esc(title)}</b><span class="tt-orch-live">● LIVE</span><span class="tt-orch-time">0.0s</span></div>
      <div class="tt-orch-rows"></div>`;
    container.appendChild(el);
    const rows = {};
    const t0 = performance.now();
    const timeEl = $('.tt-orch-time', el);
    const liveEl = $('.tt-orch-live', el);
    const timer = setInterval(() => { timeEl.textContent = ((performance.now() - t0) / 1000).toFixed(1) + 's'; }, 100);
    const events = {};

    return {
      el,
      start(agents) {
        const holder = $('.tt-orch-rows', el);
        holder.innerHTML = '';
        agents.forEach((a) => {
          const row = document.createElement('div');
          row.className = 'tt-agent waiting';
          row.innerHTML = `
            <div class="tt-agent-name">${esc(a.icon || '🤖')} ${esc(a.label)}</div>
            <div class="tt-agent-track"><div class="tt-agent-fill"></div><div class="tt-agent-status">waiting</div></div>
            <div class="tt-agent-detail"></div>`;
          holder.appendChild(row);
          rows[a.name] = row;
        });
      },
      update(ev) {
        const row = rows[ev.name];
        if (!row) return;
        events[ev.name] = Object.assign(events[ev.name] || {}, ev);
        row.className = 'tt-agent ' + ev.status;
        const status = $('.tt-agent-status', row);
        if (ev.status === 'running') status.textContent = 'running…';
        if (ev.status === 'done') status.textContent = ((ev.end_ms - ev.start_ms) / 1000).toFixed(2) + 's ✓';
        if (ev.status === 'failed') status.textContent = 'failed';
        if (ev.detail) $('.tt-agent-detail', row).textContent = ev.detail;
      },
      finish(totalMs) {
        clearInterval(timer);
        liveEl.textContent = 'DONE'; liveEl.classList.add('done');
        timeEl.textContent = (totalMs / 1000).toFixed(1) + 's total';
        // Turn the bars into a timeline: left = when it started, width = how long it took.
        Object.keys(events).forEach((name) => {
          const e = events[name];
          if (e.end_ms == null) return;
          const fill = $('.tt-agent-fill', rows[name]);
          fill.style.left = (e.start_ms / totalMs * 100) + '%';
          fill.style.width = Math.max(3, (e.end_ms - e.start_ms) / totalMs * 100) + '%';
        });
      },
      fail(msg) {
        clearInterval(timer);
        liveEl.textContent = 'ERROR'; liveEl.style.background = '#fee2e2';
        timeEl.textContent = msg;
      },
    };
  }

  /* =====================================================================
   * 2. HOLIDAY PACKAGES: live orchestration + live budget tracking
   * ===================================================================== */
  const hol = { data: null, sel: [], from: '', to: '', date: '' };

  const holPrice = (p) => {
    const o = hol.data.options, s = hol.sel[p];
    const f = o.flights[s.f], h = o.hotels[s.h], t = s.t >= 0 ? o.tours[s.t] : null;
    const flight = f.price * hol.data.travelers;
    const stay = h.price * s.nights * hol.data.rooms;
    const tour = t ? t.price * hol.data.travelers : 0;
    return { f, h, t, flight, stay, tour, total: flight + stay + tour };
  };

  const budgetValue = () => Math.max(0, parseFloat(($('#hp-budget') || {}).value) || 0);

  function paintMeter(card, total) {
    const budget = budgetValue();
    const meter = $('.tt-meter', card);
    if (!budget) { meter.style.display = 'none'; return; }
    meter.style.display = '';
    const pct = total / budget * 100;
    meter.classList.toggle('warn', pct > 85 && pct <= 100);
    meter.classList.toggle('over', pct > 100);
    $('.tt-meter-bar span', meter).style.width = Math.min(100, pct) + '%';
    $('.tt-meter-text', meter).textContent = pct > 100
      ? `${inr(total - budget)} over budget (${Math.round(pct)}% of ${inr(budget)})`
      : `${inr(budget - total)} left of ${inr(budget)} (${Math.round(pct)}% used)`;
  }

  function paintPackage(i, flash) {
    const card = $(`.tt-pkg[data-i="${i}"]`);
    if (!card) return;
    const r = holPrice(i), s = hol.sel[i], d = hol.data;
    $('.tt-lines', card).innerHTML = `
      <span>✈️ Flight <span class="tt-muted">${inr(r.f.price)} × ${d.travelers} traveler(s)</span></span><span>${inr(r.flight)}</span>
      <span>🏨 Stay <span class="tt-muted">${inr(r.h.price)} × ${s.nights} night(s) × ${d.rooms} room(s)</span></span><span>${inr(r.stay)}</span>
      <span>🎟️ ${r.t ? esc(r.t.title) : 'No tour'} ${r.t ? `<span class="tt-muted">${inr(r.t.price)} × ${d.travelers}</span>` : ''}</span><span>${inr(r.tour)}</span>`;
    const price = $('.tt-price-live', card);
    price.innerHTML = `${inr(r.total)}<span>total</span>`;
    if (flash) { price.classList.remove('tt-flash'); void price.offsetWidth; price.classList.add('tt-flash'); }
    paintMeter(card, r.total);
    card.dataset.total = r.total;
    paintBudgetSummary();
  }

  function paintBudgetSummary() {
    const box = $('#tt-budget-summary');
    if (!box || !hol.data) return;
    const budget = budgetValue();
    const totals = hol.sel.map((_, i) => holPrice(i).total);
    if (!budget) { box.innerHTML = 'Enter a budget above to track every package against it live.'; return; }
    const fitting = totals.filter((t) => t <= budget).length;
    const cheapest = Math.min(...totals);
    box.innerHTML = `💰 Budget <b>${inr(budget)}</b> · cheapest package <b>${inr(cheapest)}</b> · <b>${fitting}</b> of ${totals.length} packages fit`
      + (fitting === 0 ? ` · <span style="color:#b91c1c">raise the budget by ${inr(cheapest - budget)} or customise a package below</span>` : '');
  }

  function buildPackageCard(pkg, i) {
    const d = hol.data, o = d.options;
    const card = document.createElement('div');
    card.className = 'r-card tt-pkg';
    card.dataset.i = i;
    const opt = (list, fmt, sel) => list.map((x, k) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${esc(fmt(x))}</option>`).join('');
    card.innerHTML = `
      <div class="r-left">
        <div class="r-title">${esc(hol.from)} → ${esc(hol.to)}: ${esc(pkg.tier)} Package</div>
        <div class="r-sub">${d.travelers} traveler(s) · ${d.rooms} room(s) · departs ${esc(hol.date)}</div>
        <div class="tt-lines"></div>
        <div class="tt-meter"><div class="tt-meter-bar"><span></span></div><div class="tt-meter-text"></div></div>
        <details class="tt-custom">
          <summary>Customise &amp; watch the budget update</summary>
          <div class="tt-custom-grid">
            <label>Flight</label><select data-k="f">${opt(o.flights, (x) => `${x.title} · ${inr(x.price)}/person`, pkg.flight_i)}</select>
            <label>Stay</label><select data-k="h">${opt(o.hotels, (x) => `${(x.raw && x.raw.type) || x.title} · ${inr(x.price)}/night`, pkg.hotel_i)}</select>
            <label>Tour</label><select data-k="t"><option value="-1" ${pkg.tour_i < 0 ? 'selected' : ''}>No tour</option>${opt(o.tours, (x) => `${x.title} · ${inr(x.price)}/person`, pkg.tour_i)}</select>
            <label>Nights</label><input data-k="nights" type="number" min="1" max="14" value="${d.nights}">
          </div>
        </details>
      </div>
      <div class="r-right">
        <div class="r-price tt-price-live"></div>
        <button class="r-btn" data-act="book">Book Package</button>
      </div>`;

    $$('[data-k]', card).forEach((ctl) => ctl.addEventListener('input', () => {
      const s = hol.sel[i], k = ctl.dataset.k;
      if (k === 'nights') s.nights = Math.max(1, Math.min(14, parseInt(ctl.value, 10) || 1));
      else s[k] = parseInt(ctl.value, 10);
      paintPackage(i, true);
    }));
    $('[data-act="book"]', card).addEventListener('click', () => {
      const r = holPrice(i), s = hol.sel[i];
      const subtitle = `${hol.from} → ${hol.to} · ${s.nights} night(s) · ${(r.h.raw && r.h.raw.type) || r.h.title}${r.t ? ' · ' + r.t.title : ''}`;
      if (typeof bookPackage === 'function') bookPackage(pkg.tier, Math.round(r.total), subtitle);
    });
    return card;
  }

  window.ttHolidayBudgetChanged = function () {
    if (!hol.data) return;
    hol.sel.forEach((_, i) => paintPackage(i, false));
  };

  /** Returns true when it handled the search; false means "use the classic version". */
  window.ttSearchHolidaysLive = async function () {
    if (typeof holidayPaxCounts === 'undefined') return false;
    const from = $('#hp-from').value, to = $('#hp-to').value, date = $('#hp-date').value;
    const rooms = holidayPaxCounts.rooms;
    const guests = (holidayPaxCounts.adults + holidayPaxCounts.children) || 1;
    if (from === to) { toast("From and To cities can't be the same"); return true; }
    const nights = Math.max(1, Math.min(14, parseInt(($('#hp-nights') || {}).value, 10) || 3));

    const block = $('#resultsBlock'), area = $('#resultsArea');
    $('#resultsTitle').textContent = 'Holiday Packages';
    $('#resultsSub').textContent = `${from} → ${to} · Departure: ${date} · ${rooms} Room(s), ${guests} Guest(s), ${nights} night(s)`;
    area.innerHTML = '';
    block.classList.add('show');
    block.scrollIntoView({ behavior: 'smooth' });

    const orch = createOrchPanel(area, 'Live orchestration: agents working in parallel');
    const out = document.createElement('div');
    area.appendChild(out);

    let ok = false;
    try {
      await streamPost('/bff/holidays/stream', {
        origin: from, destination: to, depart_date: date, travelers: guests, rooms, nights, priority: 'balanced',
      }, (ev) => {
        if (ev.event === 'start') orch.start(ev.agents);
        else if (ev.event === 'agent') orch.update(ev);
        else if (ev.event === 'done') orch.finish(ev.total_ms);
        else if (ev.event === 'error') throw new Error(ev.detail);
        else if (ev.event === 'packages') {
          hol.data = ev.data; hol.from = from; hol.to = to; hol.date = date;
          hol.sel = ev.data.packages.map((p) => ({ f: p.flight_i, h: p.hotel_i, t: p.tour_i, nights: ev.data.nights }));
          out.innerHTML = '<div class="tt-budget-summary" id="tt-budget-summary"></div>';
          if (!ev.data.packages.length) { out.innerHTML += '<p style="color:var(--muted)">No packages could be built right now.</p>'; return; }
          ev.data.packages.forEach((p, i) => out.appendChild(buildPackageCard(p, i)));
          ev.data.packages.forEach((_, i) => paintPackage(i, false));
          ok = true;
        }
      });
    } catch (e) {
      orch.fail('failed');
      if (!ok) { area.innerHTML = ''; return false; }   // nothing shown yet -> let the classic search run
      toast('Live stream interrupted: ' + e.message);
    }
    return ok;
  };

  /* =====================================================================
   * 3. TRIP NAVIGATOR
   * ===================================================================== */
  const ARRIVE_RADIUS_M = 150;
  const DEFAULT_CENTER = [22.5, 79.0];   // middle of India, until a destination is chosen
  const CAT_ICON = { beach: '🏖️', heritage: '🏛️', adventure: '🪂', culture: '🎭', nature: '🌿', cruise: '⛴️', viewpoint: '🌄',
    religious: '🛕', shopping: '🛍️', food: '🍛' };

  const nav = {
    map: null, plan: null, day: 0, visited: new Set(),
    routeLayer: null, markerLayer: null, meMarker: null, meCircle: null, trail: null,
    watchId: null, simTimer: null, pos: null, prevPos: null, follow: true, mode: 'idle',
    dests: [], info: null, picked: new Set(), interests: new Set(),   // customise-panel state
  };

  try { JSON.parse(localStorage.getItem('tt_nav_visited') || '[]').forEach((k) => nav.visited.add(k)); } catch (e) { /* ignore */ }
  const saveVisited = () => { try { localStorage.setItem('tt_nav_visited', JSON.stringify(Array.from(nav.visited))); } catch (e) { /* ignore */ } };
  const vkey = (stop) => `${nav.plan.destination}|${nav.plan.nights}|${stop.id}`;

  /* ---------- geometry helpers ---------- */
  function haversineM(a, b) {
    const R = 6371000, rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  /** Shortest distance (metres) from point p to the segment a-b (flat-earth approximation, fine at city scale). */
  function segDistM(p, a, b) {
    const k = Math.cos(a.lat * Math.PI / 180);
    const xy = (q) => [q.lng * 111320 * k, q.lat * 110540];
    const [px, py] = xy(p), [ax, ay] = xy(a), [bx, by] = xy(b);
    const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
    let t = l2 ? ((px - ax) * dx + (py - ay) * dy) / l2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
  }
  const bearingName = (a, b) => {
    const y = Math.sin((b.lng - a.lng) * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180);
    const x = Math.cos(a.lat * Math.PI / 180) * Math.sin(b.lat * Math.PI / 180) - Math.sin(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180) * Math.cos((b.lng - a.lng) * Math.PI / 180);
    const deg = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    return ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(deg / 45) % 8];
  };
  const fmtKm = (m) => (m >= 1000 ? (m / 1000).toFixed(1) + ' km' : Math.round(m) + ' m');
  const dayTitle = (day) => {
    const c = {};
    day.stops.forEach((s) => { c[s.region] = (c[s.region] || 0) + 1; });
    const top = Object.keys(c).sort((a, b) => c[b] - c[a])[0];
    return top ? ((nav.plan.region_labels || {})[top] || top) : 'Free day';
  };

  /* ---------- UI skeleton ---------- */
  function buildNavigatorUI() {
    const root = $('#nav-root');
    if (!root || root.dataset.ready) return;
    root.dataset.ready = '1';
    root.innerHTML = `
      <div class="ai-intro"><b>Plan by budget, get the shortest route.</b> Choose a destination and budget and the planner picks a stay and the best places that fit, finds the <b>shortest visiting order</b> for each day and gives road directions. Want control? Open <b>Customise</b> to pick your own stay, pace, interests and must-see places. Then turn on <b>live GPS</b> and stops tick off as you arrive. <i id="nav-dest-note">Sample data.</i></div>
      <div class="form-grid">
        <div class="f-field"><label>Destination</label><select id="nav-dest"><option>Loading…</option></select><div class="tt-note" id="nav-tagline"></div></div>
        <div class="f-field"><label>Total budget (₹)</label><input type="number" id="nav-budget" value="50000" min="5000" step="1000">
          <div class="tt-chips">${[30000, 50000, 80000, 120000].map((b) => `<button type="button" class="tt-chip" data-b="${b}">${inr(b)}</button>`).join('')}</div></div>
        <div class="f-field"><label>Nights</label><input type="number" id="nav-nights" value="3" min="1" max="7"></div>
        <div class="f-field"><label>Travelers</label><input type="number" id="nav-trav" value="2" min="1" max="10"></div>
      </div>
      <details class="tt-card tt-custom-panel" id="nav-custom" style="margin-top:14px">
        <summary>⚙️ Customise your trip <span class="tt-muted" id="nav-custom-sum">(optional: stay, pace, interests, places)</span></summary>
        <div class="tt-opt-grid">
          <div class="f-field"><label>Stay</label><select id="nav-stay"><option value="">Auto: best for my budget</option></select></div>
          <div class="f-field"><label>Pace</label>
            <select id="nav-pace"><option value="relaxed">Relaxed (3 stops a day)</option><option value="balanced" selected>Balanced (4 stops a day)</option><option value="packed">Packed (5 stops a day)</option></select></div>
        </div>
        <label class="tt-sublabel">Interests <span class="tt-muted">(the planner favours these when filling your days)</span></label>
        <div class="tt-chips" id="nav-interests"></div>
        <label class="tt-sublabel">Must-see places <span class="tt-muted">(<b id="nav-picked">0</b> selected: these always go in the plan if they fit)</span></label>
        <div id="nav-places" class="tt-places"></div>
        <div class="tt-btnrow">
          <label class="tt-check"><input type="checkbox" id="nav-only"> Only my places, don't add suggestions</label>
          <button type="button" class="tt-btn" id="nav-clear">Clear selection</button>
        </div>
      </details>
      <div class="search-btn-wrap"><button class="search-btn" id="nav-go">🧭 Plan my trip</button></div>
      <div id="nav-orch" style="margin-top:16px"></div>
      <div id="nav-summary"></div>
      <div class="tt-nav-grid">
        <div>
          <div id="nav-map"></div>
          <div class="tt-note" style="margin-top:6px">Map data © OpenStreetMap contributors. Needs internet for map tiles.</div>
        </div>
        <div>
          <div class="tt-card" id="nav-gps">
            <h4>📡 GPS live tracker</h4>
            <div class="tt-btnrow">
              <button class="tt-btn primary" id="gps-start">Start live GPS</button>
              <button class="tt-btn" id="gps-sim">▶ Simulate trip</button>
              <button class="tt-btn danger" id="gps-stop" disabled>Stop</button>
            </div>
            <label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="gps-follow" checked> Keep map centred on me</label>
            <div class="tt-gps-status" id="gps-status" style="margin-top:8px">GPS is off. "Simulate trip" replays the day's route so you can demo without being at the destination.</div>
            <div id="gps-next"></div>
          </div>
          <div class="tt-card" id="nav-itin"><h4>🗒️ Itinerary</h4><div class="tt-note">Plan a trip to see your day-by-day itinerary here.</div></div>
          <div class="tt-card" id="nav-dirs" style="display:none"><h4>🛣️ Directions</h4><div id="nav-dirs-body"></div></div>
        </div>
      </div>`;

    $$('.tt-chip[data-b]', root).forEach((c) => c.addEventListener('click', () => {
      $('#nav-budget').value = c.dataset.b;
      $$('.tt-chip[data-b]', root).forEach((x) => x.classList.toggle('on', x === c));
    }));
    $('#nav-go').addEventListener('click', planTrip);
    $('#nav-dest').addEventListener('change', () => loadDestination($('#nav-dest').value));
    $('#nav-clear').addEventListener('click', () => { nav.picked.clear(); nav.interests.clear(); renderCustomise(); });
    $('#gps-start').addEventListener('click', startLiveGps);
    $('#gps-sim').addEventListener('click', startSimulation);
    $('#gps-stop').addEventListener('click', () => stopTracking('Tracking stopped.'));
    $('#gps-follow').addEventListener('change', (e) => { nav.follow = e.target.checked; });
    initMap();
    nav.ready = loadDestinations();   // awaited by loadSaved()
  }

  /* ---------- destinations + customise panel ---------- */
  async function loadDestinations() {
    try {
      const res = await fetch(API + '/bff/navigator/destinations');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      nav.dests = (await res.json()).destinations;
      $('#nav-dest').innerHTML = nav.dests.map((d) => `<option value="${esc(d.name)}">${esc(d.name)}</option>`).join('');
      $('#nav-dest-note').textContent = 'Sample data for ' + nav.dests.map((d) => d.name).join(', ') + '.';
      await loadDestination(nav.dests[0].name);
    } catch (e) {
      $('#nav-dest').innerHTML = '<option>Unavailable</option>';
      toast('Could not load destinations: ' + e.message);
    }
  }

  async function loadDestination(name) {
    try {
      const res = await fetch(`${API}/bff/navigator/places?destination=${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      nav.info = await res.json();
    } catch (e) { toast('Could not load places: ' + e.message); return; }
    nav.picked.clear(); nav.interests.clear();
    stopTracking();
    // a plan for the previous destination no longer matches the map, so clear it
    nav.plan = null; nav.day = 0;
    $('#nav-summary').innerHTML = '';
    $('#nav-orch').innerHTML = '';
    $('#nav-itin').innerHTML = '<h4>🗒️ Itinerary</h4><div class="tt-note">Plan a trip to see your day-by-day itinerary here.</div>';
    $('#nav-dirs').style.display = 'none';
    $('#gps-next').innerHTML = '';
    $('#nav-tagline').textContent = nav.info.tagline;
    if (nav.map) {
      nav.routeLayer.clearLayers(); nav.markerLayer.clearLayers();
      nav.map.setView(nav.info.center, 11);
      showPlacePins();
    }
    renderCustomise();
  }

  /** Light pins for every place of the chosen destination so you can see the options before planning. */
  function showPlacePins() {
    if (!nav.map || !nav.info) return;
    nav.markerLayer.clearLayers();
    nav.info.places.forEach((p) => {
      const on = nav.picked.has(p.id);
      L.circleMarker([p.lat, p.lng], { radius: on ? 8 : 5, color: on ? '#0d9488' : '#64748b', weight: on ? 3 : 1, fillColor: on ? '#5eead4' : '#cbd5e1', fillOpacity: 0.9 })
        .bindTooltip(esc(p.name)).addTo(nav.markerLayer);
    });
  }

  function renderCustomise() {
    const info = nav.info;
    if (!info) return;
    $('#nav-stay').innerHTML = '<option value="">Auto: best for my budget</option>' + info.stays.map((s) =>
      `<option value="${esc(s.id)}">${esc(s.label)} · ${inr(s.price_per_night)}/night · ★ ${s.rating}</option>`).join('');
    $('#nav-interests').innerHTML = info.categories.map((c) =>
      `<button type="button" class="tt-chip ${nav.interests.has(c) ? 'on' : ''}" data-c="${esc(c)}">${CAT_ICON[c] || '📍'} ${esc(c)}</button>`).join('');
    $$('#nav-interests .tt-chip').forEach((b) => b.addEventListener('click', () => {
      if (nav.interests.has(b.dataset.c)) nav.interests.delete(b.dataset.c); else nav.interests.add(b.dataset.c);
      b.classList.toggle('on'); updateCustomSummary();
    }));

    const byRegion = {};
    info.places.forEach((p) => { (byRegion[p.region] = byRegion[p.region] || []).push(p); });
    $('#nav-places').innerHTML = Object.keys(byRegion).map((r) => `
      <div class="tt-region"><div class="tt-region-h">${esc(info.region_labels[r] || r)}</div>
        ${byRegion[r].sort((a, b) => b.rating - a.rating).map((p) => `
          <label class="tt-place"><input type="checkbox" data-p="${esc(p.id)}" ${nav.picked.has(p.id) ? 'checked' : ''}>
            <span class="pn">${CAT_ICON[p.category] || '📍'} ${esc(p.name)}</span>
            <span class="pm">${p.cost ? inr(p.cost) + ' pp' : 'Free'} · ${p.visit_min >= 60 ? (p.visit_min / 60).toFixed(p.visit_min % 60 ? 1 : 0) + ' h' : p.visit_min + ' min'} · ★ ${p.rating}</span>
          </label>`).join('')}
      </div>`).join('');
    $$('#nav-places input').forEach((cb) => cb.addEventListener('change', () => {
      if (cb.checked) nav.picked.add(cb.dataset.p); else nav.picked.delete(cb.dataset.p);
      updateCustomSummary(); showPlacePins();
    }));
    $('#nav-only').checked = false;
    updateCustomSummary();
  }

  function updateCustomSummary() {
    $('#nav-picked').textContent = nav.picked.size;
    const bits = [];
    if (nav.picked.size) bits.push(nav.picked.size + ' place(s)');
    if (nav.interests.size) bits.push(Array.from(nav.interests).join(', '));
    $('#nav-custom-sum').textContent = bits.length ? '(' + bits.join(' · ') + ')' : '(optional: stay, pace, interests, places)';
  }

  function initMap() {
    const el = $('#nav-map');
    if (typeof L === 'undefined') {
      el.innerHTML = '<div class="tt-gps-status err" style="margin:20px">The map library failed to load. Lists and directions still work.</div>';
      return;
    }
    nav.map = L.map(el).setView(DEFAULT_CENTER, 5);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(nav.map);
    nav.routeLayer = L.layerGroup().addTo(nav.map);
    nav.markerLayer = L.layerGroup().addTo(nav.map);
  }

  /* ---------- planning (streamed, shows the agents live) ---------- */
  async function planTrip() {
    const btn = $('#nav-go');
    const payload = {
      destination: $('#nav-dest').value,
      budget: parseFloat($('#nav-budget').value) || 0,
      nights: parseInt($('#nav-nights').value, 10) || 3,
      travelers: parseInt($('#nav-trav').value, 10) || 2,
      must_ids: Array.from(nav.picked),
      stay_id: $('#nav-stay').value || null,
      interests: Array.from(nav.interests),
      pace: $('#nav-pace').value,
      only_mine: $('#nav-only').checked,
    };
    if (payload.budget < 5000) { toast('Please enter a budget of at least ₹5,000'); return; }
    stopTracking();
    btn.disabled = true; btn.textContent = 'Planning…';
    const holder = $('#nav-orch');
    holder.innerHTML = '';
    const orch = createOrchPanel(holder, 'Live orchestration: planning agents');
    let plan = null;
    try {
      await streamPost('/bff/navigator/plan/stream', payload, (ev) => {
        if (ev.event === 'start') orch.start(ev.agents);
        else if (ev.event === 'agent') orch.update(ev);
        else if (ev.event === 'plan') plan = ev.data;
        else if (ev.event === 'done') orch.finish(ev.total_ms);
        else if (ev.event === 'error') throw new Error(ev.detail);
      });
      if (!plan) throw new Error('No plan was returned');
      nav.plan = plan; nav.day = 0;
      renderSummary(); renderDay();
    } catch (e) {
      orch.fail('failed');
      toast('Could not plan: ' + e.message);
    } finally {
      btn.disabled = false; btn.textContent = '🧭 Plan my trip';
    }
  }

  function renderSummary() {
    const p = nav.plan, b = p.breakdown;
    const parts = [
      ['Stay', b.stay, '#0d9488'], ['Food', b.food, '#f59e0b'], ['Activities', b.activities, '#8b5cf6'],
      ['Local transport', b.local_transport, '#3b82f6'], ['Buffer (10%)', b.buffer, '#94a3b8'], ['Unspent', Math.max(0, b.unspent), '#e2e8f0'],
    ];
    const sum = parts.reduce((s, x) => s + x[1], 0) || 1;
    $('#nav-summary').innerHTML = `
      <div class="tt-card" style="margin-top:16px">
        <h4>💰 ${esc(p.destination)} · budget ${inr(p.budget)} · ${p.nights} night(s) · ${p.travelers} traveler(s)
          <span class="tt-badge ${p.routing_source === 'osrm' ? 'ok' : 'est'}">${p.routing_source === 'osrm' ? 'Road directions (OSRM)' : 'Estimated routes (OSRM unreachable)'}</span></h4>
        <div class="tt-split">${parts.map((x) => `<i style="width:${x[1] / sum * 100}%;background:${x[2]}" title="${x[0]} ${inr(x[1])}"></i>`).join('')}</div>
        <div class="tt-legend">${parts.map((x) => `<span style="--c:${x[2]}">${x[0]} ${inr(x[1])}</span>`).join('')}</div>
        <div class="tt-note" style="margin-top:8px">🏨 <b>${esc(p.stay.label)}</b> · ${inr(p.stay.price_per_night)}/night × ${p.nights} night(s) × ${p.rooms} room(s)</div>
        ${p.over_budget ? `<div class="tt-banner">⚠️ This plan is over your budget by ${inr(-b.unspent)} (counting the 10% buffer).</div>` : ''}
        ${(p.notes || []).map((n) => `<div class="tt-note">${/over budget/i.test(n) ? '⚠️' : '💡'} ${esc(n)}</div>`).join('')}
        <div class="tt-note">Transport is priced from ${b.total_km} km of ${p.routing_source === 'osrm' ? 'real road' : 'estimated'} distance. ${esc(p.note)}</div>
        <div class="tt-btnrow"><button type="button" class="tt-btn primary" id="nav-save">💾 Save to My Trips</button></div>
      </div>`;
    $('#nav-save').addEventListener('click', async (e) => {
      if (!window.ttAccount) { toast('Accounts are not available'); return; }
      const btn = e.currentTarget;
      const ok = await window.ttAccount.savePlan('navigator', `${p.destination} · ${p.nights} night(s) · ${inr(p.budget)}`, p.destination, thinPlan(p));
      if (ok) { btn.textContent = '✓ Saved to My Trips'; btn.disabled = true; }
    });
  }

  const activeDay = () => nav.plan.days[nav.day];
  const hotelPt = () => ({ lat: nav.plan.stay.lat, lng: nav.plan.stay.lng });

  function renderDay() {
    if (!nav.plan) return;
    stopTracking();
    const p = nav.plan, d = activeDay();
    // itinerary card
    const tabs = p.days.map((x, i) => `<button class="tt-tab ${i === nav.day ? 'on' : ''}" data-d="${i}">Day ${x.day} · ${esc(dayTitle(x))}</button>`).join('');
    let legIdx = 0;
    const stopsHtml = d.stops.map((s, i) => {
      const leg = d.route.legs[legIdx++];
      const done = nav.visited.has(vkey(s));
      return `<div class="tt-stop ${done ? 'visited' : ''}" data-id="${esc(s.id)}">
        <input type="checkbox" ${done ? 'checked' : ''} aria-label="Mark ${esc(s.name)} visited">
        <div><div class="n">${i + 1}. ${esc(s.name)} ${s.selected ? '<span class="tt-badge ok" title="You picked this place">⭐ your pick</span>' : ''}</div></div>
        <a href="https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}" target="_blank" rel="noopener">Open in Maps ↗</a>
        ${leg ? `<div class="tt-leg">${leg.distance_km} km · ${leg.duration_min} min from ${i === 0 ? 'hotel' : esc(d.stops[i - 1].name)}</div>` : ''}
        <div class="m">${s.cost ? inr(s.cost) + '/person' : 'Free'} · ~${s.visit_min} min · ★ ${s.rating}</div>
      </div>`;
    }).join('');
    const back = d.route.legs[d.route.legs.length - 1];
    $('#nav-itin').innerHTML = `
      <h4>🗒️ Itinerary</h4>
      <div class="tt-tabs">${tabs}</div>
      ${d.stops.length ? `
        <div class="tt-note">🏨 Start: <b>${esc(p.stay.label)}</b></div>
        <div class="tt-progress"><span></span></div><div class="tt-note" id="nav-progress-text"></div>
        ${stopsHtml}
        ${back ? `<div class="tt-note">↩️ Back to hotel: ${back.distance_km} km · ${back.duration_min} min</div>` : ''}
        <div class="tt-note"><b>Day total:</b> ${d.route.distance_km} km driving · about ${d.total_hours} h including visits</div>`
      : '<div class="tt-note">Nothing planned for this day. A free day!</div>'}`;
    $$('.tt-tab', $('#nav-itin')).forEach((t) => t.addEventListener('click', () => { nav.day = +t.dataset.d; renderDay(); }));
    $$('.tt-stop input', $('#nav-itin')).forEach((cb) => cb.addEventListener('change', () => {
      const stop = d.stops.find((s) => s.id === cb.closest('.tt-stop').dataset.id);
      setVisited(stop, cb.checked, false);
    }));

    // directions card
    const dirs = $('#nav-dirs');
    dirs.style.display = d.route.legs.length ? '' : 'none';
    $('#nav-dirs-body').innerHTML = d.route.legs.map((leg, i) => `
      <details class="tt-dir" ${i === 0 ? 'open' : ''}>
        <summary>${esc(leg.from)} → ${esc(leg.to)} <span style="color:var(--muted);font-weight:400">· ${leg.distance_km} km · ${leg.duration_min} min</span></summary>
        <ol>${leg.steps.map((s) => `<li>${esc(s.instruction)} ${s.distance_m ? `<span>(${fmtKm(s.distance_m)})</span>` : ''}</li>`).join('')}</ol>
      </details>`).join('');

    drawMap();
    updateProgress();
    updateNext();
  }

  function drawMap() {
    if (!nav.map || !nav.plan) return;
    const d = activeDay();
    nav.routeLayer.clearLayers(); nav.markerLayer.clearLayers();
    const hotel = L.marker([nav.plan.stay.lat, nav.plan.stay.lng], {
      icon: L.divIcon({ className: '', html: '<div class="tt-pin hotel"><span>🏨</span></div>', iconSize: [28, 28], iconAnchor: [14, 26] }),
    }).bindPopup(`<b>${esc(nav.plan.stay.label)}</b><br>Your stay`);
    nav.markerLayer.addLayer(hotel);
    const pts = [[nav.plan.stay.lat, nav.plan.stay.lng]];
    d.stops.forEach((s, i) => {
      const done = nav.visited.has(vkey(s));
      nav.markerLayer.addLayer(L.marker([s.lat, s.lng], {
        icon: L.divIcon({ className: '', html: `<div class="tt-pin ${done ? 'visited' : ''}"><span>${done ? '✓' : i + 1}</span></div>`, iconSize: [28, 28], iconAnchor: [14, 26] }),
      }).bindPopup(`<b>${i + 1}. ${esc(s.name)}</b><br>${s.cost ? inr(s.cost) + '/person' : 'Free'} · ~${s.visit_min} min`));
      pts.push([s.lat, s.lng]);
    });
    if (d.route.geometry.length) {
      L.polyline(d.route.geometry, { color: '#0d9488', weight: 5, opacity: 0.85, dashArray: d.route.source === 'estimate' ? '8 8' : null }).addTo(nav.routeLayer);
    }
    nav.map.invalidateSize();
    nav.map.fitBounds(L.latLngBounds(pts).pad(0.15));
  }

  /** Saved plans are capped at 200 KB, and OSRM geometry can be thousands of points per day.
   *  Keep every Nth point (always the first and last) so the route still draws smoothly. */
  function thinPlan(plan) {
    const copy = JSON.parse(JSON.stringify(plan));
    copy.days.forEach((d) => {
      const g = d.route.geometry, MAX = 150;
      if (g.length > MAX) {
        const step = (g.length - 1) / (MAX - 1);
        d.route.geometry = Array.from({ length: MAX }, (_, i) => g[Math.round(i * step)]);
      }
    });
    return copy;
  }

  /** Re-open a saved plan on the map without asking the server to plan again. */
  async function loadSaved(plan) {
    buildNavigatorUI();
    if (nav.ready) await nav.ready;
    const sel = $('#nav-dest');
    if (sel) sel.value = plan.destination;
    await loadDestination(plan.destination);          // resets the form state and shows the place pins
    $('#nav-budget').value = plan.budget; $('#nav-nights').value = plan.nights; $('#nav-trav').value = plan.travelers;
    $('#nav-pace').value = plan.pace || 'balanced';
    (plan.interests || []).forEach((i) => nav.interests.add(i));
    plan.days.forEach((d) => d.stops.forEach((s) => { if (s.selected) nav.picked.add(s.id); }));
    renderCustomise();
    $('#nav-pace').value = plan.pace || 'balanced';
    nav.plan = plan; nav.day = 0;
    renderSummary(); renderDay();
    toast('Saved plan loaded');
  }

  /* ---------- itinerary tracking ---------- */
  function setVisited(stop, on, byGps) {
    const k = vkey(stop);
    if (on) nav.visited.add(k); else nav.visited.delete(k);
    saveVisited();
    const row = $(`.tt-stop[data-id="${stop.id}"]`);
    if (row) { row.classList.toggle('visited', on); $('input', row).checked = on; }
    if (on && byGps) toast(`Arrived at ${stop.name} ✓`);
    drawMap(); updateProgress(); updateNext();
  }

  function updateProgress() {
    if (!nav.plan) return;
    const d = activeDay(), txt = $('#nav-progress-text');
    if (!txt || !d.stops.length) return;
    const done = d.stops.filter((s) => nav.visited.has(vkey(s))).length;
    // distance still to drive: legs that lead to a stop not yet visited, plus the way home
    let left = 0;
    d.route.legs.forEach((leg, i) => { if (i >= d.stops.length || !nav.visited.has(vkey(d.stops[i]))) left += leg.distance_km; });
    $('.tt-progress span', $('#nav-itin')).style.width = (done / d.stops.length * 100) + '%';
    txt.textContent = `${done} of ${d.stops.length} stops visited · about ${left.toFixed(1)} km of driving left`;
  }

  function updateNext() {
    const box = $('#gps-next');
    if (!box) return;
    if (!nav.plan) { box.innerHTML = ''; return; }
    const d = activeDay();
    const next = d.stops.find((s) => !nav.visited.has(vkey(s)));
    if (!d.stops.length) { box.innerHTML = ''; return; }
    const target = next || hotelPt();
    const label = next ? next.name : 'your hotel';
    if (!nav.pos) { box.innerHTML = `<div class="tt-next">Next up: <b>${esc(label)}</b></div>`; return; }
    const m = haversineM(nav.pos, target);
    const mins = Math.max(1, Math.round(m * 1.3 / 1000 / 30 * 60));   // road factor 1.3, ~30 km/h
    box.innerHTML = `<div class="tt-next">${next ? 'Next stop' : 'All stops done 🎉 Head back to'}: <b>${esc(label)}</b><br>
      ${fmtKm(m)} away to the ${bearingName(nav.pos, target)} · about ${mins} min</div>`;
  }

  /* ---------- GPS tracking (live + simulated share the same handler) ---------- */
  function setStatus(text, cls) {
    const el = $('#gps-status');
    el.className = 'tt-gps-status ' + (cls || '');
    el.innerHTML = text;
  }

  function onPosition(p) {
    nav.prevPos = nav.pos; nav.pos = p;
    if (nav.map) {
      const ll = [p.lat, p.lng];
      if (!nav.meMarker) {
        nav.meMarker = L.marker(ll, { icon: L.divIcon({ className: '', html: '<div class="tt-me"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), zIndexOffset: 1000 }).addTo(nav.map);
        nav.meCircle = L.circle(ll, { radius: p.accuracy || 20, color: '#2563eb', weight: 1, fillOpacity: 0.08 }).addTo(nav.map);
        nav.trail = L.polyline([ll], { color: '#2563eb', weight: 3, opacity: 0.7 }).addTo(nav.map);
      } else {
        nav.meMarker.setLatLng(ll); nav.meCircle.setLatLng(ll).setRadius(p.accuracy || 20); nav.trail.addLatLng(ll);
      }
      if (nav.follow) nav.map.panTo(ll, { animate: true });
    }
    const speed = p.speed != null && !isNaN(p.speed) ? ` · ${(p.speed * 3.6).toFixed(0)} km/h` : '';
    const when = new Date(p.ts || Date.now()).toLocaleTimeString();
    const tag = nav.mode === 'sim' ? 'Simulated GPS' : 'Live GPS';
    let msg = `<b>${tag}</b> · ±${Math.round(p.accuracy || 0)} m${speed} · ${when}`;
    let cls = 'live';
    if (nav.mode === 'live' && nav.plan) {
      const km = haversineM(p, hotelPt()) / 1000;
      if (km > 100) { msg += `<br>You are about ${Math.round(km)} km from ${esc(nav.plan.destination)}, so stops won't tick off from here. Use <b>Simulate trip</b> to demo.`; cls = 'warn'; }
    }
    setStatus(msg, cls);
    checkArrivals();
    updateNext();
  }

  /** A stop counts as reached when we come within 150 m of it. We test the path segment between the previous
   *  and the current fix, so a fast move that "jumps over" a stop between two fixes still counts. */
  function checkArrivals() {
    if (!nav.plan || !nav.pos || (nav.pos.accuracy || 0) > 250) return;
    nav.plan.days.forEach((day) => day.stops.forEach((s) => {
      if (nav.visited.has(vkey(s))) return;
      const d = nav.prevPos ? segDistM(s, nav.prevPos, nav.pos) : haversineM(s, nav.pos);
      if (d <= ARRIVE_RADIUS_M) {
        setVisited(s, true, true);
      }
    }));
  }

  function startLiveGps() {
    if (!navigator.geolocation) { setStatus('This browser has no geolocation support.', 'err'); return; }
    stopTracking();
    nav.mode = 'live';
    setStatus('Asking for your location… allow it in the browser prompt.', 'warn');
    setButtons(true);
    nav.watchId = navigator.geolocation.watchPosition(
      (pos) => onPosition({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, speed: pos.coords.speed, ts: pos.timestamp }),
      (err) => {
        const why = { 1: 'Location permission was denied. Allow location for this site in the browser settings and try again.',
          2: 'Your position is unavailable right now (no GPS or network location).', 3: 'Timed out waiting for a GPS fix.' }[err.code] || err.message;
        stopTracking(); setStatus(why, 'err');
      },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 },
    );
  }

  function startSimulation() {
    if (!nav.plan) { setStatus('Plan a trip first, then simulate it.', 'warn'); return; }
    const geo = activeDay().route.geometry;
    if (geo.length < 2) { setStatus('This day has no route to simulate.', 'warn'); return; }
    stopTracking();
    nav.mode = 'sim';
    setButtons(true);
    // cumulative length along the route polyline
    const pts = geo.map((g) => ({ lat: g[0], lng: g[1] }));
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + haversineM(pts[i - 1], pts[i]));
    const total = cum[cum.length - 1];
    const TICKS = 240, DT = 150;   // whole day replays in ~36 seconds
    let dist = 0, seg = 1;
    nav.simTimer = setInterval(() => {
      dist = Math.min(total, dist + total / TICKS);
      while (seg < cum.length - 1 && cum[seg] < dist) seg++;
      const f = (dist - cum[seg - 1]) / ((cum[seg] - cum[seg - 1]) || 1);
      const a = pts[seg - 1], b = pts[seg];
      onPosition({ lat: a.lat + (b.lat - a.lat) * f, lng: a.lng + (b.lng - a.lng) * f, accuracy: 5, speed: (total / TICKS) / (DT / 1000), ts: Date.now() });
      if (dist >= total) stopTracking('Simulation finished: you are back at the hotel.');
    }, DT);
  }

  function stopTracking(message) {
    if (nav.watchId != null) { navigator.geolocation.clearWatch(nav.watchId); nav.watchId = null; }
    if (nav.simTimer) { clearInterval(nav.simTimer); nav.simTimer = null; }
    const was = nav.mode;
    nav.mode = 'idle';
    if (nav.map && nav.meMarker) { nav.map.removeLayer(nav.meMarker); nav.map.removeLayer(nav.meCircle); nav.map.removeLayer(nav.trail); nav.meMarker = nav.meCircle = nav.trail = null; }
    nav.pos = nav.prevPos = null;
    if ($('#gps-stop')) setButtons(false);
    if (message && $('#gps-status')) setStatus(message, '');
    else if (was !== 'idle' && $('#gps-status')) setStatus('GPS is off.', '');
    if (nav.plan) updateNext();
  }

  function setButtons(running) {
    $('#gps-start').disabled = running; $('#gps-sim').disabled = running; $('#gps-stop').disabled = !running;
  }

  /* ---------- wiring ---------- */
  const originalSwitchTab = window.switchTab;
  if (typeof originalSwitchTab === 'function') {
    window.switchTab = function (tab) {
      originalSwitchTab.apply(this, arguments);
      if (tab === 'navigator') {
        buildNavigatorUI();
        if (nav.map) setTimeout(() => { nav.map.invalidateSize(); if (nav.plan) drawMap(); else showPlacePins(); }, 60);
      }
    };
  }
  // exposed for tests / console
  window.ttNav = nav;
  window.ttNavTools = { buildNavigatorUI, planTrip, startSimulation, stopTracking, onPosition, segDistM, haversineM, loadSaved, thinPlan };
})();
