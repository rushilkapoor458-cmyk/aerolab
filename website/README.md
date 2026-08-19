# Aurelia — premium restaurant website

A complete, production-shaped marketing and ordering site for a fictional
contemporary fire kitchen in Bandra West, Mumbai. Warm ivory ground, deep olive
ink, brass used sparingly, and hand-painted watercolour illustration throughout. Static HTML, CSS and vanilla
JavaScript: no framework, no runtime dependencies, and nothing to install to work
on it. There is one optional build command for deployment — see
[Production build](#production-build) — but nothing needs it.

Open `index.html` directly, or serve the folder:

```bash
python3 -m http.server 8000    # then visit http://localhost:8000/
```

## What is here

| Path | |
|---|---|
| `index.html` | The whole page — eleven sections, plus cart, checkout and lightbox overlays |
| `assets/css/style.css` | Typefaces, design system and every component, in one commented file |
| `assets/js/data.js` | All content: menu, reviews, gallery, hours, FAQ. Edit copy here |
| `assets/js/main.js` | All behaviour |
| `assets/js/motion.js` | The animation layer — optional, the site works without it |
| `assets/img/` | Generated imagery (see below) |
| `tools/generate_assets.py` | The renderer that produces every image |
| `tools/fetch_fonts.sh` | Refreshes the self-hosted webfonts |
| `tools/measure_fallback.js` | Re-measures the metric-matched font fallbacks |
| `tools/build.py` | Optional production build — see below |
| `tools/build_artifact.py` | Optional single-file build (everything inlined) |

## Sections

Hero · signature dishes · about and chef · interactive menu · why choose us ·
reviews · gallery · reservations · online ordering · contact · footer.

The ordering flow is real UI against local state: add to cart, quantity edits,
promo codes (`FIRSTFIRE`, `ASHFORD20`), a three-step checkout with UPI / card /
net banking / cash, client-side card validation including a Luhn check, and an
animated delivery tracker. **No payment is processed and nothing is sent
anywhere** — the cart persists in `localStorage` and that is all. Point
`stepPayment`'s submit handler at your real payment provider to make it live.

## Palette

One light theme, committed to rather than defaulted into: the page is paper, so
it paints its own ground and every colour comes from a token on `:root`.

| Token | | |
|---|---|---|
| `--paper` | `#F5F1E8` | warm ivory ground |
| `--surface` | `#FBF9F3` | cards, a shade above the ground |
| `--ink` | `#23261F` | deep olive-black, the darkest text |
| `--olive` | `#5E6749` | the accent: buttons, rules, small caps |
| `--brass` | `#7E5C22` | the metal note, safe at body sizes |
| `--brass-warm` | `#96702F` | warmer, display sizes only |

None of the neutrals are true greys — each carries a little of the olive, which
is what keeps the page reading as paper rather than as a UI. Contrast was
computed against **every** surface a colour sits on, not just the lightest:
`--brass` splits into two tokens for exactly this reason, since the warmer one
clears 3:1 for display type but not 4.5:1 for body copy.

## Motion

`assets/js/motion.js` holds everything decorative. It is loaded before `main.js`,
which calls into it only when it is present, so deleting the file degrades the
site to a static but fully working page.

- **Headlines rise word by word** behind an overflow mask, staggered, with one
  slow sweep of light across the hero once it settles. Splitting is done at word
  level, never character level — a screen reader spelling out a headline is a
  real cost for a decorative gain.
- **Filtering the menu is a FLIP animation.** Cards that survive a filter change
  are measured before and after the re-render and animate between the two
  positions, so the grid rearranges itself instead of blinking.
- **Adding a dish flies it to the cart** along an arc, and the cart badge springs.
- **Cards lean towards the pointer** in 3D and carry a specular sheen with it.
- **The primary buttons are magnetic**, and the dark bands carry a warm pool of
  light that tracks the cursor.
- **Images wipe open** rather than fading, and the marquee leans with scroll
  velocity.

All of it is transform and opacity only, all of it is behind
`prefers-reduced-motion`, and the pointer effects are behind `pointer: fine` so
they never fire on touch.

One trap worth recording: the wipe is `clip-path: inset(0 0 100% 0)`, and an
element that clips itself reports `intersectionRatio: 0` to IntersectionObserver
no matter where it is on screen. Observing the element to decide when to un-clip
it can therefore never fire. `motion.js` observes the parent instead.

## Editing content

Everything a restaurant would actually change lives in `assets/js/data.js`:
dish names, descriptions, prices, dietary tags, opening hours, reviews, FAQ,
address and phone numbers. Prices are plain numbers in rupees; the currency
formatting is applied once, in `main.js`.

If you change the address, update the three places outside the data file too:
the `Restaurant` JSON-LD block in `index.html`, the `<meta>` description, and
`sitemap.xml`.

## About the imagery

Every image is painted by `tools/generate_assets.py`. Nothing here imitates a
camera: each one is a flat, top-down watercolour — translucent washes that darken
where they overlap, pigment pooling at the edges of each shape, granulating into
the tooth of the paper.

That is the second attempt. The first tried to fake photographs — height fields
shaded under a key light, graded like a dark restaurant shot — and landed in the
uncanny valley. Trying harder would not have fixed it, because the failure was
one of direction rather than execution: a render that is *almost* a photograph
reads as a broken photograph, while a drawing that is confidently a drawing reads
as art direction. Removing every camera cue (perspective, specular highlights,
depth of field) is what made the images work.

They still ship with no stock-photo licensing and no third-party requests, and
they are still designed to be thrown away. Drop a real photograph at the same
path and the page picks it up with no code change:

```
assets/img/dish-scallop.jpg      + dish-scallop.webp     4:3, ~1200px wide
assets/img/hero-{900,1400,2000}  + .webp                 wide, empty on the left
assets/img/interior-*.jpg        + .webp
```

Filenames are referenced by the `img` key on each menu item in `data.js` and by
the `GALLERY` list. Ship both `.jpg` and `.webp`, or delete the `<source>` line
in `main.js`'s `img()` helper if you only have JPEGs.

Two deliberate choices worth knowing about:

- **No people are depicted.** A procedurally generated human reads as a cartoon
  and undercuts everything around it, so the chef is introduced in words and the
  story section is carried by a painting of the coal bed instead.
- **Review avatars are drawn monograms**, not invented faces. Swap them for real
  customer photos when you have consent to use them.

Regenerate the whole set with:

```bash
pip install pillow numpy
python3 tools/generate_assets.py
```

## Production build

Development needs no build: open `index.html` and it works. For deployment there
is one optional command.

```bash
python3 tools/build.py     # writes dist/
```

It inlines and minifies the stylesheet into the document and copies the assets.
That is the whole build. On a single-page site the stylesheet is the entire
critical path, and removing that one round trip is worth about a second of First
Contentful Paint on a slow connection. Scripts stay external — they are
deferred, so they never block the first paint, and external means cacheable.

`dist/` is generated and not tracked. Develop against `index.html`, deploy
`dist/`.

### Single-file build

```bash
python3 tools/build_artifact.py     # writes dist-single/aurelia.html
```

Folds the stylesheet, the webfonts, the scripts and all 39 images into one
2.5 MB `.html` that runs with **zero network requests** — useful for emailing a
copy, opening it from a USB stick, or publishing somewhere that only accepts a
single file. Three things change out of necessity: webp only (the jpg fallbacks
would double the payload), one hero width instead of three (srcset cannot pick a
smaller file when they are all already in the document), and the Google Maps
embed becomes a link, since a cross-origin iframe cannot load from a `file://`
document or under a strict CSP.

## Performance, SEO and accessibility

Lighthouse 13, mobile preset, run against `dist/` served with gzip and cache
headers (what any real host does — the numbers are meaningfully worse without
compression, which is a hosting setting, not a code one). Stable across three
consecutive runs:

| | |
|---|---|
| Performance | **95** |
| Accessibility | **100** |
| Best Practices | **100** |
| SEO | **100** |

First Contentful Paint 1.7 s · Largest Contentful Paint 2.8 s · Total Blocking
Time 40 ms · **Cumulative Layout Shift 0.008**.

Getting CLS down took two specific fixes. Webfonts swapping in used to reflow the
hero for 0.204 of shift, so the two faces that set most of the visible text are
preloaded, and `style.css` carries metric-matched `@font-face` fallbacks —
`size-adjust`, `ascent-override` and `descent-override` measured against the
shipped woff2 files by `tools/measure_fallback.js`, not guessed. The hero is also
served at three widths so a phone does not download and decode a 2000px image to
show it 390px wide.

Also true of the build:

- No third-party requests at all. Fonts are self-hosted and subsetted to latin
  and latin-ext; the Google Maps embed sits behind a click-to-load facade.
- Every below-fold image is lazy and carries intrinsic dimensions.
- **axe-core reports zero violations** on desktop and mobile, and with the cart
  drawer, checkout modal and lightbox open.
- Focus is trapped inside every overlay, Escape closes them, and focus returns to
  whatever opened them.
- `prefers-reduced-motion` disables every animation described above, including
  the Ken Burns hero, the marquee, parallax, reveals and count-ups. Verified:
  zero running animations, and the headline is never even split.
- Structured data: `Restaurant` (with hours, geo, rating and menu) and `FAQPage`.
  `sitemap.xml`, `robots.txt` and a web manifest are included.

Replace `https://aurelia.example/` with the real domain in `index.html`
(canonical, Open Graph, JSON-LD), `sitemap.xml` and `robots.txt` before launch.

## Browser support

Evergreen Chrome, Edge, Firefox and Safari. Uses `backdrop-filter` (with an
opaque fallback), `aspect-ratio`, `svh` units and `IntersectionObserver` (with a
no-observer fallback that simply shows all content).
