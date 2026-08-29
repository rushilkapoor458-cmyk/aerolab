"""
Procedural art director for the AURELIA website.

Every image on the site is painted here — no stock photography, no network
fetch, no licensing question.

An earlier version of this file tried to fake photographs: height fields shaded
under a key light, graded like a dark food shot. It landed in the uncanny
valley. Trying harder was the wrong move, because the failure was one of
direction rather than execution — a render that is *almost* a photograph reads
as a broken photograph, while a drawing that is confidently a drawing reads as
art direction.

So nothing here imitates a camera. Every image is a flat, top-down watercolour:
pigment laid down in translucent washes that darken where they overlap and pool
at their edges, on paper with visible fibre. No perspective, no specular
highlights, no depth of field — none of the cues that made the old images look
like failed photographs rather than deliberate illustration.

Swapping in real photography is still a drop-in: put a file at the same path in
assets/img/ and the site picks it up. See website/README.md.

    python3 website/tools/generate_assets.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "assets" / "img"

# ---------------------------------------------------------------------------
# palette — the same tokens the stylesheet uses, in sRGB floats
# ---------------------------------------------------------------------------

PAPER = np.array([0.961, 0.945, 0.910])   # #F5F1E8 warm ivory
INK   = np.array([0.137, 0.149, 0.122])   # #23261F deep olive-black
OLIVE = np.array([0.420, 0.451, 0.333])   # #6B7355
BRASS = np.array([0.659, 0.502, 0.290])   # #A8804A


def hexc(s: str) -> np.ndarray:
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)])


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def _box1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Exact box blur along one axis via a cumulative sum, in float."""
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode="edge").astype(np.float64)
    zs = list(ap.shape)
    zs[axis] = 1
    c = np.concatenate([np.zeros(zs), np.cumsum(ap, axis=axis)], axis=axis)
    hi = [slice(None)] * a.ndim
    hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo = [slice(None)] * a.ndim
    lo[axis] = slice(0, n)
    return ((c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)).astype(np.float32)


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur of a float array, three box passes, no 8-bit quantisation.

    Going through Pillow here costs 8 bits of precision, which shows up as
    concentric contour banding across the smooth gradients this renderer is
    almost entirely made of. Staying in float removes it.
    """
    if sigma <= 0.35:
        return a.astype(np.float32)
    r = max(1, int(round((-1 + math.sqrt(1 + 4 * sigma * sigma)) / 2)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box1d(out, r, 0)
        out = _box1d(out, r, 1)
    return out


def value_noise(shape, rng, octaves=5, persistence=0.55, base=4) -> np.ndarray:
    """Fractal value noise in [0, 1] — bicubic-upscaled random lattices."""
    h, w = shape
    total = np.zeros(shape, dtype=np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        res = base * 2 ** o
        lat = rng.random((max(2, int(res * h / w)) + 1, res + 1)).astype(np.float32)
        up = Image.fromarray((lat * 255).astype(np.uint8), "L").resize((w, h), Image.BICUBIC)
        total += amp * (np.asarray(up, dtype=np.float32) / 255)
        norm += amp
        amp *= persistence
    total /= norm
    return (total - total.min()) / max(float(np.ptp(total)), 1e-6)


def grid(shape):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return xx, yy


def dome(shape, cx, cy, rx, ry, warp=None, wob=0.0, power=0.5, angle=0.0) -> np.ndarray:
    """A smooth hemisphere height field, optionally rotated and noise-warped."""
    xx, yy = grid(shape)
    ox, oy = xx - cx, yy - cy
    if angle:
        c, s = math.cos(angle), math.sin(angle)
        ox, oy = ox * c + oy * s, -ox * s + oy * c
    dx = ox / max(rx, 1e-3)
    dy = oy / max(ry, 1e-3)
    d = np.sqrt(dx * dx + dy * dy)
    if warp is not None and wob:
        d = d * (1.0 + wob * (warp - 0.5))
    return np.clip(1.0 - d * d, 0.0, 1.0) ** power


def ellipse_mask(shape, cx, cy, rx, ry, feather=2.0) -> np.ndarray:
    xx, yy = grid(shape)
    dx = (xx - cx) / max(rx, 1e-3)
    dy = (yy - cy) / max(ry, 1e-3)
    d = np.sqrt(dx * dx + dy * dy)
    return np.clip((1.0 - d) * max(rx, ry) / feather + 0.5, 0.0, 1.0)


def over(dst: np.ndarray, src: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return dst * (1 - mask[..., None]) + src * mask[..., None]



# ---------------------------------------------------------------------------
# watercolour
# ---------------------------------------------------------------------------


def paper(shape, rng, tint=PAPER, strength=1.0):
    """Warm rag paper: long fibres, a little cloudiness, a faint deckle."""
    h, w = shape
    base = np.broadcast_to(tint, (h, w, 3)).astype(np.float32).copy()

    cloud = value_noise(shape, rng, octaves=5, base=3)
    base *= (1.0 - 0.045 * strength * (cloud - 0.5))[..., None]

    # fibres run mostly one way, as they do in real rag paper
    fine = value_noise(shape, rng, octaves=3, base=90)
    coarse = value_noise((h, max(4, w // 34)), rng, octaves=2, base=40)
    coarse = np.asarray(Image.fromarray((coarse * 255).astype(np.uint8), "L")
                        .resize((w, h), Image.BICUBIC), dtype=np.float32) / 255
    grain = 0.55 * fine + 0.45 * coarse
    base *= (1.0 - 0.055 * strength * (grain - 0.5))[..., None]
    return base


def wash(img, mask, colour, *, density=0.55, edge=0.55, bleed=2.2, rng=None,
         granulate=0.18):
    """Lay one translucent wash of pigment over the page.

    Watercolour is subtractive and it is not flat. Three things carry that here:
    the wash multiplies rather than covers, so overlaps deepen the way two
    passes of real pigment do; pigment collects at the edge of a drying pool, so
    the boundary is darker than the middle; and heavier pigments settle into the
    tooth of the paper, which is the granulation term.
    """
    m = np.clip(mask, 0.0, 1.0)
    if bleed:
        m = blur(m, bleed)

    # pigment pools where the wash ends
    rim = np.clip(m - blur(m, bleed * 3.2 + 4.0), 0.0, 1.0)
    a = np.clip(m * density + rim * edge, 0.0, 1.0)

    if granulate and rng is not None:
        tooth = value_noise(img.shape[:2], rng, octaves=5, base=26)
        a = np.clip(a * (1.0 - granulate + granulate * 2.0 * tooth), 0.0, 1.0)

    return img * (1.0 - a[..., None] * (1.0 - colour))


def petal(shape, cx, cy, r, rng, *, wob=0.55, octaves=5, base=6, power=0.62,
          squash=1.0, angle=0.0):
    """One organic shape — the unit every painted element is built from."""
    n = value_noise(shape, rng, octaves=octaves, base=int(base))
    d = dome(shape, cx, cy, r, r * squash, warp=n, wob=wob, power=power, angle=angle)
    return np.clip(d * 1.6 - 0.18, 0.0, 1.0)


def stroke(shape, x0, y0, x1, y1, width, rng, taper=True):
    """A brush stroke laid down between two points."""
    xx, yy = grid(shape)
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy) or 1.0
    t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / (ln * ln), 0.0, 1.0)
    px, py = x0 + t * dx, y0 + t * dy
    dist = np.sqrt((xx - px) ** 2 + (yy - py) ** 2)
    wob = value_noise(shape, rng, octaves=4, base=10)
    w = width * (1.0 + 0.45 * (wob - 0.5))
    if taper:
        # sin() dips fractionally below zero at the ends through float error,
        # and the square root of that is NaN, which poisons the whole wash
        w = w * (0.35 + 0.65 * np.sqrt(np.clip(np.sin(np.pi * t), 0.0, 1.0)))
    return np.clip(1.0 - dist / np.maximum(w, 1e-3), 0.0, 1.0)


def finish(img, rng, *, warmth=1.0, bloom_paper=0.0):
    """Final pass: a touch of scanned-paper softness and a whisper of grain."""
    img = np.clip(img, 0.0, 1.0)
    if bloom_paper:
        img = img * (1 - bloom_paper) + blur(img, 3.0) * bloom_paper
    if warmth != 1.0:
        img = img * np.array([1.0, 1.0 - 0.012 * (warmth - 1), 1.0 - 0.03 * (warmth - 1)])
    n = rng.normal(0, 0.008, img.shape[:2]).astype(np.float32)
    img = img + blur(n, 0.6)[..., None]
    return np.clip(img, 0.0, 1.0)


def save(img, name, *, quality=88, width=None, webp=True):
    arr = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(arr, "RGB")
    if width and im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / f"{name}.jpg", quality=quality, optimize=True, progressive=True)
    if webp:
        im.save(OUT / f"{name}.webp", quality=quality - 4, method=6)
    print(f"  {name}  {im.width}x{im.height}")


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------


def scene_plate(seed, palette, *, size=(900, 1200), components=7, spread=0.46,
                sauce=None, garnish="#6B7355", rim=True, crumbs=0.0, scatter=1.0):
    """A plate from directly above, painted rather than photographed."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    img = paper(shape, rng)

    pcx, pcy = w * 0.5, h * 0.5
    pr = min(w, h) * 0.40

    # the plate is barely there: a soft shadow and a drawn rim, no fill
    shadow = ellipse_mask(shape, pcx + w * 0.006, pcy + h * 0.010, pr * 1.02, pr * 1.02,
                          feather=6)
    img = wash(img, shadow, hexc("#CFC7B4"), density=0.30, edge=0.10, bleed=14, rng=rng,
               granulate=0.10)
    if rim:
        ring = np.clip(ellipse_mask(shape, pcx, pcy, pr, pr, feather=3)
                       - ellipse_mask(shape, pcx, pcy, pr * 0.985, pr * 0.985, feather=3), 0, 1)
        wobble = value_noise(shape, rng, octaves=4, base=7)
        ring = ring * (0.55 + 0.9 * wobble)
        img = wash(img, ring, hexc("#8A8674"),
                   density=0.72, edge=0.40, bleed=1.4, rng=rng, granulate=0.25)

    # sauce goes down first, the way it would on the plate
    if sauce is not None:
        sm = np.zeros(shape, dtype=np.float32)
        for _ in range(3):
            sm = np.maximum(sm, petal(shape, pcx + rng.normal(0, w * 0.045),
                                      pcy + rng.normal(0, h * 0.045),
                                      min(w, h) * rng.uniform(0.16, 0.24), rng,
                                      wob=0.85, base=5, power=0.5,
                                      angle=rng.uniform(0, math.pi)))
        img = wash(img, sm * ellipse_mask(shape, pcx, pcy, pr * 0.96, pr * 0.96, feather=4),
                   hexc(sauce), density=0.46, edge=0.62, bleed=3.4, rng=rng)

    cols = [hexc(c) for c in palette]
    for i in range(components):
        # golden angle plus jitter: purely random angles clump on one side of the
        # plate as often as not, and a clumped plate reads as a mistake
        ang = i * 2.39996 + rng.normal(0, 0.42)
        rad = ((i + 0.6) / components) ** 0.55 * rng.uniform(0.75, 1.12)
        cx = pcx + math.cos(ang) * pr * spread * rad
        cy = pcy + math.sin(ang) * pr * spread * rad
        r = min(w, h) * rng.uniform(0.095, 0.165)
        m = petal(shape, cx, cy, r, rng, wob=rng.uniform(0.42, 0.68),
                  base=rng.integers(5, 10), power=rng.uniform(0.48, 0.70),
                  squash=rng.uniform(0.60, 1.0), angle=rng.uniform(0, math.pi))
        m = m * ellipse_mask(shape, pcx, pcy, pr * 0.94, pr * 0.94, feather=4)
        img = wash(img, m, cols[i % len(cols)], density=rng.uniform(0.68, 0.88),
                   edge=rng.uniform(0.55, 0.80), bleed=rng.uniform(1.3, 2.3), rng=rng)

    # herbs, drawn with the brush rather than dropped in
    g = hexc(garnish)
    for _ in range(int(rng.integers(10, 17) * scatter)):
        ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(0, 1) ** 0.5
        cx = pcx + math.cos(ang) * pr * 0.50 * rad
        cy = pcy + math.sin(ang) * pr * 0.50 * rad
        # a leaf, not a stick: a squashed petal reads as something that grew
        m = petal(shape, cx, cy, min(w, h) * rng.uniform(0.016, 0.032), rng,
                  wob=0.45, base=rng.integers(7, 13), power=0.75,
                  squash=rng.uniform(0.24, 0.42), angle=rng.uniform(0, math.pi))
        img = wash(img, m, g * rng.uniform(0.82, 1.18), density=0.72, edge=0.55,
                   bleed=1.1, rng=rng, granulate=0.12)

    # a few spots of pigment flicked off the brush
    if crumbs or scatter:
        dust = value_noise(shape, rng, octaves=8, base=44)
        specks = np.clip(dust - 0.845, 0, 1) * 7
        specks = specks * ellipse_mask(shape, pcx, pcy, pr * 1.12, pr * 1.12, feather=8)
        img = wash(img, specks, cols[0] * 0.85, density=0.60, edge=0.2, bleed=0.7, rng=rng,
                   granulate=0.0)

    return finish(img, rng, bloom_paper=0.12)


