"""
Procedural art director for the AURELIA website.

Every image on the site is synthesised here — no stock photography, no network
fetch, no licensing question. The renderer is a small physically-flavoured
pipeline: a height field is built from noise-warped blobs, shaded with a
Lambert + Blinn-Phong model under a single warm key light, then graded the way
a dark, moody food photograph is graded (split-tone, bloom, grain, vignette,
depth-of-field falloff).

The result is atmospheric rather than literal. It is designed to be replaced:
drop a real photograph at the same path in assets/img/ and the site picks it up
with no code change. See website/README.md.

    python3 website/tools/generate_assets.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "assets" / "img"

# ---------------------------------------------------------------------------
# palette — the same tokens the stylesheet uses, in linear-ish sRGB floats
# ---------------------------------------------------------------------------

INK = np.array([0.055, 0.051, 0.043])
GOLD = np.array([0.788, 0.659, 0.416])
GOLD_WARM = np.array([1.00, 0.82, 0.52])
CREAM = np.array([0.949, 0.929, 0.894])


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
# lighting
# ---------------------------------------------------------------------------


def shade(height, albedo, *, light=(-0.55, -0.75, 0.62), relief=90.0, ambient=0.16,
          spec_power=42.0, spec=0.55, light_col=GOLD_WARM, rim=0.0):
    """Lambert + Blinn-Phong over a height field. albedo is (H, W, 3)."""
    gy, gx = np.gradient(height.astype(np.float32))
    nx, ny = -gx * relief, -gy * relief
    nz = np.ones_like(height, dtype=np.float32)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / ln, ny / ln, nz / ln

    L = np.array(light, dtype=np.float32)
    L /= np.linalg.norm(L)
    ndl = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0.0, 1.0)

    Hv = L + np.array([0.0, 0.0, 1.0], dtype=np.float32)
    Hv /= np.linalg.norm(Hv)
    ndh = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0.0, 1.0)

    lit = albedo * (ambient + (1 - ambient) * ndl)[..., None] * light_col
    lit = lit + (ndh ** spec_power)[..., None] * spec * light_col
    if rim:
        fres = (1.0 - nz) ** 3
        lit = lit + fres[..., None] * rim * GOLD_WARM
    return lit


# ---------------------------------------------------------------------------
# grade — what turns a render into a photograph
# ---------------------------------------------------------------------------


def vignette(shape, strength=0.72, radius=0.86, cx=0.5, cy=0.5):
    h, w = shape
    xx, yy = grid(shape)
    dx = (xx / w - cx) / radius
    dy = (yy / h - cy) / (radius * h / w) * (h / w)
    d = np.sqrt(dx * dx + dy * dy)
    return np.clip(1.0 - strength * np.clip(d - 0.35, 0, None) ** 1.7, 0.05, 1.0)


def grade(img, rng, *, bloom=0.30, grain=0.016, contrast=1.11, lift=0.012,
          vig=0.72, aberration=1.0, warmth=1.0, saturation=1.0):
    img = np.clip(img, 0, None)

    if bloom:
        bright = np.clip(img - 0.62, 0, None)
        img = img + blur(bright, 26) * bloom + blur(bright, 8) * bloom * 0.5

    # filmic tone map — keeps highlights from clipping to paper white
    img = (img * (2.51 * img + 0.03)) / (img * (2.43 * img + 0.59) + 0.14)

    # split tone: warm highlights, cool-green shadows (the classic dark-food look)
    lum = img @ np.array([0.2126, 0.7152, 0.0722])
    shadow = np.clip(1 - lum * 2.2, 0, 1)[..., None]
    high = np.clip(lum * 1.6 - 0.35, 0, 1)[..., None]
    img = img + shadow * np.array([-0.012, 0.004, 0.020]) * warmth
    img = img + high * np.array([0.052, 0.026, -0.020]) * warmth

    if saturation != 1.0:
        lum = (img @ np.array([0.2126, 0.7152, 0.0722]))[..., None]
        img = lum + (img - lum) * saturation

    img = (img - 0.5) * contrast + 0.5 + lift
    img = img * vignette(img.shape[:2], strength=vig)[..., None]

    if aberration:
        h, w = img.shape[:2]
        k = max(1, int(aberration))
        img[..., 0] = np.roll(img[..., 0], k, axis=1)
        img[..., 2] = np.roll(img[..., 2], -k, axis=1)

    if grain:
        n = rng.normal(0, grain, img.shape[:2]).astype(np.float32)
        n = blur(n, 0.55)
        img = img + n[..., None] * (0.35 + 0.9 * np.clip(1 - img.mean(axis=2), 0, 1))[..., None]

    return np.clip(img, 0, 1)


def save(img, name, *, quality=84, width=None, webp=True):
    arr = (np.clip(img, 0, 1) ** (1 / 1.06) * 255).astype(np.uint8)
    im = Image.fromarray(arr, "RGB")
    if width and im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / f"{name}.jpg", quality=quality, optimize=True, progressive=True)
    if webp:
        im.save(OUT / f"{name}.webp", quality=quality - 4, method=6)
    print(f"  {name}  {im.width}x{im.height}")


# ---------------------------------------------------------------------------
# scene: a plated dish
# ---------------------------------------------------------------------------


def scene_dish(seed, palette, *, size=(900, 1200), plate="charcoal", garnish="#6E8460",
               sauce=None, components=7, spread=0.62, relief=95.0, height_scale=1.0,
               crumb=0.0, saturation=1.0, elong=1.0):
    """A plate under a single warm key light, shot wide open against a dark room."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    xx, yy = grid(shape)

    # --- the room behind the table: warm, out of focus, never flat black
    room = np.broadcast_to(INK * 1.9, (h, w, 3)).copy()
    room = room * (0.5 + 1.4 * value_noise(shape, rng, octaves=5, base=3)[..., None])
    room = room * np.array([1.16, 1.0, 0.80])
    for _ in range(rng.integers(5, 10)):          # candle bokeh
        bx, by = rng.uniform(0.02, 0.98) * w, rng.uniform(0.0, 0.34) * h
        r = w * rng.uniform(0.018, 0.055)
        b = dome(shape, bx, by, r, r, power=0.35)
        room = room + blur(b, r * 0.55)[..., None] * GOLD_WARM * rng.uniform(0.25, 0.85)
    horizon = np.clip((yy / h - 0.30) * 6.0, 0, 1)
    room = room * (1 - 0.55 * horizon)[..., None]
    img = blur(room, 34)

    # --- table: dark stone, lit by a pool falling from the upper left
    stone = value_noise(shape, rng, octaves=6, base=3)
    streak = value_noise(shape, rng, octaves=3, base=2)
    table = INK * (0.85 + 0.75 * stone[..., None] + 0.30 * streak[..., None])
    table = table * np.array([1.08, 1.0, 0.88])
    pool = np.exp(-(((xx - w * 0.26) / (w * 0.80)) ** 2 + ((yy - h * 0.12) / (h * 0.78)) ** 2))
    table = table * (0.26 + 1.75 * pool[..., None])
    img = over(img, table, np.clip((yy / h - 0.20) * 7.0, 0, 1))

    # --- plate: wide, low, with a soft directional rim rather than a hard ring
    pcx, pcy = w * 0.5, h * 0.60
    prx, pry = w * 0.455, h * 0.268

    contact = ellipse_mask(shape, pcx, pcy + h * 0.028, prx * 1.03, pry * 1.02, feather=10)
    img = img * (1 - 0.82 * blur(contact, 30))[..., None]

    plate_col = {"charcoal": hexc("#151417"), "bone": hexc("#D9D0BE"),
                 "slate": hexc("#20222A"), "clay": hexc("#3A2E27")}[plate]
    pm = ellipse_mask(shape, pcx, pcy, prx, pry, feather=2.4)
    well = dome(shape, pcx, pcy, prx * 0.93, pry * 0.93, power=0.30)
    pheight = blur((1 - well) * pm, 9) * 0.6
    ptex = value_noise(shape, rng, octaves=4, base=7)
    palb = np.broadcast_to(plate_col, (h, w, 3)) * (0.88 + 0.26 * ptex[..., None])
    palb = palb * (0.42 + 1.5 * pool[..., None])
    plate_lit = shade(pheight, palb, relief=180, ambient=0.34, spec_power=12,
                      spec=0.26 if plate == "charcoal" else 0.12)
    img = over(img, plate_lit, pm)

    # rim: brightest where the edge faces the key light, gone on the far side
    ring = np.clip(ellipse_mask(shape, pcx, pcy, prx, pry, feather=3.2)
                   - ellipse_mask(shape, pcx, pcy, prx * 0.965, pry * 0.945, feather=3.2), 0, 1)
    edge_ang = np.arctan2((yy - pcy) / max(pry, 1e-3), (xx - pcx) / max(prx, 1e-3))
    facing = np.clip(np.cos(edge_ang + 2.36), 0, 1) ** 1.3
    img = img + blur(ring * facing, 2.0)[..., None] * GOLD * 0.85
    img = img + blur(ring * facing, 16)[..., None] * GOLD * 0.28

    # --- sauce: a thin reflective pool, not a dome
    if sauce is not None:
        sm = np.zeros(shape, dtype=np.float32)
        for _ in range(3):
            sm = np.maximum(sm, dome(shape, pcx + rng.normal(0, w * 0.07),
                                     pcy + rng.normal(0, h * 0.035),
                                     w * rng.uniform(0.17, 0.27), h * rng.uniform(0.08, 0.13),
                                     warp=value_noise(shape, rng, octaves=4, base=5), wob=0.70,
                                     power=0.30, angle=rng.uniform(0, math.pi)))
        sm = blur(np.clip(sm, 0, 1), 9) * pm
        salb = np.broadcast_to(hexc(sauce), (h, w, 3)) * (0.5 + 1.3 * pool[..., None])
        slit = shade(sm * 0.035, salb, relief=240, ambient=0.26, spec_power=30, spec=0.70)
        img = over(img, slit, np.clip(sm * 1.3, 0, 1) * 0.93)

    # --- the food: many small rotated elements, layered, not one fused mass
    height = np.zeros(shape, dtype=np.float32)
    albedo = np.zeros((h, w, 3), dtype=np.float32)
    weight = np.zeros(shape, dtype=np.float32)
    cols = [hexc(c) for c in palette]

    for i in range(components):
        ang = rng.uniform(0, 2 * math.pi)
        rad = rng.uniform(0, 1) ** 0.55
        cx = pcx + math.cos(ang) * prx * spread * rad
        cy = pcy + math.sin(ang) * pry * spread * rad * 0.90
        rx = w * rng.uniform(0.052, 0.098) * elong
        ry = rx * rng.uniform(0.40, 0.72)
        rot = rng.uniform(0, math.pi)
        n = value_noise(shape, rng, octaves=5, base=int(rng.integers(5, 11)))
        d = dome(shape, cx, cy, rx, ry, warp=n, wob=0.42, power=rng.uniform(0.40, 0.62), angle=rot)
        d = d * rng.uniform(0.68, 1.0) * height_scale
        col = cols[i % len(cols)] * rng.uniform(0.82, 1.18)
        albedo += col * d[..., None]
        weight += d
        height = np.maximum(height, d)

    fm = np.clip(weight, 0, 1)
    albedo = albedo / np.maximum(weight, 1e-4)[..., None]

    micro = value_noise(shape, rng, octaves=7, base=16)
    fibre = value_noise(shape, rng, octaves=6, base=int(rng.integers(20, 40)))
    height = blur(height, 1.2) + (micro - 0.5) * 0.050 * fm + (fibre - 0.5) * 0.028 * fm
    if crumb:
        height += (value_noise(shape, rng, octaves=8, base=34) - 0.5) * crumb * fm
    albedo = albedo * (0.84 + 0.34 * micro[..., None]) * (0.45 + 1.35 * pool[..., None])

    food = shade(height, albedo, relief=relief, ambient=0.13, spec_power=30, spec=0.50, rim=0.14)
    # a little subsurface bleed — cooked food is never fully opaque
    food = food + blur(albedo * fm[..., None], 9) * 0.16
    img = over(img, food, blur(fm, 1.0) * pm)

    # --- garnish: flat leaves, low relief, barely specular
    g = hexc(garnish)
    for _ in range(int(rng.integers(9, 16))):
        ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(0, 1) ** 0.5
        cx = pcx + math.cos(ang) * prx * 0.50 * rad
        cy = pcy + math.sin(ang) * pry * 0.50 * rad
        lx = w * rng.uniform(0.014, 0.032)
        lm = dome(shape, cx, cy, lx, lx * rng.uniform(0.22, 0.40), power=0.85,
                  angle=rng.uniform(0, math.pi))
        gl = shade(lm * 0.10, np.broadcast_to(g * rng.uniform(0.75, 1.25), (h, w, 3)),
                   relief=120, ambient=0.26, spec_power=22, spec=0.22)
        img = over(img, gl, np.clip(lm * 2.6, 0, 1) * 0.85)

    # --- powder, crumb and oil scatter
    dust = value_noise(shape, rng, octaves=8, base=42)
    scatter = np.clip(dust - 0.80, 0, 1) * 5 * pm * (1 - fm * 0.4)
    img = img + blur(scatter, 0.7)[..., None] * cols[0] * 0.55

    for _ in range(int(rng.integers(8, 16))):
        ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(0.3, 1.0)
        cx = pcx + math.cos(ang) * prx * 0.75 * rad
        cy = pcy + math.sin(ang) * pry * 0.75 * rad
        r = w * rng.uniform(0.0022, 0.006)
        bm = dome(shape, cx, cy, r, r, power=0.5)
        img = img + blur(bm, 0.7)[..., None] * GOLD_WARM * 0.30

    # --- shallow depth of field, focus plane on the plate
    focus = np.exp(-(((yy / h) - 0.585) ** 2) / (2 * 0.145 ** 2))
    img = img * focus[..., None] + blur(img, 13) * (1 - focus)[..., None]

    # --- steam
    steam = value_noise(shape, rng, octaves=4, base=3)
    veil = np.clip((0.60 - yy / h) * 1.8, 0, 1) * np.clip(steam - 0.45, 0, 1) * 1.6
    img = img + blur(veil, 24)[..., None] * CREAM * 0.060

    return grade(img, rng, saturation=saturation)


