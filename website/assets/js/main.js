/* =============================================================================
   AURELIA — behaviour
   Vanilla, no build step, no dependencies. Everything degrades: without JS the
   page is still readable, and every animation is skipped under
   prefers-reduced-motion.
   ========================================================================== */

(function () {
  'use strict';

  const D = window.AURELIA;
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const M = window.AureliaMotion || null;   // decoration; the page works without it

  const inr = new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0
  });
  const money = n => inr.format(Math.round(n));

  const img = (name, alt, w, h, cls = '', eager = false) => `
    <picture>
      <source srcset="assets/img/${name}.webp" type="image/webp">
      <img src="assets/img/${name}.jpg" alt="${alt}" width="${w}" height="${h}" class="${cls}"
           ${eager ? '' : 'loading="lazy"'} decoding="async">
    </picture>`;

  const esc = s => String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---------------------------------------------------------------------- */
  /* toasts                                                                  */
  /* ---------------------------------------------------------------------- */
  const toastHost = $('#toasts');
  function toast(msg, icon = 'i-check') {
    if (!toastHost) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `<svg class="i"><use href="#${icon}"/></svg><span>${esc(msg)}</span>`;
    toastHost.appendChild(el);
    setTimeout(() => {
      el.classList.add('is-out');
      el.addEventListener('animationend', () => el.remove(), { once: true });
    }, 3200);
  }

  /* ---------------------------------------------------------------------- */
  /* scroll: progress, header, reveal, parallax, active nav                   */
  /* ---------------------------------------------------------------------- */
  const header = $('#header');
  const progress = $('.scroll-progress i');
  const toTop = $('#toTop');

  function onScroll() {
    const y = window.scrollY;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (progress) progress.style.width = (max > 0 ? (y / max) * 100 : 0) + '%';

    // The header stays put rather than hiding on scroll-down: the cart and the
    // two calls to action live in it, and a header that retreats exactly when you
    // reach for the cart is a trap — scrolling it back into view re-hides it.
    if (header) header.classList.toggle('is-stuck', y > 30);
    if (toTop) toTop.hidden = y < 700;
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  toTop && toTop.addEventListener('click', () =>
    window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' }));

  // reveal on entry
  const revealIO = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries, obs) => {
        entries.forEach(e => {
          if (!e.isIntersecting) return;
          const d = e.target.dataset.delay;
          if (d) e.target.style.setProperty('--d', d + 'ms');
          e.target.classList.add('is-in');
          obs.unobserve(e.target);
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' })
    : null;

  function observeReveals(root = document) {
    const items = $$('.reveal:not(.is-in)', root);
    if (!revealIO) { items.forEach(el => el.classList.add('is-in')); return; }
    items.forEach(el => revealIO.observe(el));
  }

  // parallax
  const parallaxEls = $$('.parallax');
  if (parallaxEls.length && !reduced) {
    let ticking = false;
    const runParallax = () => {
      const vh = window.innerHeight;
      parallaxEls.forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.bottom < -200 || r.top > vh + 200) return;
        const speed = parseFloat(el.dataset.speed || '0.08');
        const shift = ((r.top + r.height / 2) - vh / 2) * speed;
        el.style.transform = `translate3d(0, ${shift.toFixed(1)}px, 0)`;
      });
      ticking = false;
    };
    window.addEventListener('scroll', () => {
      if (!ticking) { ticking = true; requestAnimationFrame(runParallax); }
    }, { passive: true });
    window.addEventListener('resize', runParallax);
    runParallax();
  }

  // active nav link
  const navLinks = $$('.nav-link');
  const sections = navLinks
    .map(a => document.getElementById(a.getAttribute('href').slice(1)))
    .filter(Boolean);
  if (sections.length && 'IntersectionObserver' in window) {
    const spy = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        navLinks.forEach(a =>
          a.classList.toggle('is-active', a.getAttribute('href') === '#' + e.target.id));
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    sections.forEach(s => spy.observe(s));
  }

  /* ---------------------------------------------------------------------- */
  /* mobile nav                                                              */
  /* ---------------------------------------------------------------------- */
  const burger = $('#burger');
  const nav = $('#nav');
  function closeNav() {
    if (!burger) return;
    burger.setAttribute('aria-expanded', 'false');
    burger.setAttribute('aria-label', 'Open menu');
    nav.classList.remove('is-open');
  }
  burger && burger.addEventListener('click', () => {
    const open = burger.getAttribute('aria-expanded') === 'true';
    burger.setAttribute('aria-expanded', String(!open));
    burger.setAttribute('aria-label', open ? 'Open menu' : 'Close menu');
    nav.classList.toggle('is-open', !open);
  });
  nav && $$('a', nav).forEach(a => a.addEventListener('click', closeNav));

  /* ---------------------------------------------------------------------- */
  /* marquee                                                                 */
  /* ---------------------------------------------------------------------- */
  const marquee = $('#marquee');
  if (marquee) {
    const run = D.ACCOLADES.map(t => `<span class="marquee-item">${esc(t)}</span>`).join('');
    marquee.innerHTML = run + run;   // duplicated so the -50% loop is seamless
  }

  /* ---------------------------------------------------------------------- */
  /* cards                                                                   */
  /* ---------------------------------------------------------------------- */
  function tagHtml(keys) {
    return keys.map(k => {
      const t = D.TAGS[k];
      return t ? `<span class="tag" data-tone="${t.tone}">${esc(t.short)}</span>` : '';
    }).join('');
  }

  function dishCard(item, opts = {}) {
    const popular = item.popular
      ? `<span class="dish-badge"><svg class="i"><use href="#i-spark"/></svg> Guest favourite</span>` : '';
    return `
      <article class="dish-card${opts.reveal ? ' reveal' : ''}" data-id="${item.id}" data-tilt>
        <div class="dish-media" data-reveal-media>
          ${popular}
          <span class="dish-rating"><svg class="i"><use href="#i-star"/></svg>${item.rating}</span>
          ${img(item.img, esc(item.name), 1200, 900)}
        </div>
        <div class="dish-body">
          <h3 class="dish-name">${esc(item.name)}</h3>
          <p class="dish-desc">${esc(item.desc)}</p>
          <div class="dish-tags">${tagHtml(item.tags)}</div>
          <div class="dish-foot">
            <span class="dish-price">${money(item.price)}</span>
            <button class="add-btn" type="button" data-add="${item.id}">
              <svg class="i"><use href="#i-plus"/></svg> Add
            </button>
          </div>
        </div>
      </article>`;
  }

  /* signature dishes ------------------------------------------------------ */
  const sigGrid = $('#signatureGrid');
  if (sigGrid) {
    const picks = D.MENU.filter(m => m.popular).slice(0, 6);
    sigGrid.innerHTML = picks.map((m, i) => dishCard(m, { reveal: true })).join('');
    $$('.dish-card', sigGrid).forEach((c, i) => (c.dataset.delay = String(i * 70)));
  }

  /* timeline -------------------------------------------------------------- */
  const timeline = $('#timeline');
  if (timeline) {
    timeline.innerHTML = D.TIMELINE.map(t => `
      <li class="reveal">
        <span class="timeline-year">${esc(t.year)}</span>
        <p class="timeline-text">${esc(t.text)}</p>
      </li>`).join('');
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(es => es.forEach(e =>
        e.target.classList.toggle('is-in', e.isIntersecting)), { rootMargin: '-40% 0px -40% 0px' });
      $$('li', timeline).forEach(li => io.observe(li));
    }
  }

  /* pillars --------------------------------------------------------------- */
  const pillarGrid = $('#pillarGrid');
  if (pillarGrid) {
    pillarGrid.innerHTML = D.PILLARS.map((p, i) => `
      <article class="pillar reveal" data-delay="${i * 80}">
        <span class="pillar-ico"><svg class="i"><use href="#i-${p.icon}"/></svg></span>
        <h3>${esc(p.title)}</h3>
        <p>${esc(p.text)}</p>
        <div class="pillar-stat">
          <span class="pillar-num" data-count="${p.stat}">0</span>
          <span class="pillar-label">${esc(p.statLabel)}</span>
        </div>
      </article>`).join('');
  }

  /* count-up -------------------------------------------------------------- */
  function countUp(el) {
    const target = parseFloat(el.dataset.count);
    if (reduced) { el.textContent = target; return; }
    const dur = 1500;
    const t0 = performance.now();
    const tick = now => {
      const p = Math.min((now - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  if ('IntersectionObserver' in window) {
    const countIO = new IntersectionObserver((es, obs) => es.forEach(e => {
      if (!e.isIntersecting) return;
      countUp(e.target); obs.unobserve(e.target);
    }), { threshold: 0.6 });
    $$('[data-count]').forEach(el => countIO.observe(el));
  } else {
    $$('[data-count]').forEach(el => (el.textContent = el.dataset.count));
  }

  /* ---------------------------------------------------------------------- */
  /* interactive menu                                                        */
  /* ---------------------------------------------------------------------- */
  const menuGrid = $('#menuGrid');
  const menuTabs = $('#menuTabs');
  const menuFilters = $('#menuFilters');
  const menuSearch = $('#menuSearch');
  const menuSort = $('#menuSort');
  const menuCount = $('#menuCount');
  const menuEmpty = $('#menuEmpty');
  const searchClear = $('#searchClear');

  const state = { cat: 'all', q: '', sort: 'popular', diets: new Set() };

  if (menuTabs) {
    const counts = c => c === 'all' ? D.MENU.length : D.MENU.filter(m => m.cat === c).length;
    menuTabs.innerHTML = [{ id: 'all', name: 'Everything' }, ...D.CATEGORIES].map(c => `
      <button class="menu-tab" role="tab" type="button" data-cat="${c.id}"
              aria-selected="${c.id === 'all'}">${esc(c.name)} <span>${counts(c.id)}</span></button>`).join('');
  }
  if (menuFilters) {
    menuFilters.innerHTML = ['veg', 'gf', 'zero', 'spicy', 'chef'].map(k => `
      <button class="filter-chip" type="button" data-diet="${k}" aria-pressed="false">${esc(D.TAGS[k].label)}</button>`).join('');
  }

  function filtered() {
    const q = state.q.trim().toLowerCase();
    let list = D.MENU.filter(m => {
      if (state.cat !== 'all' && m.cat !== state.cat) return false;
      for (const d of state.diets) if (!m.tags.includes(d)) return false;
      if (!q) return true;
      return (m.name + ' ' + m.desc).toLowerCase().includes(q);
    });
    const by = {
      popular: (a, b) => b.orders - a.orders,
      rating:  (a, b) => b.rating - a.rating || b.orders - a.orders,
      low:     (a, b) => a.price - b.price,
      high:    (a, b) => b.price - a.price,
      az:      (a, b) => a.name.localeCompare(b.name)
    }[state.sort];
    return list.sort(by);
  }

  function renderMenu() {
    if (!menuGrid) return;
    const list = filtered();

    // Re-rendering innerHTML would make every surviving card blink out and back.
    // FLIP measures where each card was, lets the DOM change, then plays the
    // difference — so filtering reads as the grid rearranging itself.
    const paint = () => {
      menuGrid.innerHTML = list.map(dishCard).join('');
      $$('.dish-card', menuGrid).forEach((c, i) =>
        (c.style.animationDelay = Math.min(i * 45, 400) + 'ms'));
    };
    if (M && menuGrid.children.length) M.flip(menuGrid, paint, { key: 'id' });
    else paint();
    if (menuCount) {
      menuCount.textContent = list.length
        ? `${list.length} ${list.length === 1 ? 'dish' : 'dishes'}`
        : '';
    }
    if (menuEmpty) menuEmpty.hidden = list.length > 0;
    syncAddButtons();
  }

  menuTabs && menuTabs.addEventListener('click', e => {
    const btn = e.target.closest('[data-cat]');
    if (!btn) return;
    state.cat = btn.dataset.cat;
    $$('.menu-tab', menuTabs).forEach(t =>
      t.setAttribute('aria-selected', String(t === btn)));
    renderMenu();
  });
  menuFilters && menuFilters.addEventListener('click', e => {
    const btn = e.target.closest('[data-diet]');
    if (!btn) return;
    const k = btn.dataset.diet;
    const on = btn.getAttribute('aria-pressed') === 'true';
    btn.setAttribute('aria-pressed', String(!on));
    on ? state.diets.delete(k) : state.diets.add(k);
    renderMenu();
  });
  if (menuSearch) {
    let t;
    menuSearch.addEventListener('input', () => {
      clearTimeout(t);
      searchClear.hidden = !menuSearch.value;
      t = setTimeout(() => { state.q = menuSearch.value; renderMenu(); }, 160);
    });
  }
  searchClear && searchClear.addEventListener('click', () => {
    menuSearch.value = ''; state.q = ''; searchClear.hidden = true;
    menuSearch.focus(); renderMenu();
  });
  menuSort && menuSort.addEventListener('change', () => {
    state.sort = menuSort.value; renderMenu();
  });
  $('#menuReset') && $('#menuReset').addEventListener('click', () => {
    state.q = ''; state.cat = 'all'; state.diets.clear(); state.sort = 'popular';
    if (menuSearch) { menuSearch.value = ''; searchClear.hidden = true; }
    if (menuSort) menuSort.value = 'popular';
    $$('.menu-tab', menuTabs).forEach(t =>
      t.setAttribute('aria-selected', String(t.dataset.cat === 'all')));
    $$('.filter-chip', menuFilters).forEach(c => c.setAttribute('aria-pressed', 'false'));
    renderMenu();
  });

  /* ---------------------------------------------------------------------- */
  /* cart                                                                    */
  /* ---------------------------------------------------------------------- */
  const KEY = 'aurelia.cart.v1';
  let cart = [];
  let promo = null;

  const PROMOS = {
    FIRSTFIRE: { off: .10, label: '10% off your first order' },
    ASHFORD20: { off: .20, label: '20% off, Ashford Lane regulars' }
  };

  try { cart = JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { cart = []; }
  cart = cart.filter(l => D.MENU.some(m => m.id === l.id) && l.qty > 0);

  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(cart)); } catch (e) {} };
  const itemOf = id => D.MENU.find(m => m.id === id);
  const cartCountN = () => cart.reduce((n, l) => n + l.qty, 0);

  function totals() {
    const sub = cart.reduce((n, l) => n + itemOf(l.id).price * l.qty, 0);
    const discount = promo ? sub * PROMOS[promo].off : 0;
    const after = sub - discount;
    const delivery = after === 0 ? 0 : (after >= D.RESTAURANT.freeDeliveryOver ? 0 : D.RESTAURANT.deliveryFee);
    const tax = after * D.RESTAURANT.taxRate;
    return { sub, discount, delivery, tax, total: after + delivery + tax };
  }

  function renderTotals(host) {
    if (!host) return;
    const t = totals();
    const rows = [
      ['Subtotal', money(t.sub), ''],
      ...(t.discount ? [[`Promo · ${promo}`, '−' + money(t.discount), 'is-discount']] : []),
      ['Delivery', t.delivery ? money(t.delivery) : 'Free', t.delivery ? '' : 'is-free'],
      ['Taxes (5%)', money(t.tax), ''],
      ['Total', money(t.total), 'is-total']
    ];
    host.innerHTML = rows.map(([k, v, cls]) =>
      `<div class="${cls}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  }

  const cartItemsEl = $('#cartItems');
  const cartEmptyEl = $('#cartEmpty');
  const cartFootEl  = $('#cartFoot');
  const cartCountEl = $('#cartCount');
  const cartBtn     = $('#cartBtn');

  function renderCart() {
    const n = cartCountN();
    if (cartCountEl) {
      cartCountEl.textContent = n;
      cartCountEl.dataset.empty = String(n === 0);
    }
    if (cartItemsEl) {
      cartItemsEl.innerHTML = cart.map(l => {
        const m = itemOf(l.id);
        return `
        <li class="cart-item" data-id="${m.id}">
          <div class="cart-item-img">${img(m.img, '', 1200, 900)}</div>
          <div>
            <p class="cart-item-name">${esc(m.name)}</p>
            <p class="cart-item-price">${money(m.price)} each</p>
            <div class="cart-item-row">
              <span class="qty">
                <button type="button" data-dec="${m.id}" aria-label="One fewer ${esc(m.name)}"><svg class="i"><use href="#i-minus"/></svg></button>
                <output>${l.qty}</output>
                <button type="button" data-inc="${m.id}" aria-label="One more ${esc(m.name)}"><svg class="i"><use href="#i-plus"/></svg></button>
              </span>
              <span class="cart-item-total">${money(m.price * l.qty)}</span>
              <button class="cart-remove" type="button" data-del="${m.id}" aria-label="Remove ${esc(m.name)}"><svg class="i"><use href="#i-trash"/></svg></button>
            </div>
          </div>
        </li>`;
      }).join('');
    }
    if (cartEmptyEl) cartEmptyEl.hidden = cart.length > 0;
    if (cartFootEl)  cartFootEl.hidden  = cart.length === 0;
    renderTotals($('#totals'));
    renderTotals($('#checkoutTotals'));
    const payAmount = $('#payAmount');
    if (payAmount) payAmount.textContent = money(totals().total);
    syncAddButtons();
    save();
  }

  function syncAddButtons() {
    $$('[data-add]').forEach(b => {
      const line = cart.find(l => l.id === b.dataset.add);
      b.classList.toggle('is-added', !!line);
      b.innerHTML = line
        ? `<svg class="i"><use href="#i-check"/></svg> ${line.qty} in order`
        : `<svg class="i"><use href="#i-plus"/></svg> Add`;
    });
  }

  function addToCart(id) {
    const line = cart.find(l => l.id === id);
    line ? line.qty++ : cart.push({ id, qty: 1 });
    renderCart();
    cartBtn && cartBtn.classList.add('is-bumped');
    setTimeout(() => cartBtn && cartBtn.classList.remove('is-bumped'), 560);
    toast(`${itemOf(id).name} added to your order`);
  }

  document.addEventListener('click', e => {
    const add = e.target.closest('[data-add]');
    if (add) {
      const card = add.closest('.dish-card');
      if (M && card && cartBtn) M.flyToCart(card.querySelector('.dish-media'), cartBtn);
      addToCart(add.dataset.add);
      return;
    }

    const inc = e.target.closest('[data-inc]');
    if (inc) {
      const l = cart.find(x => x.id === inc.dataset.inc);
      if (l) l.qty++;
      renderCart(); return;
    }
    const dec = e.target.closest('[data-dec]');
    if (dec) {
      const l = cart.find(x => x.id === dec.dataset.dec);
      if (l && --l.qty <= 0) cart = cart.filter(x => x.id !== dec.dataset.dec);
      renderCart(); return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      cart = cart.filter(x => x.id !== del.dataset.del);
      renderCart(); toast('Removed from your order'); return;
    }
  });

  /* promo ----------------------------------------------------------------- */
  const promoMsg = $('#promoMsg');
  $('#promoApply') && $('#promoApply').addEventListener('click', () => {
    const code = ($('#promoInput').value || '').trim().toUpperCase();
    if (!code) return;
    if (PROMOS[code]) {
      promo = code;
      promoMsg.textContent = PROMOS[code].label + ' applied.';
      promoMsg.classList.remove('is-error');
    } else {
      promo = null;
      promoMsg.textContent = 'That code is not recognised. Try FIRSTFIRE.';
      promoMsg.classList.add('is-error');
    }
    renderCart();
  });

  /* ---------------------------------------------------------------------- */
  /* overlays: focus trapping shared by drawer, modal and lightbox            */
  /* ---------------------------------------------------------------------- */
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  let lastFocus = null;

  // Closing an overlay must put focus somewhere sensible. If whatever opened it
  // is gone or was never focusable (a programmatic click leaves focus on body),
  // fall back to the cart button rather than dropping the user at the top.
  function restoreFocus() {
    const target = (lastFocus && lastFocus.isConnected && lastFocus !== document.body)
      ? lastFocus : $('#cartBtn');
    target && target.focus({ preventScroll: true });
  }

  function trap(container) {
    return e => {
      if (e.key !== 'Tab') return;
      const items = $$(FOCUSABLE, container).filter(el => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
  }

  /* cart drawer ----------------------------------------------------------- */
  const drawer = $('#cartDrawer');
  const scrim  = $('#drawerScrim');
  let drawerTrap = null;

  function openDrawer() {
    lastFocus = document.activeElement;
    scrim.hidden = false; drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add('is-open'));
    document.body.classList.add('is-locked');
    drawerTrap = trap(drawer);
    drawer.addEventListener('keydown', drawerTrap);
    $('#cartClose').focus();
  }
  function closeDrawer() {
    drawer.classList.remove('is-open');
    document.body.classList.remove('is-locked');
    drawer.removeEventListener('keydown', drawerTrap);
    setTimeout(() => { drawer.hidden = true; scrim.hidden = true; }, 560);
    restoreFocus();
  }
  cartBtn && cartBtn.addEventListener('click', openDrawer);
  $('#cartClose') && $('#cartClose').addEventListener('click', closeDrawer);
  scrim && scrim.addEventListener('click', closeDrawer);
  $('#cartBrowse') && $('#cartBrowse').addEventListener('click', () => {
    closeDrawer();
    document.getElementById('menu').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' });
  });

  /* ---------------------------------------------------------------------- */
  /* checkout                                                                */
  /* ---------------------------------------------------------------------- */
  const modal = $('#checkoutModal');
  const stepEls = { 1: $('#stepDetails'), 2: $('#stepPayment'), 3: $('#stepTrack') };
  const stepTitles = { 1: 'Delivery details', 2: 'Payment', 3: 'Your order' };
  let step = 1, modalTrap = null, payMethod = 'upi', trackTimers = [];

  const PAY_METHODS = [
    { id: 'upi',  name: 'UPI',  note: 'GPay, PhonePe, Paytm' },
    { id: 'card', name: 'Card', note: 'Visa, Mastercard, Amex' },
    { id: 'net',  name: 'Net banking', note: 'All major banks' },
    { id: 'cash', name: 'Cash', note: 'Pay the rider' }
  ];
  const payMethodsEl = $('#payMethods');
  if (payMethodsEl) {
    payMethodsEl.innerHTML = PAY_METHODS.map(p => `
      <button class="pay-method" type="button" role="radio" data-pay="${p.id}"
              aria-checked="${p.id === payMethod}">
        <strong>${esc(p.name)}</strong><span>${esc(p.note)}</span>
      </button>`).join('');
    payMethodsEl.addEventListener('click', e => {
      const btn = e.target.closest('[data-pay]');
      if (!btn) return;
      payMethod = btn.dataset.pay;
      $$('[data-pay]', payMethodsEl).forEach(b =>
        b.setAttribute('aria-checked', String(b === btn)));
      $('#payCard').hidden = payMethod !== 'card';
      $('#payUpi').hidden  = payMethod !== 'upi';
      $('#payCash').hidden = payMethod !== 'cash';
    });
  }

  function showStep(n) {
    step = n;
    Object.entries(stepEls).forEach(([k, el]) => el && el.classList.toggle('is-on', +k === n));
    $$('#checkoutSteps .step').forEach((s, i) => s.classList.toggle('is-on', i < n));
    $('#checkoutStepLabel').textContent = `Step ${n} of 3`;
    $('#checkoutTitle').textContent = stepTitles[n];
    const first = $(FOCUSABLE, stepEls[n]);
    first && first.focus({ preventScroll: true });
  }

  function openCheckout() {
    if (!cart.length) { toast('Your order is empty'); return; }
    lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add('is-locked');
    modalTrap = trap(modal);
    modal.addEventListener('keydown', modalTrap);
    renderCart();
    showStep(1);
    $('#payUpi').hidden = payMethod !== 'upi';
  }
  function closeCheckout() {
    modal.hidden = true;
    document.body.classList.remove('is-locked');
    modal.removeEventListener('keydown', modalTrap);
    trackTimers.forEach(clearTimeout); trackTimers = [];
    restoreFocus();
  }
  $('#checkoutBtn') && $('#checkoutBtn').addEventListener('click', () => {
    closeDrawer(); setTimeout(openCheckout, 200);
  });
  $$('[data-close]', modal).forEach(b => b.addEventListener('click', closeCheckout));
  $$('[data-back]', modal).forEach(b => b.addEventListener('click', () => showStep(step - 1)));

  /* validation ------------------------------------------------------------ */
  function setError(input, msg) {
    const field = input.closest('.field');
    const err = field && $(`.field-error[data-for="${input.id}"]`, field);
    field && field.classList.toggle('is-invalid', !!msg);
    if (err) err.textContent = msg || '';
    if (msg) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
    return !msg;
  }
  const required = (input, msg) => setError(input, input.value.trim() ? '' : msg);
  const emailOk  = v => /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i.test(v.trim());
  const phoneOk  = v => (v.replace(/\D/g, '').length >= 10);

  function luhn(num) {
    const s = num.replace(/\D/g, '');
    if (s.length < 12) return false;
    let sum = 0, alt = false;
    for (let i = s.length - 1; i >= 0; i--) {
      let d = +s[i];
      if (alt) { d *= 2; if (d > 9) d -= 9; }
      sum += d; alt = !alt;
    }
    return sum % 10 === 0;
  }

  // input masks
  const cardNum = $('#cardNum');
  cardNum && cardNum.addEventListener('input', () => {
    const v = cardNum.value.replace(/\D/g, '').slice(0, 19);
    cardNum.value = v.replace(/(.{4})/g, '$1 ').trim();
  });
  const cardExp = $('#cardExp');
  cardExp && cardExp.addEventListener('input', () => {
    const v = cardExp.value.replace(/\D/g, '').slice(0, 4);
    cardExp.value = v.length > 2 ? v.slice(0, 2) + ' / ' + v.slice(2) : v;
  });
  const cardCvc = $('#cardCvc');
  cardCvc && cardCvc.addEventListener('input', () => {
    cardCvc.value = cardCvc.value.replace(/\D/g, '').slice(0, 4);
  });
  const cPin = $('#cPin');
  cPin && cPin.addEventListener('input', () => {
    cPin.value = cPin.value.replace(/\D/g, '').slice(0, 6);
  });

  /* step 1 ---------------------------------------------------------------- */
  $('#stepDetails') && $('#stepDetails').addEventListener('submit', e => {
    e.preventDefault();
    const name = $('#cName'), phone = $('#cPhone'), addr = $('#cAddress'), pin = $('#cPin');
    const ok = [
      required(name, 'We need a name for the order.'),
      setError(phone, !phone.value.trim() ? 'A phone number, so the rider can reach you.'
        : phoneOk(phone.value) ? '' : 'That does not look like a ten-digit number.'),
      required(addr, 'Where are we delivering to?'),
      setError(pin, pin.value.length === 6 ? '' : 'Six digits, please.')
    ].every(Boolean);
    if (ok) showStep(2);
  });

  /* step 2 ---------------------------------------------------------------- */
  $('#stepPayment') && $('#stepPayment').addEventListener('submit', e => {
    e.preventDefault();
    let ok = true;
    if (payMethod === 'card') {
      const exp = $('#cardExp').value.replace(/\D/g, '');
      const mm = +exp.slice(0, 2), yy = +exp.slice(2);
      const now = new Date();
      const expOk = exp.length === 4 && mm >= 1 && mm <= 12 &&
        (2000 + yy > now.getFullYear() ||
         (2000 + yy === now.getFullYear() && mm >= now.getMonth() + 1));
      ok = [
        setError(cardNum, luhn(cardNum.value) ? '' : 'Check that card number.'),
        setError(cardExp, expOk ? '' : 'Use MM / YY, and a date in the future.'),
        setError(cardCvc, cardCvc.value.length >= 3 ? '' : 'Three or four digits.')
      ].every(Boolean);
    } else if (payMethod === 'upi') {
      const upi = $('#upiId');
      ok = setError(upi, /^[\w.\-]{2,}@[a-zA-Z]{2,}$/.test(upi.value.trim())
        ? '' : 'A UPI ID looks like yourname@bank.');
    }
    if (!ok) return;

    const btn = $('#payBtn');
    btn.classList.add('is-busy');
    btn.textContent = 'Authorising…';
    setTimeout(() => {
      btn.classList.remove('is-busy');
      btn.innerHTML = 'Pay <span id="payAmount">' + money(totals().total) + '</span>';
      startTracking();
      showStep(3);
    }, 1400);
  });

  /* step 3: delivery tracking --------------------------------------------- */
  const TRACK = [
    { label: 'Order confirmed',            note: 'Paid and sent to the kitchen' },
    { label: 'In the kitchen',             note: 'On the fire now' },
    { label: 'Packed and picked up',       note: 'Sealed in insulated ceramic' },
    { label: 'Out for delivery',           note: 'Arun is on the way' },
    { label: 'Delivered',                  note: 'Enjoy it while it is hot' }
  ];

  function startTracking() {
    const list = $('#trackList');
    const rider = $('#riderCard');
    if (!list) return;
    trackTimers.forEach(clearTimeout); trackTimers = [];

    $('#orderId').textContent = '#AU' + Math.floor(100000 + Math.random() * 899999);
    $('#orderEta').textContent = 'Arriving in about 34 minutes';
    rider.hidden = true;

    list.innerHTML = `<span class="track-fill" aria-hidden="true"></span>` + TRACK.map((s, i) => `
      <li${i === 0 ? ' class="is-now"' : ''}>
        <span class="track-label">${esc(s.label)}</span>
        <span class="track-time">${esc(s.note)}</span>
      </li>`).join('');

    const lis = $$('li', list);
    const fill = $('.track-fill', list);
    // demo pacing: the five stages play out over about twelve seconds
    const gap = reduced ? 600 : 2600;
    TRACK.forEach((s, i) => {
      if (i === 0) return;
      trackTimers.push(setTimeout(() => {
        lis[i - 1].classList.remove('is-now');
        lis[i - 1].classList.add('is-done');
        lis[i].classList.add('is-now');
        if (fill) fill.style.height = ((i / (TRACK.length - 1)) * 100) + '%';
        if (i === 3) rider.hidden = false;
        if (i === TRACK.length - 1) {
          lis[i].classList.remove('is-now');
          lis[i].classList.add('is-done');
          $('#orderEta').textContent = 'Delivered — thank you';
          cart = []; promo = null; renderCart();
        }
      }, gap * i));
    });
  }
  $('#trackDone') && $('#trackDone').addEventListener('click', closeCheckout);

  /* ---------------------------------------------------------------------- */
  /* reviews carousel                                                        */
  /* ---------------------------------------------------------------------- */
  const track = $('#reviewTrack');
  const dotsEl = $('#reviewDots');
  let rIndex = 0, rTimer = null;

  if (track) {
    track.innerHTML = D.REVIEWS.map(r => `
      <li class="review-card">
        <div class="review-avatar">${img(r.avatar, 'Portrait medallion for ' + esc(r.name), 320, 320)}</div>
        <div>
          <span class="stars" role="img" aria-label="Rated ${r.rating} out of 5">
            ${'<svg class="i"><use href="#i-star"/></svg>'.repeat(r.rating)}
          </span>
          <p class="review-quote">${esc(r.quote)}</p>
          <div class="review-meta">
            <span class="review-name">${esc(r.name)}</span>
            <span class="review-role">${esc(r.role)}</span>
            <span class="review-dish">${esc(r.dish)}</span>
            <span class="review-date">${esc(r.date)}</span>
          </div>
        </div>
      </li>`).join('');

    dotsEl.innerHTML = D.REVIEWS.map((_, i) => `
      <button class="review-dot" type="button" role="tab" data-i="${i}"
              aria-selected="${i === 0}" aria-label="Review ${i + 1}"></button>`).join('');

    const go = i => {
      rIndex = (i + D.REVIEWS.length) % D.REVIEWS.length;
      track.style.transform = `translateX(-${rIndex * 100}%)`;
      $$('.review-dot', dotsEl).forEach((d, n) =>
        d.setAttribute('aria-selected', String(n === rIndex)));
    };
    const auto = () => {
      if (reduced) return;
      clearInterval(rTimer);
      rTimer = setInterval(() => go(rIndex + 1), 7000);
    };

    $('#reviewNext').addEventListener('click', () => { go(rIndex + 1); auto(); });
    $('#reviewPrev').addEventListener('click', () => { go(rIndex - 1); auto(); });
    dotsEl.addEventListener('click', e => {
      const d = e.target.closest('[data-i]');
      if (d) { go(+d.dataset.i); auto(); }
    });

    const stage = $('#reviewViewport');
    stage.addEventListener('mouseenter', () => clearInterval(rTimer));
    stage.addEventListener('mouseleave', auto);
    stage.addEventListener('focusin', () => clearInterval(rTimer));

    // swipe
    let x0 = null;
    stage.addEventListener('touchstart', e => (x0 = e.touches[0].clientX), { passive: true });
    stage.addEventListener('touchend', e => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 45) { go(rIndex + (dx < 0 ? 1 : -1)); auto(); }
      x0 = null;
    });
    auto();
  }

  /* ---------------------------------------------------------------------- */
  /* gallery + lightbox                                                      */
  /* ---------------------------------------------------------------------- */
  const galleryGrid = $('#galleryGrid');
  const galleryFilters = $('#galleryFilters');
  const lightbox = $('#lightbox');
  let lbIndex = 0, lbList = [];

  if (galleryGrid) {
    galleryGrid.innerHTML = D.GALLERY.map((g, i) => `
      <button class="gallery-item ${g.span ? 'span-' + g.span : ''} reveal" type="button"
              data-i="${i}" data-cat="${g.cat}" data-delay="${(i % 4) * 60}"
              aria-label="Open: ${esc(g.caption)}">
        ${img(g.img, '', 1200, 900)}
        <span class="gallery-cap">${esc(g.caption)}</span>
      </button>`).join('');

    const cats = [
      { id: 'all', name: 'Everything' },
      { id: 'food', name: 'The plates' },
      { id: 'interior', name: 'The room' },
      { id: 'kitchen', name: 'The kitchen' }
    ];
    galleryFilters.innerHTML = cats.map(c => `
      <button class="filter-chip" type="button" data-gcat="${c.id}"
              aria-pressed="${c.id === 'all'}">${esc(c.name)}</button>`).join('');

    galleryFilters.addEventListener('click', e => {
      const btn = e.target.closest('[data-gcat]');
      if (!btn) return;
      const cat = btn.dataset.gcat;
      $$('[data-gcat]', galleryFilters).forEach(b =>
        b.setAttribute('aria-pressed', String(b === btn)));
      $$('.gallery-item', galleryGrid).forEach(it =>
        it.classList.toggle('is-hidden', cat !== 'all' && it.dataset.cat !== cat));
    });

    galleryGrid.addEventListener('click', e => {
      const it = e.target.closest('.gallery-item');
      if (it) openLightbox(+it.dataset.i);
    });
  }

  function visibleGallery() {
    return $$('.gallery-item:not(.is-hidden)', galleryGrid).map(el => +el.dataset.i);
  }
  function paintLightbox() {
    const g = D.GALLERY[lbList[lbIndex]];
    $('#lbImg').src = `assets/img/${g.img}.jpg`;
    $('#lbImg').alt = g.caption;
    $('#lbCap').textContent = g.caption;
  }
  function openLightbox(i) {
    lbList = visibleGallery();
    lbIndex = Math.max(0, lbList.indexOf(i));
    lastFocus = document.activeElement;
    lightbox.hidden = false;
    document.body.classList.add('is-locked');
    paintLightbox();
    $('.lb-close', lightbox).focus();
  }
  function closeLightbox() {
    lightbox.hidden = true;
    document.body.classList.remove('is-locked');
    restoreFocus();
  }
  if (lightbox) {
    $$('[data-close]', lightbox).forEach(b => b.addEventListener('click', closeLightbox));
    $('#lbNext').addEventListener('click', () => { lbIndex = (lbIndex + 1) % lbList.length; paintLightbox(); });
    $('#lbPrev').addEventListener('click', () => { lbIndex = (lbIndex - 1 + lbList.length) % lbList.length; paintLightbox(); });
    lightbox.addEventListener('click', e => { if (e.target === lightbox) closeLightbox(); });
  }

  /* global keyboard ------------------------------------------------------- */
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (lightbox && !lightbox.hidden) return closeLightbox();
      if (modal && !modal.hidden) return closeCheckout();
      if (drawer && !drawer.hidden) return closeDrawer();
      if (nav && nav.classList.contains('is-open')) return closeNav();
    }
    if (lightbox && !lightbox.hidden) {
      if (e.key === 'ArrowRight') $('#lbNext').click();
      if (e.key === 'ArrowLeft')  $('#lbPrev').click();
    }
  });

  /* ---------------------------------------------------------------------- */
  /* reservation                                                             */
  /* ---------------------------------------------------------------------- */
  const rDate = $('#rDate');
  const rTime = $('#rTime');
  const guestOut = $('#guestOut');
  let guests = 2;

  const SLOTS = ['12:30', '13:00', '13:30', '18:30', '19:00', '19:30', '20:00', '20:30', '21:00', '21:30'];
  const pretty = t => {
    const [h, m] = t.split(':').map(Number);
    const ap = h >= 12 ? 'pm' : 'am';
    const hh = h % 12 || 12;
    return `${hh}.${String(m).padStart(2, '0')}${ap}`;
  };

  if (rDate) {
    const today = new Date();
    const iso = d => d.toISOString().slice(0, 10);
    rDate.min = iso(today);
    rDate.max = iso(new Date(today.getTime() + 120 * 864e5));
    rDate.value = iso(new Date(today.getTime() + 864e5));
  }
  if (rTime) {
    rTime.innerHTML = SLOTS.map(s =>
      `<option value="${s}"${s === '20:00' ? ' selected' : ''}>${pretty(s)}</option>`).join('');
  }

  function paintGuests() {
    if (guestOut) guestOut.textContent = guests + (guests === 1 ? ' guest' : ' guests');
    const minus = $('#guestMinus'), plus = $('#guestPlus');
    if (minus) minus.disabled = guests <= 1;
    if (plus) plus.disabled = guests >= 12;
    const hint = $('#guestHint');
    if (hint) {
      hint.textContent = guests >= 9
        ? 'For nine or more we will call you to arrange the private room.'
        : 'Tables of nine or more are handled by our events team.';
    }
  }
  $('#guestMinus') && $('#guestMinus').addEventListener('click', () => { guests = Math.max(1, guests - 1); paintGuests(); });
  $('#guestPlus')  && $('#guestPlus').addEventListener('click',  () => { guests = Math.min(12, guests + 1); paintGuests(); });
  paintGuests();

  const OCCASIONS = ['Just dinner', 'Birthday', 'Anniversary', 'Business', 'Celebration'];
  let occasion = '';
  const occRow = $('#occasionRow');
  if (occRow) {
    occRow.innerHTML = OCCASIONS.map(o =>
      `<button class="occ-chip" type="button" data-occ="${esc(o)}" aria-pressed="false">${esc(o)}</button>`).join('');
    occRow.addEventListener('click', e => {
      const b = e.target.closest('[data-occ]');
      if (!b) return;
      const on = b.getAttribute('aria-pressed') === 'true';
      $$('[data-occ]', occRow).forEach(x => x.setAttribute('aria-pressed', 'false'));
      b.setAttribute('aria-pressed', String(!on));
      occasion = on ? '' : b.dataset.occ;
    });
  }

  const reserveForm = $('#reserveForm');
  reserveForm && reserveForm.addEventListener('submit', e => {
    e.preventDefault();
    const name = $('#rName'), phone = $('#rPhone'), email = $('#rEmail');
    const ok = [
      setError(rDate, rDate.value ? '' : 'Pick a date.'),
      setError(rTime, rTime.value ? '' : 'Pick a time.'),
      required(name, 'Who is the table for?'),
      setError(phone, !phone.value.trim() ? 'A number, in case anything changes.'
        : phoneOk(phone.value) ? '' : 'That does not look like a ten-digit number.'),
      setError(email, emailOk(email.value) ? '' : 'We send the confirmation here.')
    ].every(Boolean);
    if (!ok) {
      const bad = $('.field.is-invalid input, .field.is-invalid select', reserveForm);
      bad && bad.focus();
      return;
    }

    const btn = $('#reserveSubmit');
    btn.classList.add('is-busy');
    btn.textContent = 'Checking the book…';
    setTimeout(() => {
      const d = new Date(rDate.value + 'T12:00:00');
      const when = d.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
      $('#reserveSummary').textContent =
        `${when} at ${pretty(rTime.value)}, for ${guests} ${guests === 1 ? 'guest' : 'guests'}` +
        (occasion && occasion !== 'Just dinner' ? ` · ${occasion.toLowerCase()}` : '') + '.';
      reserveForm.hidden = true;
      $('#reserveDone').hidden = false;
      toast('Table confirmed. See you soon.');
    }, 1300);
  });

  $('#reserveAgain') && $('#reserveAgain').addEventListener('click', () => {
    const btn = $('#reserveSubmit');
    btn.classList.remove('is-busy');
    btn.innerHTML = 'Confirm reservation <svg class="i"><use href="#i-arrow"/></svg>';
    reserveForm.reset();
    reserveForm.hidden = false;
    $('#reserveDone').hidden = true;
    guests = 2; paintGuests();
    if (rTime) rTime.value = '20:00';
    if (rDate) rDate.value = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
    $$('.field.is-invalid', reserveForm).forEach(f => f.classList.remove('is-invalid'));
    reserveForm.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  });

  /* ---------------------------------------------------------------------- */
  /* opening hours                                                           */
  /* ---------------------------------------------------------------------- */
  function mumbaiNow() {
    // the restaurant's clock, not the visitor's
    try {
      return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    } catch (e) { return new Date(); }
  }
  const mins = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };

  function openState() {
    const now = mumbaiNow();
    const dow = now.getDay();                       // 0 = Sunday
    const cur = now.getHours() * 60 + now.getMinutes();
    const idx = (dow + 6) % 7;                      // our list starts on Monday
    const today = D.RESTAURANT.hours[idx];
    const yday = D.RESTAURANT.hours[(idx + 6) % 7];

    // a close time before the open time means it runs past midnight
    if (yday.open && mins(yday.close) < mins(yday.open) && cur < mins(yday.close)) {
      return { open: true, today, idx, closes: yday.close };
    }
    if (!today.open) return { open: false, today, idx };
    const o = mins(today.open), c = mins(today.close);
    const isOpen = c < o ? cur >= o : (cur >= o && cur < c);
    return { open: isOpen, today, idx, closes: today.close };
  }

  const hoursList = $('#hoursList');
  const openPill = $('#openPill');
  const heroHours = $('#heroHours');

  function paintHours() {
    const st = openState();
    if (hoursList) {
      hoursList.innerHTML = D.RESTAURANT.hours.map((h, i) => `
        <li class="${i === st.idx ? 'is-today' : ''}">
          <span class="hours-day">${esc(h.day)}</span>
          <span class="hours-time">${h.open ? pretty(h.open) + ' – ' + pretty(h.close) : 'Closed'}</span>
        </li>`).join('');
    }
    if (openPill) {
      openPill.textContent = st.open ? 'Open now' : 'Closed';
      openPill.classList.toggle('is-open', st.open);
      openPill.classList.toggle('is-shut', !st.open);
    }
    if (heroHours) {
      const span = $('span', heroHours);
      if (span) {
        span.innerHTML = st.open
          ? `<strong>Open now</strong> until ${pretty(st.closes)}`
          : (st.today.open
              ? `<strong>Opens</strong> ${pretty(st.today.open)} today`
              : `<strong>Closed</strong> Mondays`);
      }
    }
  }
  paintHours();
  setInterval(paintHours, 60000);

  /* ---------------------------------------------------------------------- */
  /* faq                                                                     */
  /* ---------------------------------------------------------------------- */
  const faqList = $('#faqList');
  if (faqList) {
    faqList.innerHTML = D.FAQ.map((f, i) => `
      <div class="faq-item">
        <button class="faq-q" type="button" aria-expanded="false" aria-controls="faq-a-${i}" id="faq-q-${i}">
          ${esc(f.q)} <svg class="i"><use href="#i-chev"/></svg>
        </button>
        <div class="faq-a" id="faq-a-${i}" role="region" aria-labelledby="faq-q-${i}">
          <p>${esc(f.a)}</p>
        </div>
      </div>`).join('');

    faqList.addEventListener('click', e => {
      const q = e.target.closest('.faq-q');
      if (!q) return;
      const item = q.closest('.faq-item');
      const panel = $('.faq-a', item);
      const open = q.getAttribute('aria-expanded') === 'true';

      $$('.faq-item.is-open', faqList).forEach(other => {
        if (other === item) return;
        other.classList.remove('is-open');
        $('.faq-q', other).setAttribute('aria-expanded', 'false');
        $('.faq-a', other).style.height = '0px';
      });

      q.setAttribute('aria-expanded', String(!open));
      item.classList.toggle('is-open', !open);
      panel.style.height = open ? '0px' : panel.scrollHeight + 'px';
    });
  }

  /* ---------------------------------------------------------------------- */
  /* map facade, newsletter, misc                                            */
  /* ---------------------------------------------------------------------- */
  $('#loadMap') && $('#loadMap').addEventListener('click', () => {
    const wrap = $('.visit-map');
    const { lat, lng, name } = D.RESTAURANT;
    wrap.innerHTML =
      `<iframe title="Map showing Aurelia at 14 Ashford Lane, Bandra West, Mumbai" loading="lazy"
               referrerpolicy="no-referrer-when-downgrade"
               src="https://www.google.com/maps?q=${lat},${lng}&z=16&output=embed"></iframe>`;
  });

  const newsForm = $('#newsForm');
  newsForm && newsForm.addEventListener('submit', e => {
    e.preventDefault();
    const input = $('#newsEmail'), msg = $('#newsMsg');
    if (!emailOk(input.value)) {
      msg.textContent = 'That address does not look right.';
      msg.classList.add('is-error');
      input.focus();
      return;
    }
    msg.textContent = 'Thank you — the next note goes out on Saturday.';
    msg.classList.remove('is-error');
    input.value = '';
  });

  const yearEl = $('#year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // smooth-scroll with a header offset for same-page links
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const id = a.getAttribute('href');
    if (id === '#' || id.length < 2) return;
    const target = document.getElementById(id.slice(1));
    if (!target) return;
    e.preventDefault();
    const top = target.getBoundingClientRect().top + window.scrollY -
                (parseInt(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 78) - 14;
    window.scrollTo({ top, behavior: reduced ? 'auto' : 'smooth' });
    history.replaceState(null, '', id);
  });

  renderMenu();
  renderCart();
  observeReveals();
  M && M.init();

  // anything injected after first paint still needs observing
  const mo = new MutationObserver(() => { observeReveals(); M && M.init(); });
  mo.observe(document.body, { childList: true, subtree: true });
})();