def scene_glass(seed, liquid, *, size=(900, 1200), form="tumbler", garnish=None):
    """Glassware: drawn in line, filled with a wash.

    The silhouette is drawn as explicit strokes rather than traced from a filled
    mask — tracing a rectangle gives you a rectangle, which is what the first
    attempt looked like. Sides, base arc and the ellipse of the mouth are three
    separate marks, the way they would be made by hand.
    """
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    img = paper(shape, rng)
    xx, yy = grid(shape)

    cx = w * 0.5
    if form == "coupe":
        gw, gh, cy, foot = w * 0.215, h * 0.125, h * 0.34, True
    elif form == "cup":
        gw, gh, cy, foot = w * 0.190, h * 0.155, h * 0.50, False
    elif form == "highball":
        gw, gh, cy, foot = w * 0.115, h * 0.270, h * 0.48, False
    else:
        gw, gh, cy, foot = w * 0.150, h * 0.205, h * 0.50, False

    top, bot = cy - gh, cy + gh
    taper = 0.72 if form == "coupe" else (0.86 if form == "cup" else 0.93)
    ery = gw * 0.30                                    # how open the mouth reads
    cap = gw * taper * 0.55                            # rounded base

    # One definition of the silhouette, used by both the wash and the drawn line.
    # Two definitions is how the first version ended up with the drink spilling
    # out past the sides of its own glass.
    y0, y1 = top + ery * 0.5, bot - cap
    def half_at(y):
        t = np.clip((y - y0) / max(y1 - y0, 1e-3), 0.0, 1.0)
        return gw * (1 - t) + gw * taper * t

    halfw = half_at(yy)
    inside = ((np.abs(xx - cx) < halfw) & (yy >= y0) & (yy < y1)).astype(np.float32)
    # above the widest point the glass is the ellipse of its own mouth, so the
    # drink has to follow that curve rather than a straight edge
    mouth_fill = ellipse_mask(shape, cx, top, gw, ery, feather=2) * (yy < y0)
    base = ellipse_mask(shape, cx, y1, gw * taper, cap * 1.25, feather=2) * (yy >= y1)
    body = np.clip(inside + mouth_fill + base, 0, 1)

    stands_on = bot + gh * 1.55 if foot else bot
    shadow = ellipse_mask(shape, cx + w * 0.022, stands_on + h * 0.006,
                          gw * 1.35, gh * 0.09, feather=8)
    img = wash(img, shadow, hexc("#CFC7B4"), density=0.30, edge=0.10, bleed=12, rng=rng)

    # --- the drink
    level = top + 2 * gh * (0.26 if form in ("coupe", "cup") else 0.34)
    level = max(level, top + ery * 1.15)   # never pour above the rim
    fill = body * np.clip((yy - level) / 3.0 + 0.5, 0, 1)
    img = wash(img, fill, hexc(liquid), density=0.60, edge=0.62, bleed=2.6, rng=rng)
    surf = ellipse_mask(shape, cx, level, float(half_at(level)), ery * 0.82, feather=2)
    img = wash(img, surf, hexc(liquid), density=0.28, edge=0.70, bleed=2.0, rng=rng)

    # --- the drawing
    line = INK * 1.55
    lw = min(w, h) * 0.0034
    wobble = value_noise(shape, rng, octaves=4, base=9)

    def ink(canvas, mask, d=0.62):
        return wash(canvas, np.clip(mask * (0.55 + 0.9 * wobble), 0, 1), line,
                    density=d, edge=0.35, bleed=1.0, rng=rng, granulate=0.22)

    for side in (-1, 1):
        img = ink(img, stroke(shape, cx + side * gw, y0,
                              cx + side * gw * taper, y1, lw, rng, taper=False))
    lower = np.clip(ellipse_mask(shape, cx, y1, gw * taper, cap * 1.25, feather=2)
                    - ellipse_mask(shape, cx, y1, gw * taper - lw * 2,
                                   cap * 1.25 - lw * 2, feather=2), 0, 1)
    img = ink(img, lower * (yy >= y1))

    mouth = np.clip(ellipse_mask(shape, cx, top, gw, ery, feather=2)
                    - ellipse_mask(shape, cx, top, gw - lw * 2, ery - lw * 1.4, feather=2), 0, 1)
    img = ink(img, mouth, d=0.70)

    if foot:
        bowl_bottom = y1 + cap * 1.25
        stem_end = bowl_bottom + gh * 1.25
        img = ink(img, stroke(shape, cx, bowl_bottom, cx, stem_end, lw * 0.9, rng, taper=False))
        img = ink(img, stroke(shape, cx - gw * 0.62, stem_end,
                              cx + gw * 0.62, stem_end, lw * 0.9, rng, taper=False))

    if garnish:
        gm = petal(shape, cx + gw * 0.86, top - ery * 0.4, min(w, h) * 0.026, rng,
                   wob=0.45, power=0.75, squash=0.34, angle=-0.45)
        img = wash(img, gm, hexc(garnish), density=0.72, edge=0.55, bleed=1.2, rng=rng)

    return finish(img, rng, bloom_paper=0.12)