def superellipse(shape, cx, cy, rx, ry, n=5.0, feather=2.0):
    xx, yy = grid(shape)
    dx = np.abs(xx - cx) / max(rx, 1e-3)
    dy = np.abs(yy - cy) / max(ry, 1e-3)
    d = (dx ** n + dy ** n) ** (1.0 / n)
    return np.clip((1.0 - d) * max(rx, ry) / feather + 0.5, 0.0, 1.0)


def scene_drink(seed, liquid, *, size=(900, 1200), form="tumbler", ice=2, foam=None,
                garnish=None, saturation=1.0):
    """Glassware on a bar.

    What makes a glass read as a glass is not its outline — it is the ellipse of
    the mouth, the ellipse of the liquid surface seen slightly from above, and
    the way a cylinder darkens towards both edges. All three are built here
    explicitly.
    """
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    xx, yy = grid(shape)
    opaque = form == "cup"

    # --- the bar behind, thrown well out of focus
    room = np.broadcast_to(INK * 2.0, (h, w, 3)).copy()
    room = room * (0.45 + 1.5 * value_noise(shape, rng, octaves=5, base=3)[..., None])
    room = room * np.array([1.18, 1.0, 0.78])
    for _ in range(int(rng.integers(5, 9))):
        bx, by = rng.uniform(0.02, 0.98) * w, rng.uniform(0.0, 0.40) * h
        r = w * rng.uniform(0.012, 0.032)
        room = room + blur(dome(shape, bx, by, r, r, power=0.35), r * 0.7)[..., None] \
            * GOLD_WARM * rng.uniform(0.15, 0.45)
    pool = np.exp(-(((xx - w * 0.30) / (w * 0.78)) ** 2 + ((yy - h * 0.18) / (h * 0.80)) ** 2))
    img = blur(room, 30) * (0.34 + 1.15 * pool[..., None])

    bar = np.clip((yy / h - 0.72) * 9.0, 0, 1)
    tex = value_noise(shape, rng, octaves=5, base=4)
    surf = np.broadcast_to(hexc("#1E1913"), (h, w, 3)) * (0.5 + 1.1 * tex[..., None]) \
        * (0.30 + 1.30 * pool[..., None])
    img = over(img, surf, bar * 0.94)

    lc = hexc(liquid)
    cx = w * 0.5
    if form == "coupe":
        gw, gh, gy = w * 0.30, h * 0.150, h * 0.42
    elif form == "cup":
        gw, gh, gy = w * 0.235, h * 0.150, h * 0.52
    elif form == "highball":
        gw, gh, gy = w * 0.150, h * 0.310, h * 0.46
    else:
        gw, gh, gy = w * 0.205, h * 0.230, h * 0.50

    top, bot = gy - gh, gy + gh
    ery = gw * (0.34 if form == "coupe" else 0.30)          # mouth ellipse, seen from above
    taper = 0.86 if form in ("coupe", "cup") else 0.94       # narrower at the base

    # silhouette: a tapered cylinder with a rounded foot
    halfw = gw * (taper + (1 - taper) * np.clip((yy - top) / (2 * gh), 0, 1))
    walls = np.clip((halfw - np.abs(xx - cx)) / 2.0 + 0.5, 0, 1)
    body = walls * np.clip((yy - top) / 2.0 + 0.5, 0, 1) * np.clip((bot - yy) / 2.0 + 0.5, 0, 1)
    body = np.maximum(body * (yy > top - ery), 0)
    foot = ellipse_mask(shape, cx, bot, gw * taper, ery * 0.85, feather=2.0)
    body = np.clip(body + foot * (yy > bot - ery), 0, 1)
    mouth = ellipse_mask(shape, cx, top, gw, ery, feather=2.0)
    body = np.clip(body + mouth, 0, 1)

    # shadow and caustic cast on the bar
    shadow = ellipse_mask(shape, cx, bot + h * 0.012, gw * 1.5, ery * 1.5, feather=8)
    img = img * (1 - 0.55 * blur(shadow, 20))[..., None]
    caustic = ellipse_mask(shape, cx + gw * 0.35, bot + h * 0.016, gw * 0.85, ery * 0.7, feather=8)
    img = img + blur(caustic, 14)[..., None] * lc * 0.55
    img = img + blur(caustic, 48)[..., None] * lc * 0.18

    # --- cylinder shading term: bright off-centre, dark at both edges
    u = np.clip((xx - cx) / np.maximum(halfw, 1e-3), -1, 1)
    cyl = np.sqrt(np.clip(1 - u * u, 0, 1))
    cyl = 0.30 + 0.95 * cyl ** 0.7
    cyl = cyl * (1 - 0.45 * np.clip((np.abs(u) - 0.72) / 0.28, 0, 1))
    cyl = cyl + 0.55 * np.exp(-((u - 0.55) / 0.13) ** 2)     # refracted band on the far side

    level = top + (2 * gh) * (0.34 if form in ("coupe", "cup") else 0.42)

    if opaque:
        cup = np.broadcast_to(hexc("#DCD3C0"), (h, w, 3)) * (cyl * 0.55)[..., None]
        cup = cup * (0.40 + 1.15 * pool[..., None])
        img = over(img, cup, body * 0.98)
        saucer = np.clip(ellipse_mask(shape, cx, bot + h * 0.008, gw * 1.65, ery * 1.45, feather=3)
                         - ellipse_mask(shape, cx, bot + h * 0.004, gw * 0.9, ery * 0.8, feather=3),
                         0, 1)
        img = over(img, np.broadcast_to(hexc("#CFC5B0"), (h, w, 3)) * 0.42, saucer * 0.9)
    else:
        # the glass mostly shows what is behind it, a little dimmed and warmed
        img = img * (1 - 0.20 * body)[..., None]
        img = img + (body * cyl)[..., None] * GOLD * 0.045

    # --- liquid: a filled cylinder below an elliptical surface
    below = np.clip((yy - level) / 2.0 + 0.5, 0, 1)
    liq = body * below
    if not opaque:
        liq = liq * np.clip((bot - yy) / 2.0 + 0.5, 0, 1)
    depth = np.clip((yy - level) / max(2 * gh, 1e-3), 0, 1)
    lalb = np.broadcast_to(lc, (h, w, 3)) * (0.55 + 0.85 * (1 - depth))[..., None]
    lalb = lalb * cyl[..., None] * (0.45 + 1.05 * pool[..., None])
    img = over(img, lalb, liq * 0.95)

    # the surface itself — the strongest single cue that this is a liquid
    srx, sry = gw * (taper + (1 - taper) * np.clip((level - top) / (2 * gh), 0, 1)), ery * 0.92
    surface = ellipse_mask(shape, cx, level, srx, sry, feather=2.0) * body
    img = over(img, lalb * 1.12 + GOLD_WARM * 0.06, surface * 0.90)
    srim = np.clip(surface - ellipse_mask(shape, cx, level, srx * 0.93, sry * 0.86, feather=2), 0, 1)
    img = img + blur(srim, 1.4)[..., None] * GOLD_WARM * 0.45
    glint = dome(shape, cx - srx * 0.42, level - sry * 0.10, srx * 0.26, sry * 0.30, power=0.8)
    img = img + blur(glint * surface, 2.0)[..., None] * CREAM * 0.55

    # --- ice, half in and half out of the surface
    for k in range(ice):
        ix = cx + rng.uniform(-0.40, 0.40) * gw
        iy = level + rng.uniform(-0.10, 0.55) * gh
        ir = gw * rng.uniform(0.34, 0.48)
        cube = superellipse(shape, ix, iy, ir, ir * rng.uniform(0.82, 1.05), n=3.4, feather=2.0)
        cube = cube * body
        face = dome(shape, ix - ir * 0.2, iy - ir * 0.25, ir * 0.7, ir * 0.55, power=0.9)
        img = over(img, lalb * 0.55 + CREAM * 0.16, cube * 0.40)
        img = img + blur(face * cube, 3.0)[..., None] * CREAM * 0.22
        edge = np.clip(cube - superellipse(shape, ix, iy, ir * 0.86, ir * 0.86, n=3.4), 0, 1)
        img = img + blur(edge, 1.8)[..., None] * CREAM * 0.11

    if foam:
        fm = body * np.clip(1 - np.abs(yy - level) / (h * 0.026), 0, 1)
        ftex = value_noise(shape, rng, octaves=7, base=22)
        fcol = np.broadcast_to(hexc(foam), (h, w, 3)) * (0.55 + 0.60 * ftex[..., None]) \
            * (0.5 + 1.0 * pool[..., None])
        img = over(img, fcol, np.clip(fm * 1.5, 0, 1) * 0.90)

    if not opaque:
        # walls: a thin catch of light down each side, brighter on the key side
        inner = np.clip((halfw * 0.90 - np.abs(xx - cx)) / 2.0 + 0.5, 0, 1) * body
        wall = np.clip(body - inner, 0, 1) * (yy > top)
        keyside = np.clip((cx - xx) / (gw * 0.9), 0, 1)
        img = img + blur(wall * keyside, 1.6)[..., None] * GOLD_WARM * 0.55
        img = img + blur(wall * (1 - keyside), 2.2)[..., None] * GOLD * 0.20

        # thick glass foot picks up far more light than the walls
        img = img + blur(foot * (yy > bot - ery * 0.9), 2.5)[..., None] * GOLD_WARM * 0.30

    # the mouth: an ellipse ring, the near lip brighter than the far one
    rim = np.clip(mouth - ellipse_mask(shape, cx, top, gw * 0.93, ery * 0.86, feather=2), 0, 1)
    near = np.clip((yy - top) / (ery * 1.4) + 0.35, 0, 1)
    img = img + blur(rim * (0.35 + 0.85 * near), 1.3)[..., None] * GOLD_WARM * 0.75
    if not opaque:
        # looking down into the empty part of the glass
        throat = ellipse_mask(shape, cx, top, gw * 0.90, ery * 0.86, feather=2) \
            * np.clip((level - yy) / 2.0 + 0.5, 0, 1)
        img = img * (1 - 0.35 * throat)[..., None]

    if garnish:
        gcol = hexc(garnish)
        gm = dome(shape, cx + gw * 0.52, top - ery * 0.30, w * 0.048, w * 0.021,
                  power=0.7, angle=-0.45)
        gl = shade(gm * 0.12, np.broadcast_to(gcol, (h, w, 3)), relief=140, ambient=0.28,
                   spec_power=20, spec=0.3)
        img = over(img, gl, np.clip(gm * 2.4, 0, 1) * 0.9)

    if form in ("tumbler", "highball"):
        drops = value_noise(shape, rng, octaves=8, base=46)
        dm = np.clip(drops - 0.80, 0, 1) * 5 * body * (yy > level)
        img = img + blur(dm, 0.9)[..., None] * CREAM * 0.20

    focus = np.exp(-(((yy / h) - 0.50) ** 2) / (2 * 0.26 ** 2))
    img = img * focus[..., None] + blur(img, 12) * (1 - focus)[..., None]
    return grade(img, rng, bloom=0.20, vig=0.84, saturation=saturation * 0.88)


