/*
 * Travel Techie: theme + cursor-following logos.
 *   - Light / Dark / System theme, saved in localStorage ("tt_theme"). theme-init.js applies the saved
 *     theme before first paint; this file adds the toggle button and lets other code change the theme.
 *   - A field of faint floating logos that turn to face the cursor and drift toward it. The header logo
 *     tilts toward the cursor too. Disabled for touch screens and for "reduce motion" users.
 * Nothing in the existing page code is modified.
 */
(function () {
  'use strict';

  const root = document.documentElement;
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  /* =====================================================================
   * Theme
   * ===================================================================== */
  const theme = {
    mode() { try { return localStorage.getItem('tt_theme') || 'system'; } catch (e) { return 'system'; } },
    resolved() { const m = this.mode(); return m === 'system' ? (mq && mq.matches ? 'dark' : 'light') : m; },
    apply(animate) {
      if (animate) { root.classList.add('tt-theme-anim'); setTimeout(() => root.classList.remove('tt-theme-anim'), 450); }
      root.setAttribute('data-theme', this.resolved());
      syncToggle();
      window.dispatchEvent(new CustomEvent('tt-theme-change', { detail: this.resolved() }));
    },
    set(mode) {
      try { localStorage.setItem('tt_theme', mode); } catch (e) { /* private mode: still works for this visit */ }
      this.apply(true);
    },
    toggle() { this.set(this.resolved() === 'dark' ? 'light' : 'dark'); },
  };
  window.ttTheme = theme;
  if (mq && mq.addEventListener) mq.addEventListener('change', () => { if (theme.mode() === 'system') theme.apply(true); });

  /* The header has a flex row (.nav-inner). We add one container on the right for our buttons. */
  window.ttNavActions = function () {
    let box = document.querySelector('.tt-nav-actions');
    if (!box) {
      const inner = document.querySelector('.nav-inner');
      if (!inner) return null;
      box = document.createElement('div');
      box.className = 'tt-nav-actions';
      inner.appendChild(box);
    }
    return box;
  };

  let toggleBtn = null;
  function syncToggle() {
    if (!toggleBtn) return;
    const dark = theme.resolved() === 'dark';
    toggleBtn.textContent = dark ? '☀️' : '🌙';
    toggleBtn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
    toggleBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    toggleBtn.setAttribute('aria-pressed', String(dark));
  }

  function buildToggle() {
    const box = window.ttNavActions();
    if (!box || toggleBtn) return;
    toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'tt-icon-btn';
    toggleBtn.id = 'tt-theme-toggle';
    toggleBtn.addEventListener('click', () => theme.toggle());
    box.prepend(toggleBtn);
    syncToggle();
  }

  /* =====================================================================
   * Cursor-following logos
   * ===================================================================== */
  const canHover = window.matchMedia && matchMedia('(hover: hover)').matches;
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // x%, y%, size px, depth (how strongly it reacts), opacity
  const SPOTS = [
    [4, 22, 54, 1.0, .20], [93, 18, 44, 0.7, .18], [9, 62, 34, 0.5, .16], [90, 58, 62, 1.0, .18],
    [48, 9, 26, 0.4, .14], [74, 80, 30, 0.6, .15], [24, 86, 46, 0.8, .16], [60, 34, 22, 0.35, .10],
    [34, 44, 20, 0.3, .09],
  ];
  const logos = [];
  let mouse = { x: innerWidth / 2, y: innerHeight / 3, moved: false };
  let raf = 0;

  const logoSvg = (id) => `
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs><linearGradient id="${id}" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
        <stop stop-color="#f97316"/><stop offset="1" stop-color="#0d9488"/></linearGradient></defs>
      <path d="M12 2L2 22L12 17L22 22L12 2Z" fill="url(#${id})" stroke="#065af3" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;

  function buildLogoField() {
    if (!canHover || reduce || document.getElementById('tt-logo-field')) return;
    const field = document.createElement('div');
    field.id = 'tt-logo-field';
    field.setAttribute('aria-hidden', 'true');
    SPOTS.forEach((s, i) => {
      const el = document.createElement('div');
      el.className = 'tt-fl';
      el.style.cssText = `left:${s[0]}%;top:${s[1]}%;width:${s[2]}px;height:${s[2]}px;opacity:${s[4]}`;
      const inner = document.createElement('span');
      inner.style.setProperty('--dur', (6 + (i % 4) * 1.3) + 's');
      inner.style.setProperty('--delay', (-i * 0.9) + 's');
      inner.style.width = inner.style.height = '100%';
      inner.innerHTML = logoSvg('ttFl' + i);
      el.appendChild(inner);
      field.appendChild(el);
      logos.push({ el, depth: s[3], size: s[2], angle: 0, x: 0, y: 0 });
    });
    document.body.insertBefore(field, document.body.firstChild);
    addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.moved = true; if (!raf) raf = requestAnimationFrame(tick); }, { passive: true });
    document.addEventListener('visibilitychange', () => { if (document.hidden && raf) { cancelAnimationFrame(raf); raf = 0; } });
  }

  const brandLogo = () => document.querySelector('.brand-logo');
  let brandAngle = 0;

  function tick() {
    raf = 0;
    let moving = false;
    logos.forEach((l) => {
      const r = l.el.getBoundingClientRect();
      // r includes our own current offset; subtract it so the logo's "home" position stays stable
      const cx = r.left - l.x + r.width / 2, cy = r.top - l.y + r.height / 2;
      const dx = mouse.x - cx, dy = mouse.y - cy;
      const dist = Math.hypot(dx, dy) || 1;
      // the logo's tip points up, so add 90 degrees to point it at the cursor
      let target = Math.atan2(dy, dx) * 180 / Math.PI + 90;
      let diff = ((target - l.angle + 540) % 360) - 180;          // shortest way round
      l.angle += diff * 0.10;
      // drift toward the cursor, stronger when closer, capped so logos never fly off
      const pull = Math.min(46, (260 / dist) * 22) * l.depth;
      const tx = (dx / dist) * pull, ty = (dy / dist) * pull;
      l.x += (tx - l.x) * 0.08; l.y += (ty - l.y) * 0.08;
      l.el.style.transform = `translate(${l.x.toFixed(1)}px, ${l.y.toFixed(1)}px) rotate(${l.angle.toFixed(1)}deg)`;
      if (Math.abs(diff) > 0.4 || Math.abs(tx - l.x) > 0.3 || Math.abs(ty - l.y) > 0.3) moving = true;
    });

    const b = brandLogo();
    if (b) {   // header logo: tilts toward the cursor, limited to +/- 35 degrees so it stays upright-ish
      const r = b.getBoundingClientRect();
      const a = Math.atan2(mouse.y - (r.top + r.height / 2), mouse.x - (r.left + r.width / 2)) * 180 / Math.PI + 90;
      const clamped = Math.max(-35, Math.min(35, ((a + 180) % 360) - 180));
      brandAngle += (clamped - brandAngle) * 0.12;
      b.style.transform = `rotate(${brandAngle.toFixed(1)}deg)`;
      if (Math.abs(clamped - brandAngle) > 0.3) moving = true;
    }
    if (moving && !document.hidden) raf = requestAnimationFrame(tick);
  }

  /* =====================================================================
   * Start
   * ===================================================================== */
  function init() {
    buildToggle();
    buildLogoField();
    theme.apply(false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