def scene_table(seed, *, size=(1200, 2000)):
    """A laid table from above, for the hero.

    Wide rather than square, and weighted to the right: the headline sits over
    the left third, so that side is left as bare paper.
    """
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    img = paper(shape, rng)

    # linen, blocked in as one soft wash
    linen = petal(shape, w * 0.66, h * 0.56, min(w, h) * 0.62, rng,
                  wob=0.22, power=0.85, squash=0.78, base=3)
    img = wash(img, linen, hexc("#EBE5D6"), density=0.34, edge=0.28, bleed=16, rng=rng,
               granulate=0.10)

    plates = [
        (0.62, 0.46, 0.30, ["#D8B478", "#BE9450", "#EBD6A8"], "#7E8F76"),
        (0.86, 0.72, 0.22, ["#9C5240", "#B87058"],            "#6B7355"),
        (0.44, 0.78, 0.17, ["#C9A063", "#E0C48E"],            "#6B7355"),
    ]
    for fx, fy, fr, pal, garnish in plates:
        pcx, pcy = w * fx, h * fy
        pr = min(w, h) * fr

        sh = ellipse_mask(shape, pcx + w * 0.004, pcy + h * 0.012, pr * 1.02, pr * 1.02, feather=6)
        img = wash(img, sh, hexc("#CFC7B4"), density=0.26, edge=0.10, bleed=14, rng=rng,
                   granulate=0.08)
        ring = np.clip(ellipse_mask(shape, pcx, pcy, pr, pr, feather=3)
                       - ellipse_mask(shape, pcx, pcy, pr * 0.985, pr * 0.985, feather=3), 0, 1)
        wob = value_noise(shape, rng, octaves=4, base=7)
        img = wash(img, ring * (0.55 + 0.9 * wob), hexc("#8A8674"), density=0.66, edge=0.40,
                   bleed=1.4, rng=rng, granulate=0.25)

        cols = [hexc(c) for c in pal]
        for i in range(6):
            ang = i * 2.39996 + rng.normal(0, 0.4)
            rad = ((i + 0.6) / 6) ** 0.55 * rng.uniform(0.75, 1.1)
            m = petal(shape, pcx + math.cos(ang) * pr * 0.44 * rad,
                      pcy + math.sin(ang) * pr * 0.44 * rad,
                      pr * rng.uniform(0.24, 0.40), rng, wob=rng.uniform(0.45, 0.68),
                      base=rng.integers(5, 10), power=rng.uniform(0.5, 0.7),
                      squash=rng.uniform(0.6, 1.0), angle=rng.uniform(0, math.pi))
            m = m * ellipse_mask(shape, pcx, pcy, pr * 0.94, pr * 0.94, feather=4)
            img = wash(img, m, cols[i % len(cols)], density=rng.uniform(0.66, 0.86),
                       edge=rng.uniform(0.55, 0.78), bleed=rng.uniform(1.4, 2.4), rng=rng)

        g = hexc(garnish)
        for _ in range(int(rng.integers(6, 11))):
            ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(0, 1) ** 0.5
            m = petal(shape, pcx + math.cos(ang) * pr * 0.5 * rad,
                      pcy + math.sin(ang) * pr * 0.5 * rad,
                      pr * rng.uniform(0.05, 0.10), rng, wob=0.45, power=0.75,
                      squash=rng.uniform(0.24, 0.42), angle=rng.uniform(0, math.pi))
            img = wash(img, m, g * rng.uniform(0.85, 1.15), density=0.70, edge=0.55,
                       bleed=1.1, rng=rng)

    # a glass, seen from above: two circles and a wash
    for gx, gy, gr in ((0.30, 0.30, 0.052), (0.76, 0.20, 0.042)):
        gcx, gcy, r = w * gx, h * gy, min(w, h) * gr
        img = wash(img, ellipse_mask(shape, gcx, gcy, r * 0.82, r * 0.82, feather=3),
                   hexc("#B4783C"), density=0.42, edge=0.60, bleed=2.4, rng=rng)
        ring = np.clip(ellipse_mask(shape, gcx, gcy, r, r, feather=2)
                       - ellipse_mask(shape, gcx, gcy, r * 0.93, r * 0.93, feather=2), 0, 1)
        img = wash(img, ring, INK * 1.5, density=0.62, edge=0.35, bleed=1.0, rng=rng)

    # herbs and pigment flicked across the cloth
    for _ in range(22):
        cx0, cy0 = rng.uniform(0.22, 1.0) * w, rng.uniform(0.05, 0.98) * h
        m = petal(shape, cx0, cy0, min(w, h) * rng.uniform(0.012, 0.026), rng,
                  wob=0.45, power=0.75, squash=rng.uniform(0.24, 0.42),
                  angle=rng.uniform(0, math.pi))
        img = wash(img, m, OLIVE * rng.uniform(0.85, 1.2), density=0.52, edge=0.5,
                   bleed=1.3, rng=rng)

    return finish(img, rng, bloom_paper=0.13)