# ---------------------------------------------------------------------------
# scene: interior / architecture
# ---------------------------------------------------------------------------


def scene_room(seed, *, size=(900, 1400), mood="dining", warm=1.0):
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    xx, yy = grid(shape)

    wall = value_noise(shape, rng, octaves=6, base=3)
    img = np.broadcast_to(INK * 1.5, (h, w, 3)).copy() * (0.55 + 0.9 * wall[..., None])
    img = img * np.array([1.10, 1.0, 0.86])

    # a colonnade of warm arches receding into the dark
    if mood in ("dining", "bar"):
        for i, fx in enumerate(np.linspace(0.10, 0.90, 5)):
            cx = w * fx
            aw, ah = w * 0.085, h * 0.30
            cy = h * 0.36
            arch = ellipse_mask(shape, cx, cy, aw, ah, feather=5)
            col = ((np.abs(yy - cy) < ah) & (np.abs(xx - cx) < aw)).astype(np.float32)
            body = np.clip(arch + col * (yy > cy).astype(np.float32), 0, 1)
            glow = blur(body, 26)
            img = img + glow[..., None] * GOLD_WARM * (0.10 + 0.05 * (i % 2)) * warm
            img = over(img, np.broadcast_to(INK * 0.6, (h, w, 3)), blur(body, 2) * 0.55)

    # pendant lights / candles — bokeh
    n_lights = 9 if mood == "dining" else 14
    for _ in range(n_lights):
        cx = rng.uniform(0.05, 0.95) * w
        cy = rng.uniform(0.06, 0.52) * h
        r = w * rng.uniform(0.006, 0.020)
        core = dome(shape, cx, cy, r, r, power=0.5)
        img = img + blur(core, 1.2)[..., None] * GOLD_WARM * 2.4
        img = img + blur(core, 34)[..., None] * GOLD_WARM * rng.uniform(0.5, 1.3) * warm
        img = img + blur(core, 90)[..., None] * GOLD * 0.35 * warm

    if mood == "kitchen":
        # the pass: a row of heat lamps over brushed steel, fire behind
        for fx in np.linspace(0.16, 0.84, 5):
            lx, ly = w * fx, h * 0.175
            lamp = dome(shape, lx, ly, w * 0.038, h * 0.020, power=0.45)
            img = img + blur(lamp, 3)[..., None] * GOLD_WARM * 1.5
            img = img + blur(lamp, 30)[..., None] * GOLD_WARM * 0.55
            img = img + blur(lamp, 85)[..., None] * GOLD * 0.22
            stem = ((np.abs(xx - lx) < w * 0.0022) & (yy < ly)).astype(np.float32)
            img = over(img, np.broadcast_to(INK * 0.5, (h, w, 3)), blur(stem, 1.2) * 0.8)

        # fire behind the pass, thrown out of focus
        for _ in range(3):
            fx, fy = rng.uniform(0.15, 0.85) * w, rng.uniform(0.40, 0.52) * h
            fl = dome(shape, fx, fy, w * 0.10, h * 0.055,
                      warp=value_noise(shape, rng, octaves=5, base=8), wob=1.1, power=0.6)
            img = img + blur(fl, 26)[..., None] * np.array([1.0, 0.48, 0.14]) * 0.85

        # brushed steel, lit from above, with a hot specular lip
        steel = np.clip((yy / h - 0.60) * 4.6, 0, 1)
        brush = value_noise(shape, rng, octaves=4, base=int(rng.integers(30, 50)))
        # falls away fast, so the foreground sinks into the dark
        grad = np.clip(1.15 - (yy / h - 0.60) * 3.1, 0, 1.3)
        steel_col = np.broadcast_to(hexc("#3A362E"), (h, w, 3)) \
            * (0.50 + 0.80 * brush[..., None]) * grad[..., None]
        img = over(img, steel_col, steel * 0.94)
        lip = np.exp(-((yy - h * 0.615) / (h * 0.005)) ** 2)
        img = img + lip[..., None] * GOLD_WARM * 0.45
        img = img + blur(lip, 22)[..., None] * GOLD_WARM * 0.30

        # plates waiting on the pass
        for px in np.linspace(0.22, 0.78, 4):
            pcx2, pcy2 = w * px, h * 0.700
            pl = ellipse_mask(shape, pcx2, pcy2, w * 0.066, h * 0.023, feather=2.5)
            img = img * (1 - 0.55 * blur(pl, 9))[..., None]
            img = over(img, np.broadcast_to(hexc("#CFC6B2"), (h, w, 3)) * 0.42, pl * 0.9)
            rim2 = np.clip(pl - ellipse_mask(shape, pcx2, pcy2, w * 0.058, h * 0.018, feather=2.5), 0, 1)
            img = img + blur(rim2, 1.4)[..., None] * GOLD_WARM * 0.55

        steam2 = value_noise(shape, rng, octaves=4, base=3)
        veil2 = np.clip((0.62 - yy / h) * 2.0, 0, 1) * np.clip(steam2 - 0.46, 0, 1) * 1.8
        img = img + blur(veil2, 26)[..., None] * CREAM * 0.10

    # tables / counter in the foreground, in shadow
    front = np.clip((yy / h - 0.63) * 5.0, 0, 1)
    tex = value_noise(shape, rng, octaves=5, base=4)
    surf = np.broadcast_to(hexc("#241E18"), (h, w, 3)) * (0.55 + 0.95 * tex[..., None])
    img = over(img, surf, front * 0.90)
    edge = np.exp(-((yy - h * 0.665) / (h * 0.012)) ** 2)
    img = img + edge[..., None] * GOLD * 0.30

    if mood == "dining":
        for _ in range(6):
            cx = rng.uniform(0.05, 0.95) * w
            cy = rng.uniform(0.70, 0.96) * h
            gm = dome(shape, cx, cy, w * rng.uniform(0.012, 0.03), h * rng.uniform(0.02, 0.05),
                      power=0.4)
            img = img + blur(gm, 5)[..., None] * GOLD_WARM * 0.55
            img = img + blur(gm, 42)[..., None] * GOLD_WARM * 0.22

    focus = np.exp(-(((yy / h) - 0.42) ** 2) / (2 * 0.30 ** 2))
    img = img * focus[..., None] + blur(img, 9) * (1 - focus)[..., None]
    return grade(img, rng, bloom=0.42, vig=0.80, saturation=0.94)


