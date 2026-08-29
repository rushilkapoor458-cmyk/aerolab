/* =============================================================================
   AURELIA — motion layer
   -----------------------------------------------------------------------------
   Everything here is decoration. main.js checks for window.AureliaMotion and
   works without it, and every routine below returns immediately under
   prefers-reduced-motion, so the site stays usable if this file never loads.

   Two rules hold throughout:
     · animate transform and opacity only, never layout properties;
     · never change what the DOM says, only how it arrives.
   ========================================================================== */

window.AureliaMotion = (function () {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finePointer = window.matchMedia('(pointer: fine)').matches;
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const EASE = 'cubic-bezier(.16, 1, .3, 1)';
  const SPRING = 'cubic-bezier(.34, 1.4, .64, 1)';

  /* ---------------------------------------------------------------------- */
  /* split text — words wrapped in masked spans so lines rise into view      */
  /* ---------------------------------------------------------------------- */
  /* Word level, never character level: a screen reader announcing a headline
     one letter at a time is a real cost for a decorative gain.              */

  function splitWords(el) {
    if (el.dataset.split === 'done') return;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walker.nextNode()) {
      if (walker.currentNode.nodeValue.trim()) texts.push(walker.currentNode);
    }
    texts.forEach(node => {
      const frag = document.createDocumentFragment();
      node.nodeValue.split(/(\s+)/).forEach(chunk => {
        if (!chunk) return;
        if (!chunk.trim()) { frag.appendChild(document.createTextNode(chunk)); return; }
        const mask = document.createElement('span');
        mask.className = 'w';
        const inner = document.createElement('span');
        inner.className = 'w-i';
        inner.textContent = chunk;
        mask.appendChild(inner);
        frag.appendChild(mask);
      });
      node.parentNode.replaceChild(frag, node);
    });
    el.dataset.split = 'done';
  }

  function playWords(el, { stagger = 46, delay = 0 } = {}) {
    $$('.w-i', el).forEach((w, i) => {
      w.style.transitionDelay = (delay + i * stagger) + 'ms';
    });
    el.classList.add('is-lit');
  }

  /*
   * init() is called again for anything injected after first paint, and
   * main.js drives that from a MutationObserver — which countUp's per-frame
   * text writes trigger. One observer is built once and reused, or the page
   * would accumulate a fresh one on every animated frame.
   */
  let splitIO = null;

  function initSplitReveal() {
    const targets = $$('[data-split-reveal]');
    if (reduced) { targets.forEach(t => t.classList.add('is-lit')); return; }
    if (!('IntersectionObserver' in window)) {
      targets.forEach(t => t.classList.add('is-lit'));
      return;
    }
    if (!splitIO) {
      splitIO = new IntersectionObserver((entries, obs) => {
        entries.forEach(e => {
          if (!e.isIntersecting) return;
          playWords(e.target, { stagger: +(e.target.dataset.stagger || 46) });
          obs.unobserve(e.target);
        });
      }, { threshold: 0.25, rootMargin: '0px 0px -10% 0px' });
    }
    targets.forEach(t => {
      // Splitting twice would shred the words already in the DOM.
      if (t.dataset.splitDone === '1') return;
      splitWords(t);
      t.dataset.splitDone = '1';
      splitIO.observe(t);
    });
  }

  /* ---------------------------------------------------------------------- */
  /* FLIP — filtering the menu reorders cards instead of blinking them       */
  /* ---------------------------------------------------------------------- */

  function flip(container, mutate, { key = 'id', duration = 620 } = {}) {
    if (reduced || !container || !container.animate) { mutate(); return; }

    const before = new Map();
    $$('[data-' + key + ']', container).forEach(el =>
      before.set(el.dataset[key], el.getBoundingClientRect()));

    mutate();

    const after = $$('[data-' + key + ']', container);
    after.forEach((el, i) => {
      const from = before.get(el.dataset[key]);
      const to = el.getBoundingClientRect();
      if (from) {
        const dx = from.left - to.left;
        const dy = from.top - to.top;
        if (!dx && !dy) return;
        el.style.animation = 'none';           // clear the entry keyframes
        el.animate(
          [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
          { duration, easing: EASE }
        );
      } else {
        // genuinely new to the view — let it grow in, slightly staggered
        el.style.animation = 'none';
        el.animate(
          [{ opacity: 0, transform: 'translateY(26px) scale(.96)' },
           { opacity: 1, transform: 'none' }],
          { duration: duration * 0.8, delay: Math.min(i * 28, 260), easing: EASE, fill: 'backwards' }
        );
      }
    });

    before.forEach((rect, id) => {
      if (after.some(el => el.dataset[key] === id)) return;
      // the card is already gone from the DOM; a ghost carries it off screen
      const ghost = document.createElement('div');
      ghost.setAttribute('aria-hidden', 'true');
      Object.assign(ghost.style, {
        position: 'fixed', left: rect.left + 'px', top: rect.top + 'px',
        width: rect.width + 'px', height: rect.height + 'px',
        borderRadius: '5px', background: 'rgba(28,26,21,.55)',
        pointerEvents: 'none', zIndex: 5
      });
      document.body.appendChild(ghost);
      ghost.animate([{ opacity: .8, transform: 'none' },
                     { opacity: 0, transform: 'scale(.92)' }],
                    { duration: 320, easing: EASE })
           .onfinish = () => ghost.remove();
    });
  }

  /* ---------------------------------------------------------------------- */
  /* fly to cart — the dish leaves the card and lands on the cart button     */
  /* ---------------------------------------------------------------------- */

  function flyToCart(sourceEl, targetEl) {
    if (reduced || !sourceEl || !targetEl || !sourceEl.animate) return;
    const img = sourceEl.querySelector('img');
    if (!img) return;

    const from = img.getBoundingClientRect();
    const to = targetEl.getBoundingClientRect();
    if (!from.width || !to.width) return;

    const clone = img.cloneNode();
    clone.setAttribute('aria-hidden', 'true');
    clone.removeAttribute('loading');
    Object.assign(clone.style, {
      position: 'fixed', left: from.left + 'px', top: from.top + 'px',
      width: from.width + 'px', height: from.height + 'px',
      objectFit: 'cover', borderRadius: '4px', zIndex: 150,
      pointerEvents: 'none', boxShadow: '0 20px 50px -18px rgba(0,0,0,.9)'
    });
    document.body.appendChild(clone);

    const dx = (to.left + to.width / 2) - (from.left + from.width / 2);
    const dy = (to.top + to.height / 2) - (from.top + from.height / 2);

    clone.animate([
      { transform: 'translate(0,0) scale(1) rotate(0deg)', opacity: 1, offset: 0 },
      // lifts and leans before it falls — a straight line reads mechanical
      { transform: `translate(${dx * 0.45}px, ${dy * 0.32 - 90}px) scale(.66) rotate(-7deg)`,
        opacity: .95, offset: .55 },
      { transform: `translate(${dx}px, ${dy}px) scale(.06) rotate(4deg)`, opacity: 0, offset: 1 }
    ], { duration: 820, easing: 'cubic-bezier(.55,.06,.32,1)' }).onfinish = () => clone.remove();
  }

  /* ---------------------------------------------------------------------- */
  /* pointer-driven decoration                                              */
  /* ---------------------------------------------------------------------- */

  /* cards lean towards the cursor and carry a specular sheen with it */
  function initTilt() {
    if (reduced || !finePointer) return;
    let frame = null;

    document.addEventListener('pointermove', e => {
      const card = e.target.closest('[data-tilt]');
      if (!card) return;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width;
        const py = (e.clientY - r.top) / r.height;
        card.style.setProperty('--rx', ((0.5 - py) * 7).toFixed(2) + 'deg');
        card.style.setProperty('--ry', ((px - 0.5) * 9).toFixed(2) + 'deg');
        card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
        card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
        card.classList.add('is-tilting');
      });
    }, { passive: true });

    document.addEventListener('pointerout', e => {
      const card = e.target.closest('[data-tilt]');
      if (!card || card.contains(e.relatedTarget)) return;
      card.classList.remove('is-tilting');
      card.style.removeProperty('--rx');
      card.style.removeProperty('--ry');
    }, { passive: true });
  }

  /* the primary calls to action pull very slightly towards the cursor */
  function initMagnetic() {
    if (reduced || !finePointer) return;
    $$('[data-magnetic]').forEach(btn => {
      let frame = null;
      btn.addEventListener('pointermove', e => {
        if (frame) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const r = btn.getBoundingClientRect();
          const dx = (e.clientX - (r.left + r.width / 2)) / r.width;
          const dy = (e.clientY - (r.top + r.height / 2)) / r.height;
          btn.style.setProperty('--tx', (dx * 11).toFixed(1) + 'px');
          btn.style.setProperty('--ty', (dy * 7).toFixed(1) + 'px');
        });
      }, { passive: true });
      btn.addEventListener('pointerleave', () => {
        btn.style.setProperty('--tx', '0px');
        btn.style.setProperty('--ty', '0px');
      }, { passive: true });
    });
  }

  /* a warm pool of light tracks the cursor across the dark bands */
  function initSpotlight() {
    if (reduced || !finePointer) return;
    const zones = $$('[data-spotlight]');
    if (!zones.length) return;
    let frame = null;
    zones.forEach(zone => {
      zone.addEventListener('pointermove', e => {
        if (frame) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const r = zone.getBoundingClientRect();
          zone.style.setProperty('--sx', (e.clientX - r.left) + 'px');
          zone.style.setProperty('--sy', (e.clientY - r.top) + 'px');
          zone.classList.add('is-lit-zone');
        });
      }, { passive: true });
      zone.addEventListener('pointerleave', () =>
        zone.classList.remove('is-lit-zone'), { passive: true });
    });
  }

  /* ---------------------------------------------------------------------- */
  /* scroll-driven                                                          */
  /* ---------------------------------------------------------------------- */

  /* the marquee leans with scroll velocity, so the page feels like one object */
  function initScrollVelocity() {
    if (reduced) return;
    const track = document.getElementById('marquee');
    if (!track) return;
    let last = window.scrollY, vel = 0, running = false;

    const tick = () => {
      vel *= 0.88;
      track.style.setProperty('--skew', (vel * 0.16).toFixed(2) + 'deg');
      track.style.setProperty('--shift', (vel * 0.9).toFixed(1) + 'px');
      if (Math.abs(vel) > 0.05) requestAnimationFrame(tick);
      else { running = false; track.style.setProperty('--skew', '0deg'); }
    };

    window.addEventListener('scroll', () => {
      const y = window.scrollY;
      vel = Math.max(-40, Math.min(40, y - last));
      last = y;
      if (!running) { running = true; requestAnimationFrame(tick); }
    }, { passive: true });
  }

  /* media wipes open rather than fading */
  let mediaIO = null;
  function initMediaReveal() {
    const media = $$('[data-reveal-media]:not([data-watched])');
    if (reduced || !('IntersectionObserver' in window)) {
      media.forEach(m => m.classList.add('is-open'));
      return;
    }
    // Observe the card, never the clipped element itself. An element carrying
    // clip-path: inset(0 0 100% 0) reports intersectionRatio 0 no matter where it
    // sits on screen, so it can never cross the threshold that would un-clip it.
    if (!mediaIO) {
      mediaIO = new IntersectionObserver((entries, obs) => {
        entries.forEach(e => {
          if (!e.isIntersecting) return;
          $$('[data-reveal-media]', e.target).forEach(m => m.classList.add('is-open'));
          if (e.target.matches('[data-reveal-media]')) e.target.classList.add('is-open');
          obs.unobserve(e.target);
        });
      }, { threshold: 0.15 });
    }
    media.forEach(m => {
      m.dataset.watched = '1';
      mediaIO.observe(m.parentElement || m);
    });
  }

  /* ---------------------------------------------------------------------- */

  // init() is called again every time main.js injects cards. The delegated and
  // per-element pointer handlers must only ever be bound once, or they stack up
  // one deep per re-render and the page slowly grinds.
  let bound = false;
  function init() {
    initSplitReveal();
    initMediaReveal();
    if (bound) return;
    bound = true;
    initTilt();
    initMagnetic();
    initSpotlight();
    initScrollVelocity();
  }

  return { init, flip, flyToCart, splitWords, playWords, reduced, EASE, SPRING };
})();