def scene_room(seed, *, size=(900, 1400), mood="dining"):
    """The room as an architectural wash — arches, light, a suggestion of tables."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    img = paper(shape, rng)
    xx, yy = grid(shape)

    if mood in ("dining", "bar"):
        for fx in np.linspace(0.13, 0.87, 4):
            acx = w * fx
            aw, ah = w * 0.085, h * 0.26
            acy = h * 0.34
            arch = ellipse_mask(shape, acx, acy, aw, ah, feather=4)
            col = ((np.abs(xx - acx) < aw) & (yy > acy) & (yy < h * 0.62)).astype(np.float32)
            m = np.clip(arch + col, 0, 1)
            img = wash(img, m, hexc("#DCD5C4"), density=0.42, edge=0.55, bleed=4.0, rng=rng)
            outline = np.clip(blur(m, 1.6) - blur(m, 3.4), 0, 1) * 3
            img = wash(img, outline, OLIVE * 1.2, density=0.40, edge=0.3, bleed=1.2, rng=rng)

    if mood == "kitchen":
        for fx in np.linspace(0.18, 0.82, 5):
            lamp = ellipse_mask(shape, w * fx, h * 0.20, w * 0.035, h * 0.016, feather=3)
            img = wash(img, lamp, BRASS, density=0.55, edge=0.5, bleed=2.4, rng=rng)
            stem = ((np.abs(xx - w * fx) < w * 0.0022) & (yy < h * 0.20)).astype(np.float32)
            img = wash(img, stem, INK * 1.8, density=0.45, edge=0.2, bleed=0.9, rng=rng)
        bench = ((yy > h * 0.60) & (yy < h * 0.66)).astype(np.float32)
        img = wash(img, bench, OLIVE, density=0.30, edge=0.55, bleed=3.0, rng=rng)

    # a warm pool of light across the upper left
    pool = np.exp(-(((xx - w * 0.30) / (w * 0.55)) ** 2 + ((yy - h * 0.22) / (h * 0.42)) ** 2))
    img = wash(img, pool, BRASS, density=0.16, edge=0.05, bleed=30, rng=rng, granulate=0.05)

    # tables in the foreground, blocked in loosely
    for _ in range(4 if mood == "dining" else 3):
        tx = rng.uniform(0.10, 0.90) * w
        ty = rng.uniform(0.74, 0.94) * h
        m = petal(shape, tx, ty, min(w, h) * rng.uniform(0.07, 0.12), rng,
                  wob=0.30, power=0.75, squash=rng.uniform(0.45, 0.7))
        img = wash(img, m, hexc("#CBC3AE"), density=0.40, edge=0.55, bleed=3.4, rng=rng)
        if mood == "dining":
            g = ellipse_mask(shape, tx, ty, min(w, h) * 0.012, min(w, h) * 0.012, feather=3)
            img = wash(img, g, BRASS, density=0.6, edge=0.4, bleed=1.4, rng=rng)

    floor = np.clip((yy / h - 0.66) * 3.2, 0, 1)
    img = wash(img, floor, hexc("#E2DAC8"), density=0.30, edge=0.12, bleed=16, rng=rng)
    return finish(img, rng, bloom_paper=0.14)


def scene_hearth(seed, *, size=(1100, 900)):
    """Fire, as washes of ochre and rust rather than glowing pixels."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    img = paper(shape, rng)
    xx, yy = grid(shape)

    bed = np.clip((yy / h - 0.42) * 3.0, 0, 1)
    img = wash(img, bed, hexc("#C9A063"), density=0.34, edge=0.30, bleed=14, rng=rng)

    for _ in range(26):
        cx = rng.uniform(-0.05, 1.05) * w
        cy = rng.uniform(0.45, 1.02) * h
        m = petal(shape, cx, cy, min(w, h) * rng.uniform(0.05, 0.11), rng,
                  wob=0.6, power=0.6, squash=rng.uniform(0.5, 0.9),
                  angle=rng.uniform(0, math.pi))
        col = hexc(rng.choice(["#B4561E", "#8C3A18", "#D98E28", "#6B2A12"]))
        img = wash(img, m, col, density=rng.uniform(0.32, 0.55),
                   edge=rng.uniform(0.4, 0.65), bleed=rng.uniform(2.5, 5.0), rng=rng)

    for by in np.linspace(0.50, 0.96, 5):
        bar = np.exp(-((yy - h * by) / (h * 0.006)) ** 2)
        img = wash(img, bar, INK * 1.5, density=0.40, edge=0.25, bleed=1.4, rng=rng)

    for _ in range(40):
        sx, sy = rng.uniform(0, 1) * w, rng.uniform(0.05, 0.55) * h
        m = ellipse_mask(shape, sx, sy, min(w, h) * rng.uniform(0.002, 0.005),
                         min(w, h) * rng.uniform(0.003, 0.010), feather=2)
        img = wash(img, m, hexc("#B4561E"), density=0.45, edge=0.3, bleed=1.0, rng=rng)

    return finish(img, rng, bloom_paper=0.12)