def scene_hearth(seed, *, size=(1100, 900)):
    """A bed of coals under the grill.

    No figure is attempted anywhere in this image set: a procedurally generated
    human reads as a cartoon, and the chef is introduced in words instead. Fire
    is what this renderer is actually good at, so fire is what carries the story
    section.
    """
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    xx, yy = grid(shape)

    img = np.broadcast_to(INK * 1.1, (h, w, 3)).copy()
    smoke = value_noise(shape, rng, octaves=6, base=3)
    img = img * (0.4 + 1.1 * smoke[..., None]) * np.array([1.15, 1.0, 0.82])

    # --- the coal bed: a height field whose hottest ridges emit light
    height = np.zeros(shape, dtype=np.float32)
    for _ in range(46):
        cxc = rng.uniform(-0.05, 1.05) * w
        cyc = rng.uniform(0.34, 1.02) * h
        r = w * rng.uniform(0.035, 0.095)
        n = value_noise(shape, rng, octaves=4, base=int(rng.integers(6, 14)))
        height = np.maximum(height, dome(shape, cxc, cyc, r, r * rng.uniform(0.5, 0.85),
                                         warp=n, wob=0.5, power=rng.uniform(0.4, 0.7),
                                         angle=rng.uniform(0, math.pi)) * rng.uniform(0.6, 1.0))
    bed = np.clip((yy / h - 0.30) * 4.0, 0, 1)
    height = blur(height, 1.5) * bed

    # heat varies across the bed; the near edge is hotter than the back
    heat = value_noise(shape, rng, octaves=5, base=4)
    heat = np.clip(heat * 1.10 + (yy / h - 0.46) * 0.34, 0, 1.15) * bed
    heat = blur(heat, 5)

    ash = np.broadcast_to(hexc("#3A322C"), (h, w, 3))
    coal = shade(height, ash, relief=120, ambient=0.10, spec_power=20, spec=0.10,
                 light_col=np.array([1.0, 0.72, 0.42]))
    # emission: dull red through orange to a white core
    e = np.clip(heat - 0.30, 0, 1)
    ember = (e ** 1.7)[..., None] * np.array([1.00, 0.30, 0.06]) * 2.0 \
          + (np.clip(heat - 0.80, 0, 1) ** 1.5)[..., None] * np.array([1.0, 0.78, 0.40]) * 2.2
    glow = np.clip(height, 0, 1)
    img = over(img, coal + ember, np.clip(glow * 2.2, 0, 1) * bed)
    img = img + blur(ember, 30) * 0.40 + blur(ember, 90) * 0.16

    # --- grill bars over the coals
    for by in np.linspace(0.44, 0.96, 6):
        yb = h * by
        thick = h * (0.010 + 0.004 * by)
        bar = np.exp(-((yy - yb) / thick) ** 2)
        img = over(img, np.broadcast_to(hexc("#1A1613"), (h, w, 3)), np.clip(bar * 1.4, 0, 1) * 0.82)
        top = np.exp(-((yy - (yb - thick * 0.75)) / (thick * 0.30)) ** 2)
        img = img + top[..., None] * np.array([1.0, 0.62, 0.28]) * 0.55

    # --- sparks lifting off the bed
    for _ in range(70):
        sx = rng.uniform(0, 1) * w
        sy = rng.uniform(0.05, 0.72) * h
        r = w * rng.uniform(0.0016, 0.0055)
        life = np.clip(1 - (0.72 - sy / h) * 1.5, 0.12, 1)
        sp = dome(shape, sx, sy, r, r * rng.uniform(1.0, 3.0), power=0.5)
        img = img + blur(sp, 1.0)[..., None] * np.array([1.0, 0.66, 0.30]) * 1.8 * life
        img = img + blur(sp, 12)[..., None] * np.array([1.0, 0.50, 0.18]) * 0.6 * life

    veil = np.clip((0.62 - yy / h) * 1.9, 0, 1) * np.clip(smoke - 0.40, 0, 1) * 2.0
    img = img + blur(veil, 30)[..., None] * np.array([1.0, 0.78, 0.55]) * 0.16

    focus = np.exp(-(((yy / h) - 0.62) ** 2) / (2 * 0.22 ** 2))
    img = img * focus[..., None] + blur(img, 13) * (1 - focus)[..., None]
    return grade(img, rng, bloom=0.45, vig=0.82, saturation=0.96)


