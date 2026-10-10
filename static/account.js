/*
 * Travel Techie: accounts.
 *   - Sign up / log in (modal), header account menu
 *   - Profile page (new panel): My Trips = booking history + saved plans, with plan details; Settings
 *   - "Save to My Trips" for AI Planner itineraries (button injected next to "Book This Trip")
 *     and Trip Navigator plans (button lives in features.js and calls ttAccount.savePlan)
 *
 * How it plugs into the existing page without changing its code:
 *   * the page already keys bookings by localStorage "tt_client_id". When you log in we move your guest
 *     bookings into your account (POST /auth/claim) and switch tt_client_id to your account's id, so the
 *     existing "My Bookings" tab and every Book button keep working, now saving to your account.
 *   * logging out gives the browser a fresh guest id, so the next person doesn't see your bookings.
 *   * the login token is kept in localStorage and sent as "Authorization: Bearer ..." by this file only.
 */
(function () {
  'use strict';

  const API = (typeof API_BASE !== 'undefined') ? API_BASE : ((location.port === '8000') ? '/api' : 'http://localhost:8000/api');
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inr = (n) => '₹' + Math.round(n || 0).toLocaleString('en-IN');
  const toast = (m) => { if (typeof showToast === 'function') showToast(m); };
  const fmtDate = (iso) => { try { return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); } catch (e) { return ''; } };

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  const newId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

  const state = { token: store.get('tt_token'), user: null, trips: null };
  try { state.user = JSON.parse(store.get('tt_user') || 'null'); } catch (e) { state.user = null; }
  if (!state.token) state.user = null;
  const ui = { section: 'trips', sub: 'bookings', filter: 'all' };

  /* =====================================================================
   * API helper
   * ===================================================================== */
  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    let res;
    try { res = await fetch(API + path, Object.assign({}, opts, { headers })); }
    catch (e) { throw new Error("Can't reach the server. Is it still running?"); }
    let body = null;
    try { body = await res.json(); } catch (e) { /* no body */ }
    if (res.status === 401 && state.token && path.indexOf('/auth/login') !== 0) { endSession(false); }
    if (!res.ok) {
      let d = body && body.detail;
      if (Array.isArray(d)) d = d.map((x) => x.msg || '').join('. ');
      throw new Error(d || `Request failed (${res.status})`);
    }
    return body ? body.data : null;
  }

  /* =====================================================================
   * Session
   * ===================================================================== */
  function startSession(token, user) {
    state.token = token; state.user = user;
    store.set('tt_token', token); store.set('tt_user', JSON.stringify(user));
  }

  /** Logged out (or the session expired): forget the account and give this browser a fresh guest id. */
  function endSession(announce) {
    const had = !!state.user;
    state.token = null; state.user = null; state.trips = null;
    store.del('tt_token'); store.del('tt_user');
    store.set('tt_client_id', newId());
    renderHeader();
    if (had) {
      if (announce) toast('Logged out');
      else toast('Your session expired. Please log in again.');
      refreshBookingsTab();
      const p = $('#panel-profile');
      if (p && p.classList.contains('active') && typeof switchTab === 'function') switchTab(null);
      window.dispatchEvent(new CustomEvent('tt-auth-change', { detail: null }));
    }
  }

  function refreshBookingsTab() {
    const active = $('#panel-bookings');
    if (typeof loadMyBookings === 'function' && active && active.classList.contains('active')) { try { loadMyBookings(); } catch (e) { /* ignore */ } }
  }

  /** After login: move guest bookings into the account, then make the account id the browser's id. */
  async function adoptAccount(user) {
    const guest = store.get('tt_client_id');
    if (guest && guest !== user.client_id) {
      try {
        const r = await api('/auth/claim', { method: 'POST', body: JSON.stringify({ guest_client_id: guest }) });
        if (r && r.moved) toast(`${r.moved} earlier booking${r.moved > 1 ? 's' : ''} added to your account`);
      } catch (e) { /* not fatal: the account still works */ }
    }
    store.set('tt_client_id', user.client_id);
  }

  async function restoreSession() {
    if (!state.token) { renderHeader(); return; }
    renderHeader();                       // show the cached user instantly
    try {
      const user = await api('/auth/me');
      state.user = user; store.set('tt_user', JSON.stringify(user));
      if (store.get('tt_client_id') !== user.client_id) store.set('tt_client_id', user.client_id);
      renderHeader();
    } catch (e) {
      if (state.token) renderHeader();    // server unreachable: keep the cached login for now
    }
  }

  /* =====================================================================
   * Header: Log in / Sign up, or the account menu
   * ===================================================================== */
  function renderHeader() {
    const box = window.ttNavActions && window.ttNavActions();
    if (!box) return;
    let acct = $('.tt-acct', box);
    if (!acct) { acct = document.createElement('div'); acct.className = 'tt-acct'; box.appendChild(acct); }
    if (!state.user) {
      acct.innerHTML = '<button type="button" class="tt-pill-btn ghost" data-a="login">Log in</button><button type="button" class="tt-pill-btn primary" data-a="signup">Sign up</button>';
      $('[data-a="login"]', acct).addEventListener('click', () => openAuth('login'));
      $('[data-a="signup"]', acct).addEventListener('click', () => openAuth('signup'));
      return;
    }
    const first = state.user.name.split(' ')[0];
    acct.innerHTML = `
      <button type="button" class="tt-avatar-btn" aria-haspopup="menu" aria-expanded="false"><span class="tt-avatar">${esc(state.user.name.charAt(0).toUpperCase())}</span><span>${esc(first)}</span><span aria-hidden="true">▾</span></button>
      <div class="tt-menu" role="menu">
        <div class="who"><b>${esc(state.user.name)}</b>${esc(state.user.email)}</div><hr>
        <button type="button" role="menuitem" data-m="trips">🧳 My Trips</button>
        <button type="button" role="menuitem" data-m="plans">🗺️ Saved plans</button>
        <button type="button" role="menuitem" data-m="settings">👤 Profile &amp; settings</button><hr>
        <button type="button" role="menuitem" data-m="logout">🚪 Log out</button>
      </div>`;
    const btn = $('.tt-avatar-btn', acct), menu = $('.tt-menu', acct);
    const close = () => { menu.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', (e) => { e.stopPropagation(); const o = menu.classList.toggle('open'); btn.setAttribute('aria-expanded', String(o)); });
    document.addEventListener('click', (e) => { if (!acct.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    $$('[data-m]', menu).forEach((b) => b.addEventListener('click', () => {
      close();
      const m = b.dataset.m;
      if (m === 'trips') openProfile('trips', 'bookings');
      else if (m === 'plans') openProfile('trips', 'plans');
      else if (m === 'settings') openProfile('settings');
      else if (m === 'logout') logout();
    }));
  }

  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); } catch (e) { /* the local logout still happens */ }
    endSession(true);
  }

  /* =====================================================================
   * Modal helper (shared by login + plan details)
   * ===================================================================== */
  function makeModal(id, wide) {
    let ov = document.getElementById(id);
    if (ov) return ov;
    ov = document.createElement('div');
    ov.className = 'tt-overlay'; ov.id = id;
    ov.innerHTML = `<div class="tt-modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true"><button type="button" class="tt-x" aria-label="Close">✕</button><div class="tt-body"></div></div>`;
    document.body.appendChild(ov);
    const close = () => closeModal(ov);
    $('.tt-x', ov).addEventListener('click', close);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) close(); });
    ov.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { close(); return; }
      if (e.key !== 'Tab') return;                       // keep keyboard focus inside the dialog
      const f = $$('button, input, a[href], select', ov).filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    return ov;
  }
  let lastFocus = null;
  function openModal(ov) { lastFocus = document.activeElement; ov.classList.add('open'); document.body.style.overflow = 'hidden'; }
  function closeModal(ov) {
    ov.classList.remove('open');
    if (!$('.tt-overlay.open')) document.body.style.overflow = '';
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* ignore */ } }
  }

  /* =====================================================================
   * Login / sign-up modal
   * ===================================================================== */
  let afterAuth = null;
  function openAuth(mode, then) {
    afterAuth = then || null;
    const ov = makeModal('tt-auth');
    const body = $('.tt-body', ov);
    let m = mode === 'signup' ? 'signup' : 'login';

    function paint() {
      const su = m === 'signup';
      body.innerHTML = `
        <h2>${su ? 'Create your account' : 'Welcome back'}</h2>
        <p class="sub">${su ? 'Save your bookings and trip plans in one place.' : 'Log in to see your trips, bookings and saved plans.'}</p>
        <div class="tt-seg" role="tablist"><button type="button" class="${su ? '' : 'on'}" data-m="login" role="tab">Log in</button><button type="button" class="${su ? 'on' : ''}" data-m="signup" role="tab">Sign up</button></div>
        <div class="tt-error" id="tt-auth-err" role="alert"></div>
        <form id="tt-auth-form" novalidate>
          ${su ? '<div class="tt-field"><label for="tt-a-name">Your name</label><div class="box"><input id="tt-a-name" autocomplete="name" maxlength="60" placeholder="e.g. Chandana"></div></div>' : ''}
          <div class="tt-field"><label for="tt-a-email">Email</label><div class="box"><input id="tt-a-email" type="email" autocomplete="email" placeholder="you@example.com"></div></div>
          <div class="tt-field"><label for="tt-a-pass">Password</label><div class="box"><input id="tt-a-pass" type="password" autocomplete="${su ? 'new-password' : 'current-password'}" placeholder="${su ? 'At least 8 characters' : 'Your password'}"><button type="button" class="eye" aria-label="Show password">👁️</button></div>${su ? '<div class="hint">Use 8+ characters. Don\'t reuse a password from another site.</div>' : ''}</div>
          <button class="tt-submit" type="submit">${su ? 'Create account' : 'Log in'}</button>
        </form>
        <p class="tt-fine">${su ? 'Already have an account? <button class="tt-link" type="button" data-m="login">Log in</button>' : 'New here? <button class="tt-link" type="button" data-m="signup">Create an account</button>'}<br>or <button class="tt-link" type="button" data-close>continue as guest</button></p>`;
      $$('[data-m]', body).forEach((b) => b.addEventListener('click', () => { m = b.dataset.m; paint(); }));
      $('[data-close]', body).addEventListener('click', () => closeModal(ov));
      const pass = $('#tt-a-pass', body);
      $('.eye', body).addEventListener('click', (e) => { const show = pass.type === 'password'; pass.type = show ? 'text' : 'password'; e.currentTarget.textContent = show ? '🙈' : '👁️'; e.currentTarget.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); });
      $('#tt-auth-form', body).addEventListener('submit', submit);
      const first = $(su ? '#tt-a-name' : '#tt-a-email', body); if (first) first.focus();
    }

    async function submit(e) {
      e.preventDefault();
      const su = m === 'signup';
      const err = $('#tt-auth-err', body), btn = $('.tt-submit', body);
      const name = su ? $('#tt-a-name', body).value.trim() : '';
      const email = $('#tt-a-email', body).value.trim();
      const password = $('#tt-a-pass', body).value;
      const fail = (t) => { err.textContent = t; err.classList.add('show'); };
      err.classList.remove('show');
      if (su && !name) return fail('Please enter your name.');
      if (!/^\S+@\S+\.\S+$/.test(email)) return fail('Please enter a valid email address.');
      if (!password) return fail('Please enter your password.');
      if (su && password.length < 8) return fail('Your password needs at least 8 characters.');
      btn.disabled = true; btn.textContent = su ? 'Creating account…' : 'Logging in…';
      try {
        const out = await api(su ? '/auth/register' : '/auth/login', { method: 'POST', body: JSON.stringify(su ? { name, email, password } : { email, password }) });
        startSession(out.token, out.user);
        await adoptAccount(out.user);
        closeModal(ov);
        renderHeader();
        toast(su ? `Welcome to Travel Techie, ${out.user.name.split(' ')[0]}!` : `Welcome back, ${out.user.name.split(' ')[0]}`);
        refreshBookingsTab();
        window.dispatchEvent(new CustomEvent('tt-auth-change', { detail: out.user }));
        const cb = afterAuth; afterAuth = null;
        if (cb) cb();
      } catch (ex) {
        fail(ex.message);
        btn.disabled = false; btn.textContent = su ? 'Create account' : 'Log in';
      }
    }
    paint();
    openModal(ov);
  }

  /* =====================================================================
   * Profile panel
   * ===================================================================== */
  const ICON = { flight: '✈️', hotel: '🏨', train: '🚆', bus: '🚌', cab: '🚕', tour: '🎟️', holiday: '🧳', package: '🧳', itinerary: '🗺️' };
  const KIND = { navigator: { icon: '🧭', label: 'Trip Navigator plan' }, ai_planner: { icon: '✨', label: 'AI Planner itinerary' } };

  function ensurePanel() {
    let p = $('#panel-profile');
    if (p) return p;
    const ref = $('#panel-navigator') || $('.panel');
    if (!ref) return null;
    p = document.createElement('div');
    p.className = 'panel'; p.id = 'panel-profile';
    ref.parentNode.appendChild(p);
    return p;
  }

  function openProfile(section, sub) {
    if (!state.user) { openAuth('login', () => openProfile(section, sub)); return; }
    ui.section = section || 'trips';
    if (sub) ui.sub = sub;
    ui.filter = 'all';
    const p = ensurePanel();
    if (!p || typeof switchTab !== 'function') return;
    switchTab('profile');
    p.scrollIntoView({ behavior: 'smooth', block: 'start' });   // .panel has a scroll-margin so the sticky tab bar doesn't cover it
    renderProfile();
    loadTrips();
  }

  async function loadTrips() {
    try {
      state.trips = await api('/me/trips');
    } catch (e) {
      if (!state.user) return;
      state.trips = state.trips || { bookings: [], plans: [] };
      toast('Could not load your trips: ' + e.message);
    }
    renderProfile();
  }

  function renderProfile() {
    const p = $('#panel-profile');
    if (!p || !state.user) return;
    const u = state.user, t = state.trips;
    const confirmed = t ? t.bookings.filter((b) => b.status === 'confirmed') : [];
    const spent = confirmed.reduce((s, b) => s + (b.price || 0), 0);
    p.innerHTML = `
      <div class="tt-prof-head">
        <div class="tt-avatar lg">${esc(u.name.charAt(0).toUpperCase())}</div>
        <div><h2>${esc(u.name)}</h2><p>${esc(u.email)} · member since ${esc(fmtDate(u.created_at))}</p></div>
        <div class="tt-stats">
          <div class="tt-stat"><b>${t ? confirmed.length : '–'}</b><span>Bookings</span></div>
          <div class="tt-stat"><b>${t ? inr(spent) : '–'}</b><span>Total booked</span></div>
          <div class="tt-stat"><b>${t ? t.plans.length : '–'}</b><span>Saved plans</span></div>
        </div>
      </div>
      <div class="tt-tabs2" role="tablist">
        <button type="button" class="${ui.section === 'trips' ? 'on' : ''}" data-s="trips">🧳 My Trips</button>
        <button type="button" class="${ui.section === 'settings' ? 'on' : ''}" data-s="settings">⚙️ Settings</button>
      </div>
      <div id="tt-prof-body"></div>`;
    $$('[data-s]', p).forEach((b) => b.addEventListener('click', () => { ui.section = b.dataset.s; renderProfile(); }));
    if (ui.section === 'settings') renderSettings(); else renderTrips();
  }

  function renderTrips() {
    const body = $('#tt-prof-body'), t = state.trips;
    if (!t) { body.innerHTML = '<div class="tt-empty"><div class="big">⏳</div><b>Loading your trips…</b></div>'; return; }
    body.innerHTML = `
      <div class="tt-tabs2" role="tablist">
        <button type="button" class="${ui.sub === 'bookings' ? 'on' : ''}" data-sub="bookings">🧾 Booking history (${t.bookings.length})</button>
        <button type="button" class="${ui.sub === 'plans' ? 'on' : ''}" data-sub="plans">🗺️ Saved plans (${t.plans.length})</button>
      </div>
      <div id="tt-trips-body"></div>`;
    $$('[data-sub]', body).forEach((b) => b.addEventListener('click', () => { ui.sub = b.dataset.sub; ui.filter = 'all'; renderTrips(); }));
    if (ui.sub === 'plans') renderPlans(); else renderBookings();
  }

  function renderBookings() {
    const box = $('#tt-trips-body'), all = state.trips.bookings;
    if (!all.length) {
      box.innerHTML = '<div class="tt-empty"><div class="big">🧳</div><b>No bookings yet</b>Book a flight, hotel or holiday package and it will appear here.<br><br><button type="button" class="tt-mini primary" data-go="holidays">Browse holiday packages</button></div>';
      $('[data-go]', box).addEventListener('click', () => { if (typeof navSwitch === 'function') navSwitch('holidays'); });
      return;
    }
    const counts = { all: all.length, confirmed: 0, cancelled: 0 };
    all.forEach((b) => { if (counts[b.status] != null) counts[b.status]++; });
    const list = ui.filter === 'all' ? all : all.filter((b) => b.status === ui.filter);
    box.innerHTML = `
      <div class="tt-tabs2 small">${['all', 'confirmed', 'cancelled'].map((f) => `<button type="button" class="${ui.filter === f ? 'on' : ''}" data-f="${f}">${f[0].toUpperCase() + f.slice(1)} (${counts[f]})</button>`).join('')}</div>
      <div class="tt-list">${list.map((b) => `
        <div class="tt-trip">
          <div class="ic">${ICON[b.vertical] || '🧾'}</div>
          <div class="t">${esc(b.title)}</div>
          <div class="r"><span class="price">${inr(b.price)}</span><span class="tt-badge2 ${esc(b.status)}">${esc(b.status)}</span>
            ${b.status === 'confirmed' ? `<div class="acts"><button type="button" class="tt-mini danger" data-cancel="${esc(b.booking_id)}">Cancel</button></div>` : ''}</div>
          <div class="m">${esc([b.subtitle, b.provider, 'Booked ' + fmtDate(b.created_at)].filter(Boolean).join(' · '))}</div>
        </div>`).join('') || '<div class="tt-empty">Nothing here.</div>'}</div>`;
    $$('[data-f]', box).forEach((b) => b.addEventListener('click', () => { ui.filter = b.dataset.f; renderBookings(); }));
    $$('[data-cancel]', box).forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Cancel this booking?')) return;
      b.disabled = true;
      try {
        await api(`/bookings/${encodeURIComponent(b.dataset.cancel)}/cancel?client_id=${encodeURIComponent(state.user.client_id)}`, { method: 'POST' });
        toast('Booking cancelled');
        await loadTrips();
      } catch (e) { b.disabled = false; toast("Couldn't cancel: " + e.message); }
    }));
  }

  function planFacts(pl) {
    return pl.kind === 'navigator' ? 'Budget-based route plan with directions' : 'AI-written day-by-day itinerary';
  }

  function renderPlans() {
    const box = $('#tt-trips-body'), plans = state.trips.plans;
    if (!plans.length) {
      box.innerHTML = '<div class="tt-empty"><div class="big">🗺️</div><b>No saved plans yet</b>Plan a trip in <b style="display:inline">Trip Navigator</b> or the <b style="display:inline">AI Planner</b> and press <b style="display:inline">Save to My Trips</b>.<br><br><button type="button" class="tt-mini primary" data-go="navigator">Open Trip Navigator</button></div>';
      $('[data-go]', box).addEventListener('click', () => { if (typeof navSwitch === 'function') navSwitch('navigator'); });
      return;
    }
    box.innerHTML = `<div class="tt-list">${plans.map((pl) => `
      <div class="tt-trip">
        <div class="ic">${(KIND[pl.kind] || {}).icon || '🗺️'}</div>
        <div class="t">${esc(pl.title)}</div>
        <div class="r"><div class="acts">
          <button type="button" class="tt-mini primary" data-view="${esc(pl.id)}">View details</button>
          <button type="button" class="tt-mini danger" data-del="${esc(pl.id)}">Delete</button></div></div>
        <div class="m">${esc([(KIND[pl.kind] || {}).label, pl.destination, 'Saved ' + fmtDate(pl.created_at)].filter(Boolean).join(' · '))}</div>
      </div>`).join('')}</div>`;
    $$('[data-view]', box).forEach((b) => b.addEventListener('click', () => viewPlan(b.dataset.view)));
    $$('[data-del]', box).forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this saved plan?')) return;
      try { await api('/me/plans/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' }); toast('Plan deleted'); await loadTrips(); }
      catch (e) { toast("Couldn't delete: " + e.message); }
    }));
  }

  function renderSettings() {
    const body = $('#tt-prof-body'), u = state.user, mode = (window.ttTheme && window.ttTheme.mode()) || 'system';
    body.innerHTML = `
      <div class="tt-settings">
        <div class="tt-setcard"><h4>Appearance</h4>
          <div class="tt-tabs2 small" id="tt-theme-pick" style="margin:0">
            ${[['light', '☀️ Light'], ['dark', '🌙 Dark'], ['system', '💻 System']].map(([v, l]) => `<button type="button" class="${mode === v ? 'on' : ''}" data-t="${v}">${l}</button>`).join('')}
          </div></div>
        <div class="tt-setcard"><h4>Account</h4>
          <div class="tt-kv"><span>Name</span><span>${esc(u.name)}</span><span>Email</span><span>${esc(u.email)}</span><span>Member since</span><span>${esc(fmtDate(u.created_at))}</span></div></div>
        <div class="tt-setcard"><h4>Session</h4>
          <p style="margin:0 0 10px;font-size:13px;color:var(--muted)">Logging out also clears your bookings from this browser's My Bookings tab. They stay safe in your account.</p>
          <button type="button" class="tt-mini danger" id="tt-logout">🚪 Log out</button></div>
      </div>`;
    $$('[data-t]', body).forEach((b) => b.addEventListener('click', () => { if (window.ttTheme) window.ttTheme.set(b.dataset.t); renderSettings(); }));
    $('#tt-logout', body).addEventListener('click', logout);
  }

  /* =====================================================================
   * Plan details modal
   * ===================================================================== */
  async function viewPlan(id) {
    const ov = makeModal('tt-plan', true), body = $('.tt-body', ov);
    body.innerHTML = '<div class="tt-empty"><div class="big">⏳</div><b>Loading plan…</b></div>';
    openModal(ov);
    try {
      const pl = await api('/me/plans/' + encodeURIComponent(id));
      body.innerHTML = `<h2>${esc(pl.title)}</h2><p class="sub">${esc((KIND[pl.kind] || {}).label || '')} · saved ${esc(fmtDate(pl.created_at))}</p><div class="tt-det">${pl.kind === 'navigator' ? navDetails(pl.payload) : plannerDetails(pl.payload)}</div>
        <div class="foot">${pl.kind === 'navigator' ? '<button type="button" class="tt-mini primary" id="tt-open-nav">🧭 Open on the map</button>' : ''}<button type="button" class="tt-mini" id="tt-det-close">Close</button></div>`;
      $('#tt-det-close', body).addEventListener('click', () => closeModal(ov));
      const open = $('#tt-open-nav', body);
      if (open) open.addEventListener('click', async () => {
        closeModal(ov);
        if (typeof switchTab === 'function') switchTab('navigator');
        const np = $('#panel-navigator'); if (np) np.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (window.ttNavTools && window.ttNavTools.loadSaved) await window.ttNavTools.loadSaved(pl.payload);
      });
    } catch (e) { body.innerHTML = `<div class="tt-error show">${esc(e.message)}</div>`; }
  }

  function navDetails(p) {
    const b = p.breakdown || {};
    const parts = [['Stay', b.stay, '#0d9488'], ['Food', b.food, '#f59e0b'], ['Activities', b.activities, '#8b5cf6'], ['Local transport', b.local_transport, '#3b82f6']];
    const sum = parts.reduce((s, x) => s + (x[1] || 0), 0) || 1;
    return `
      <div class="tt-chipset"><span>📍 ${esc(p.destination)}</span><span>💰 ${inr(p.budget)} budget</span><span>🌙 ${p.nights} night(s)</span><span>👥 ${p.travelers} traveler(s)</span><span>🚶 ${esc(p.pace || 'balanced')} pace</span></div>
      <h3>Budget</h3>
      <div class="tt-bars">${parts.map((x) => `<i style="width:${(x[1] || 0) / sum * 100}%;background:${x[2]}" title="${x[0]}"></i>`).join('')}</div>
      <p>${parts.map((x) => `${x[0]} ${inr(x[1])}`).join(' · ')}</p>
      <p><b>Total about ${inr(b.spent)}</b>${p.over_budget ? ' <span style="color:#dc2626">(over budget)</span>' : ''}</p>
      <h3>Stay</h3><p>🏨 ${esc((p.stay || {}).label)} · ${inr((p.stay || {}).price_per_night)} per night</p>
      <h3>Day by day</h3>
      ${(p.days || []).map((d) => `
        <div class="tt-daybox"><b>Day ${d.day}</b> <span class="sm">· ${(d.route || {}).distance_km || 0} km · about ${d.total_hours} h</span>
          <ol>${(d.stops || []).map((s) => `<li>${esc(s.name)}${s.selected ? ' ⭐' : ''} <span class="sm">${s.cost ? inr(s.cost) + ' pp' : 'Free'} · ~${s.visit_min} min</span></li>`).join('') || '<li class="sm">Free day</li>'}</ol></div>`).join('')}
      ${(p.notes || []).length ? '<h3>Notes</h3>' + p.notes.map((n) => `<p>💡 ${esc(n)}</p>`).join('') : ''}`;
  }

  function plannerDetails(p) {
    const it = p.itinerary || {}, rq = p.request || {}, bb = it.budget_breakdown || {};
    const total = (bb.travel || 0) + (bb.stay || 0) + (bb.food || 0) + (bb.activities || 0);
    return `
      <div class="tt-chipset">${rq.destination ? `<span>📍 ${esc(rq.destination)}</span>` : ''}${rq.budget ? `<span>💰 ${inr(rq.budget)}</span>` : ''}${rq.duration ? `<span>📅 ${rq.duration} days</span>` : ''}${rq.travelers ? `<span>👥 ${rq.travelers}</span>` : ''}${rq.hotel ? `<span>🏨 ${esc(rq.hotel)}</span>` : ''}${rq.food ? `<span>🍽️ ${esc(rq.food)}</span>` : ''}</div>
      <h3>Overview</h3><p>${esc(it.destination_overview)}</p>
      <h3>Budget breakdown</h3><p>Travel ${inr(bb.travel)} · Stay ${inr(bb.stay)} · Food ${inr(bb.food)} · Activities ${inr(bb.activities)}<br><b>Total ${inr(total)}</b></p>
      <h3>Day by day</h3>
      ${(it.days || []).map((d) => `
        <div class="tt-daybox"><b>Day ${d.day}: ${esc(d.title)}</b> <span class="sm">· ${esc(d.city)}</span>
          <ul>${(d.activities || []).map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
          ${d.meals_note ? `<div class="sm">🍽️ ${esc(d.meals_note)}</div>` : ''}
          ${d.hotel && d.hotel.name ? `<div class="sm">🏨 ${esc(d.hotel.name)}${d.hotel.price_per_night ? ' · ' + inr(d.hotel.price_per_night) + '/night' : ''}</div>` : ''}</div>`).join('')}`;
  }

  /* =====================================================================
   * Saving plans (called by features.js for navigator plans)
   * ===================================================================== */
  async function savePlan(kind, title, destination, payload) {
    if (!state.user) {
      toast('Log in to save this plan');
      openAuth('login', () => savePlan(kind, title, destination, payload));
      return false;
    }
    try {
      await api('/me/plans', { method: 'POST', body: JSON.stringify({ kind, title, destination, payload }) });
      toast('Saved to My Trips ✓');
      state.trips = null;
      return true;
    } catch (e) { toast("Couldn't save: " + e.message); return false; }
  }

  /* AI Planner: remember exactly what was asked when Generate is pressed, then add a Save button
     next to "Book This Trip" whenever a new itinerary is shown. */
  let plannerRequest = null;
  function watchPlanner() {
    const gen = $('#aiBtn');
    if (gen) gen.addEventListener('click', () => {
      const v = (id) => { const el = document.getElementById(id); return el ? el.value : ''; };
      plannerRequest = { startCity: v('ai-start'), destination: v('ai-destination').trim(), budget: Number(v('ai-budget')), duration: Number(v('ai-duration')),
        travelers: Number(v('ai-travelers')), food: v('ai-food'), hotel: v('ai-hotel') };
    }, true);
    const slot = $('#overviewSlot');
    if (!slot) return;
    new MutationObserver(() => {
      const itin = window.lastItinerary;
      const book = $('.overview-card .r-btn', slot);
      if (!itin || !book || $('.tt-save-btn', slot)) return;
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'tt-save-btn'; b.textContent = '💾 Save to My Trips';
      b.addEventListener('click', async () => {
        const first = (itin.days && itin.days[0] && itin.days[0].city) || '';
        const dest = (plannerRequest && plannerRequest.destination) || first || 'AI trip';
        const days = (itin.days || []).length;
        const ok = await savePlan('ai_planner', `${dest} · ${days}-day AI itinerary`, dest, { request: plannerRequest || {}, itinerary: itin });
        if (ok) { b.textContent = '✓ Saved'; b.classList.add('saved'); b.disabled = true; }
      });
      book.insertAdjacentElement('afterend', b);
    }).observe(slot, { childList: true, subtree: true });
  }

  /* =====================================================================
   * Start
   * ===================================================================== */
  window.ttAccount = {
    isLoggedIn: () => !!state.user,
    user: () => state.user,
    openLogin: (then) => openAuth('login', then),
    openProfile, savePlan,
  };

  function init() { restoreSession(); watchPlanner(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