def scene_texture(seed, *, size=(700, 700), tone="#6B7355", second="#A8804A"):
    """Abstract wash, for the smaller gallery tiles."""
    rng = np.random.default_rng(seed)
    shape = size
    img = paper(shape, rng)
    h, w = size
    for _ in range(7):
        m = petal(shape, rng.uniform(0.1, 0.9) * w, rng.uniform(0.1, 0.9) * h,
                  min(w, h) * rng.uniform(0.16, 0.30), rng, wob=0.75, power=0.55,
                  squash=rng.uniform(0.5, 1.0), angle=rng.uniform(0, math.pi))
        col = hexc(tone) if rng.random() < 0.6 else hexc(second)
        img = wash(img, m, col, density=rng.uniform(0.26, 0.44),
                   edge=rng.uniform(0.45, 0.7), bleed=rng.uniform(3, 7), rng=rng)
    return finish(img, rng, bloom_paper=0.16)


def scene_monogram(seed, letters, *, size=(320, 320)):
    """Testimonial avatar: initials in a hand-drawn ring. No invented faces."""
    rng = np.random.default_rng(seed)
    shape = size
    h, w = size
    img = paper(shape, rng)
    disc = ellipse_mask(shape, w / 2, h / 2, w * 0.44, h * 0.44, feather=3)
    img = wash(img, disc, hexc("#E7E1D2"), density=0.45, edge=0.35, bleed=4, rng=rng)
    ring = np.clip(ellipse_mask(shape, w / 2, h / 2, w * 0.45, h * 0.45, feather=2)
                   - ellipse_mask(shape, w / 2, h / 2, w * 0.425, h * 0.425, feather=2), 0, 1)
    wobble = value_noise(shape, rng, octaves=4, base=8)
    img = wash(img, ring * (0.5 + wobble), OLIVE, density=0.60, edge=0.4, bleed=1.3, rng=rng)
    img = finish(img, rng, bloom_paper=0.10)

    from PIL import ImageDraw, ImageFont
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(im)
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(cand).exists():
            font = ImageFont.truetype(cand, int(h * 0.30))
            break
    if font is None:
        font = ImageFont.load_default()
    bb = d.textbbox((0, 0), letters, font=font)
    d.text(((w - bb[2] + bb[0]) / 2 - bb[0], (h - bb[3] + bb[1]) / 2 - bb[1]), letters,
           font=font, fill=(74, 82, 60))
    return np.asarray(im, dtype=np.float32) / 255