def scene_texture(seed, *, size=(700, 700), tone="#2A2119", accent=GOLD):
    """Abstract macro — pour, char, embers. Used for the smaller gallery tiles."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    n1 = value_noise(shape, rng, octaves=7, base=3)
    n2 = value_noise(shape, rng, octaves=5, base=8)
    base = np.broadcast_to(hexc(tone), (h, w, 3)) * (0.35 + 1.5 * n1[..., None])
    ridge = np.abs(n2 - 0.5) * 2
    img = base + (1 - ridge)[..., None] * accent * 0.55 * np.clip(n1 - 0.35, 0, 1)[..., None] * 3
    ember = np.clip(n1 * n2 - 0.42, 0, 1)
    img = img + blur(ember, 6)[..., None] * np.array([1.0, 0.52, 0.18]) * 1.6
    xx, yy = grid(shape)
    pool = np.exp(-(((xx - w * 0.35) / (w * 0.6)) ** 2 + ((yy - h * 0.3) / (h * 0.6)) ** 2))
    img = img * (0.35 + 1.4 * pool[..., None])
    return grade(img, rng, bloom=0.5, vig=0.85, saturation=0.95)


def scene_monogram(seed, letters, *, size=(320, 320)):
    """Testimonial avatar: an engraved gold medallion, no invented faces."""
    rng = np.random.default_rng(seed)
    h, w = size
    shape = (h, w)
    n = value_noise(shape, rng, octaves=6, base=4)
    img = np.broadcast_to(hexc("#231D16"), (h, w, 3)).copy() * (0.6 + 1.1 * n[..., None])
    xx, yy = grid(shape)
    sweep = np.clip((xx / w) * 0.9 + (1 - yy / h) * 0.7, 0, 1.4)
    img = img + sweep[..., None] * GOLD * 0.30
    disc = ellipse_mask(shape, w / 2, h / 2, w * 0.46, h * 0.46, feather=2)
    img = img * (0.35 + 0.9 * disc)[..., None]
    ring = np.clip(ellipse_mask(shape, w / 2, h / 2, w * 0.455, h * 0.455, feather=2)
                   - ellipse_mask(shape, w / 2, h / 2, w * 0.425, h * 0.425, feather=2), 0, 1)
    img = img + blur(ring, 1.0)[..., None] * GOLD * 1.3
    out = grade(img, rng, bloom=0.35, vig=0.5, grain=0.010)

    # letters are drawn with Pillow after the grade so they stay crisp
    from PIL import ImageDraw, ImageFont
    im = Image.fromarray((np.clip(out, 0, 1) ** (1 / 1.06) * 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(im)
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(cand).exists():
            font = ImageFont.truetype(cand, int(h * 0.34))
            break
    if font is None:
        font = ImageFont.load_default()
    bb = d.textbbox((0, 0), letters, font=font)
    d.text(((w - bb[2] + bb[0]) / 2 - bb[0], (h - bb[3] + bb[1]) / 2 - bb[1]), letters,
           font=font, fill=(228, 205, 155))
    return np.asarray(im, dtype=np.float32) / 255


# ---------------------------------------------------------------------------
# the shot list
# ---------------------------------------------------------------------------

DISHES = [
    # key, seed, palette, kwargs — one per menu item, plus the signature spreads
    ("scallop", 11, ["#EBD6AC", "#D8BB82", "#C9A063", "#F4E8CC"],
     dict(plate="charcoal", garnish="#7E9070", sauce="#3E4C3A", components=7, relief=110)),
    ("aubergine", 19, ["#4A3A52", "#33253C", "#6B5573", "#241A2C"],
     dict(plate="slate", garnish="#8C9C7A", sauce="#D8CDB4", components=6, relief=100)),
    ("oyster", 141, ["#D4CDB8", "#B6AE98", "#E8E2CE", "#928C7C"],
     dict(plate="slate", garnish="#7E9070", sauce="#4C5442", components=5, relief=118)),
    ("beet", 91, ["#7E2648", "#9A335E", "#5C1933", "#BC6082"],
     dict(plate="bone", garnish="#7E9070", sauce="#501430", components=7, relief=94)),
    ("octopus", 51, ["#6E3E4A", "#4C2732", "#8E5862", "#301A22"],
     dict(plate="slate", garnish="#7E9070", sauce="#5C2C24", components=6, relief=106)),
    ("galouti", 29, ["#5E3A26", "#42281A", "#7A5034", "#916444"],
     dict(plate="charcoal", garnish="#6F8A62", sauce="#2E1B10", components=6, relief=98)),

    ("shortrib", 23, ["#7E3026", "#5E211B", "#96432F", "#401814"],
     dict(plate="charcoal", garnish="#8C9C7A", sauce="#2C1814", components=6, relief=100)),
    ("lamb", 79, ["#723826", "#4E251A", "#8C4C33", "#2E170F"],
     dict(plate="charcoal", garnish="#6F8A62", sauce="#3C1D14", components=6, relief=102)),
    ("truffle", 37, ["#E6D8B6", "#DAC9A0", "#90724A", "#F4EBD4"],
     dict(plate="bone", garnish="#6F6047", sauce=None, components=9, spread=0.50, relief=88)),
    ("lobster", 67, ["#DB9028", "#E8B45A", "#C4741D", "#F2C269"],
     dict(plate="bone", garnish="#7E9070", sauce="#B6631C", components=6, relief=96)),
    ("morel", 129, ["#5C4834", "#7C6246", "#423224", "#988260"],
     dict(plate="clay", garnish="#6F8A62", sauce="#322414", components=8, relief=104)),
    ("seabass", 47, ["#E2DCC8", "#C8C0A8", "#F0EBDA", "#A69E88"],
     dict(plate="charcoal", garnish="#7E9070", sauce="#46543E", components=6, relief=114)),
    ("paneer", 59, ["#F0E6CE", "#DCCFAE", "#C4B48E", "#FAF2DE"],
     dict(plate="clay", garnish="#7E9070", sauce="#B4541E", components=7, relief=100)),

    ("chocolate", 103, ["#3C2219", "#2C1611", "#502E20", "#6A422C"],
     dict(plate="slate", garnish="#C9A86A", sauce="#200F0A", components=5, relief=98, crumb=0.05)),
    ("mangotart", 153, ["#DAB674", "#C49C52", "#F0DEB0", "#AA803A"],
     dict(plate="bone", garnish="#8C9C7A", sauce=None, components=6, relief=94, crumb=0.06)),
    ("citrus", 117, ["#EACA6C", "#F2E1AA", "#D6A83E", "#FCF2D4"],
     dict(plate="charcoal", garnish="#7E9070", sauce="#C28C26", components=6, relief=90)),
    ("kulfi", 163, ["#F2E6DC", "#E0CFC2", "#C8A8B4", "#FAF2EA"],
     dict(plate="slate", garnish="#7E9070", sauce="#9E6478", components=5, relief=104)),
    ("jamun", 173, ["#5A3220", "#3E2016", "#764430", "#8E5A3C"],
     dict(plate="bone", garnish="#C9A86A", sauce="#2A1409", components=5, relief=96)),
]

DRINKS = [
    ("oldfashioned", 501, "#A85E1E", dict(form="tumbler", ice=2, garnish="#B4783C")),
    ("ginsour", 511, "#C4922E", dict(form="coupe", ice=0, foam="#F2EADA", garnish="#7E9070")),
    ("kokum", 521, "#7E1E30", dict(form="highball", ice=3, garnish="#7E9070")),
    ("coffee", 531, "#4A2A18", dict(form="cup", ice=0, foam="#C9A276")),
    ("tea", 541, "#B4762E", dict(form="cup", ice=0)),
    ("wine", 551, "#6E1E30", dict(form="coupe", ice=0)),
]


def main():
    print("rendering AURELIA image set →", OUT)

    hero = scene_dish(7, ["#CFA05A", "#E4C288", "#94622E", "#F4DCAA"],
                      size=(1200, 2000), plate="charcoal", garnish="#7E9070",
                      sauce="#3E2C1A", components=10, spread=0.58, relief=105)
    # Three widths: a phone should not download, decode and downscale a 2000px
    # hero on a throttled CPU just to show it 390px wide.
    for w in (900, 1400, 2000):
        save(hero, f"hero-{w}", quality=82, width=w)
    save(hero, "hero", quality=82)
    # social scrapers want a JPEG; a webp twin here would never be fetched
    save(hero, "og", quality=80, width=1200, webp=False)

    for name, seed, pal, kw in DISHES:
        save(scene_dish(seed, pal, **kw), f"dish-{name}")

    for name, seed, liquid, kw in DRINKS:
        save(scene_drink(seed, liquid, **kw), f"dish-{name}")

    save(scene_room(201, mood="dining", size=(1000, 1500)), "interior-dining")
    save(scene_room(211, mood="bar", size=(1000, 1400)), "interior-bar")
    save(scene_room(221, mood="kitchen", size=(1000, 1400)), "kitchen-pass")
    save(scene_hearth(231), "hearth")
    save(scene_room(241, mood="dining", size=(900, 1200), warm=1.25), "gallery-room")

    save(scene_texture(301, tone="#2E2117"), "texture-ember")
    save(scene_texture(311, tone="#1E2620", accent=np.array([0.55, 0.70, 0.50])), "texture-herb")
    save(scene_texture(321, tone="#33231A"), "texture-char")

    for i, initials in enumerate(["AR", "MK", "SD", "JL", "PN", "TV"]):
        save(scene_monogram(400 + i * 7, initials), f"avatar-{i + 1}", quality=88)

    print("done")


if __name__ == "__main__":
    main()