# ---------------------------------------------------------------------------
# the shot list
# ---------------------------------------------------------------------------

# Ingredient-led palettes: each dish is painted in the colours it is made of.
DISHES = [
    ("scallop",   11, ["#E0C48E", "#CBA968", "#EBDCBC"], dict(sauce="#7E8F76", components=6)),
    ("aubergine", 19, ["#6E5A78", "#4E3E5C", "#8C7A94"], dict(sauce="#D8CDB4", components=6)),
    ("oyster",   141, ["#CFC8B4", "#AEA894", "#E4DECA"], dict(sauce="#7E8F76", components=5)),
    ("beet",      91, ["#9A4468", "#7A2E4E", "#B9708C"], dict(sauce="#E2D6C0", components=7)),
    ("octopus",   51, ["#A0687A", "#7E4A5C", "#C08C9A"], dict(sauce="#B4785E", components=6)),
    ("galouti",   29, ["#8C6444", "#6B4A30", "#A88160"], dict(sauce="#5E4A2E", components=6)),

    ("shortrib",  23, ["#9C5240", "#7A382A", "#B87058"], dict(sauce="#5A3020", components=6)),
    ("lamb",      79, ["#96543C", "#743C28", "#B0745A"], dict(sauce="#6B7355", components=6)),
    ("truffle",   37, ["#D8C9A8", "#B8A484", "#8C7A5E"], dict(components=8, spread=0.40)),
    ("lobster",   67, ["#D98E4E", "#C0702E", "#EBB878"], dict(sauce="#A8804A", components=6)),
    ("morel",    129, ["#8A7052", "#66513A", "#A89070"], dict(sauce="#6B7355", components=8)),
    ("seabass",   47, ["#DCD6C0", "#BAB49C", "#EEE8D6"], dict(sauce="#7E8F76", components=6)),
    ("paneer",    59, ["#EADFC2", "#D2C4A0", "#F2EADA"], dict(sauce="#C0704F", components=7)),

    ("chocolate",103, ["#6B4530", "#4A2C1E", "#8A6046"], dict(sauce="#3A2218", components=5)),
    ("mangotart",153, ["#E0AE5A", "#C48E38", "#F0D296"], dict(components=6, crumbs=1.0)),
    ("citrus",   117, ["#E8CC7A", "#CFAE4E", "#F4E4B0"], dict(sauce="#A8804A", components=6)),
    ("kulfi",    163, ["#EFE4DC", "#D8C4BC", "#C4A0AC"], dict(sauce="#9E6478", components=5)),
    ("jamun",    173, ["#7A4A30", "#5A3220", "#96684A"], dict(sauce="#4A2A18", components=5)),
]

DRINKS = [
    ("oldfashioned", 501, "#B4783C", dict(form="tumbler", garnish="#A8804A")),
    ("ginsour",      511, "#D8B45E", dict(form="coupe", garnish="#6B7355")),
    ("kokum",        521, "#A84058", dict(form="highball", garnish="#6B7355")),
    ("coffee",       531, "#7A5236", dict(form="cup")),
    ("tea",          541, "#C08E4A", dict(form="cup")),
    ("wine",         551, "#8C3A50", dict(form="coupe")),
]


def main():
    print("painting the AURELIA image set →", OUT)

    hero = scene_table(7)
    for wd in (900, 1400, 2000):
        save(hero, f"hero-{wd}", quality=88, width=wd)
    save(hero, "og", quality=86, width=1200, webp=False)

    for name, seed, pal, kw in DISHES:
        save(scene_plate(seed, pal, **kw), f"dish-{name}")
    for name, seed, liquid, kw in DRINKS:
        save(scene_glass(seed, liquid, **kw), f"dish-{name}")

    save(scene_room(201, mood="dining", size=(1000, 1500)), "interior-dining")
    save(scene_room(211, mood="bar", size=(1000, 1400)), "interior-bar")
    save(scene_room(221, mood="kitchen", size=(1000, 1400)), "kitchen-pass")
    save(scene_room(241, mood="dining", size=(900, 1200)), "gallery-room")
    save(scene_hearth(231), "hearth")

    save(scene_texture(301), "texture-ember")
    save(scene_texture(311, tone="#6B7355", second="#8FA88C"), "texture-herb")
    save(scene_texture(321, tone="#8C6444", second="#A8804A"), "texture-char")

    for i, initials in enumerate(["AR", "MK", "SD", "JL", "PN", "TV"]):
        save(scene_monogram(400 + i * 7, initials), f"avatar-{i + 1}", quality=90)

    print("done")


if __name__ == "__main__":
    main()
