# NOTES — modelling assumptions and known limitations

This file is part of the deliverable, not commentary on it. Every assumption
that could change a number, and every limitation that could make a number
wrong, is written down here as it is made. A solver whose errors are
understood is worth more than one whose numbers cannot be defended.

Entries are append-only within a phase. If an assumption is later found to be
wrong it is **struck through and annotated**, not deleted — the history of
what was believed matters when re-reading an old result.

---

## Global conventions

These are asserted once here and repeated in every module docstring.

| Quantity | Convention |
|---|---|
| Angles | **Radians** everywhere in function signatures and returns. Degrees only in the CLI, file formats, and plot labels. Exceptions carry a `_deg` suffix. |
| Airfoil coordinates | Non-dimensionalised by chord `c`. `x` = 0 at LE, 1 at TE, aft along the chord line. `z` positive up. |
| Surface ordering | Selig internally: TE → upper surface → LE → lower surface → TE. Imported files are converted to this on entry. |
| 3D frame | `x` aft, `y` to starboard, `z` up (right-handed). |
| Sectional coefficients | Non-dimensionalised by `q_inf * c` per unit span, `q_inf = ½ρV∞²`. |
| 3D coefficients | Non-dimensionalised by `q_inf * S_ref`. |
| Pitching moment | `Cm` positive **nose-up**, about the quarter chord unless stated. |
| Pressure coefficient | `Cp = (p − p∞)/q_inf`. |
| Reynolds number | Based on **chord** unless the name says `Re_theta`. |

---

## Phase 0 — Environment and skeleton

*Recorded 2026-08-08.*

### Assumptions

- **A0.1 — Incompressible baseline.** The whole package is built on an
  incompressible, irrotational core. Compressibility enters only as a
  correction applied afterwards (Phase 5), never as a change to the governing
  equations. This is defensible below roughly M = 0.6–0.7 and nowhere above it.
- **A0.2 — Steady flow only.** No unsteady terms anywhere. Every result is a
  converged steady state. This rules out flutter, buffet, dynamic stall, and
  any post-stall behaviour that is genuinely time-dependent — which matters
  for how far the Phase 4 lift curve can be trusted past `Cl_max`.
- **A0.3 — Float64 throughout.** All numerics in double precision. Panel
  method influence matrices are dense and ill-conditioned near a sharp
  trailing edge; single precision would not survive that.
- **A0.4 — `conda-forge` channel.** NumPy and SciPy come from conda-forge and
  link against Apple's Accelerate framework on this machine. This is a
  *performance* choice, but it is also a *reproducibility* caveat: BLAS
  implementations differ in the last few ULP, so a dense solve on another
  machine may differ in the ~14th significant figure. Validation tolerances
  are set far above that threshold and this has never been the cause of a
  disagreement — but it is why exact float equality is never asserted in
  tests.

### Limitations

- **L0.1 — No CFD.** This is a potential-flow plus integral-boundary-layer
  toolkit. It cannot resolve separated wakes, shock–boundary-layer
  interaction, or any genuinely three-dimensional separation. Where the
  methods break down, the intention is to say so and stop, not to return a
  number.

### Decisions worth recording

- **D0.1 — `miniforge` was not actually installed** on the machine at the
  start of Phase 0, despite being expected. Installed via
  `brew install --cask miniforge` (installs to `/opt/homebrew/Caskroom/`,
  symlinks `conda` into `/opt/homebrew/bin`, no `sudo` required on Apple
  Silicon). `conda init zsh` created `~/.zshrc`, which did not previously
  exist.
- **D0.2 — Environment pinned to Python 3.12** per the project standard, not
  to the system Python (Homebrew 3.14.3). Solver behaviour does not depend on
  the interpreter version, but the pin makes the environment reproducible.
- **D0.3 — Exception hierarchy defined before any solver exists**
  (`aerolab/exceptions.py`). Writing `ConvergenceError` first, with mandatory
  `iterations` / `residual` / `tolerance` fields, makes it harder to later add
  a solver that quietly returns an unconverged answer — the ergonomic path is
  to raise properly.
- **D0.4 — A truly empty test suite is not a passing state.** `pytest` exits
  with code 5 ("no tests ran") when it collects nothing, which is
  indistinguishable from a broken test path. Phase 0 therefore ships smoke
  tests of the *plumbing* (imports, CLI, exception contract) rather than zero
  tests, so that a green run means something. No physics is asserted yet.

---

## Phase 1 — Geometry

*Recorded 2026-08-09.*

### Conventions fixed in this phase

- **C1.1 — Selig order is counter-clockwise.** Walking trailing edge → upper
  surface → leading edge → lower surface → trailing edge traverses the contour
  **counter-clockwise** in the (x, z) plane, so the signed shoelace area is
  **positive**. The upper surface is walked right-to-left across positive `z`,
  which is the positive sense of rotation.

  This was initially asserted the wrong way round, and the consequences were
  instructive: `Airfoil.from_points` dutifully "repaired" every airfoil by
  reversing it, silently swapping the upper and lower surfaces. Thickness came
  out negative, maximum thickness was reported at `x/c = 1.0`, and every panel
  normal pointed into the section. None of it raised. The invariant is now
  asserted in the constructor and verified independently in the tests by the
  divergence theorem (see V1.3).
- **C1.2 — Outward panel normal is `n = (t_z, -t_x)`.** For a counter-clockwise
  contour the interior lies to the left of the direction of travel, so outward
  is the tangent rotated −90°. Check on the upper surface, where `t = (-1, 0)`
  and the formula gives `n = (0, +1)`.
- **C1.3 — Trailing-edge default is closed.** `naca(...)` closes the trailing
  edge by default (`closed_te=True`), matching the Phase 1 acceptance criterion.
  `closed_te=False` gives the original open form. This is a *geometry* default
  and is independent of how the Phase 2 solver treats a finite base.

### Assumptions

- **A1.1 — Closing the trailing edge perturbs the whole thickness polynomial.**
  The original NACA quartic coefficient is `-0.1015`, for which the five
  coefficients sum to `0.0021` and leave a half-gap of `0.0105·t` at `x = 1`.
  The closed variant uses `-0.1036` so they sum to exactly zero. That is not a
  local edit: it changes the polynomial everywhere. A closed-trailing-edge
  "12%" section has maximum thickness `0.120013c` at `x/c = 0.29953`, against
  `0.120035c` at `x/c = 0.29983` for the open form.
- **A1.2 — A "12% thick" NACA section is 12.0035% thick.** The thickness
  polynomial reaches `1.000288` times its nominal value, not exactly the
  nominal value. This is a property of the 1932 coefficient fit, not of this
  implementation, and the ratio is identical at every thickness because the
  polynomial scales linearly. Pinned as a fixed ratio in the tests so that a
  genuine change to the coefficients would be caught.
- **A1.3 — 5-digit constants are derived, never tabulated.** `m` comes from
  inverting `x_f = m(1 - sqrt(m/3))`; for the reflexed series it comes instead
  from imposing `Cm_c/4 = 0`. `k1` comes from `Cl_i = pi·A1` at the ideal angle.
  The published Abbott & von Doenhoff tables are used only as a cross-check.
  Agreement is 0.2% on `m` and 0.3% on `k1` for the standard series.
- **A1.4 — Thickness and camber are measured on vertical cuts.**
  `thickness_at` returns `z_upper(x) − z_lower(x)` at a common `x`. That is
  *not* the NACA thickness function `2·y_t(x)`, which is laid off perpendicular
  to the camber line at shifted `x` stations. The two agree exactly for a
  symmetric section. For a cambered one they differ, and the difference is real
  geometry rather than numerical error: the vertical-cut camber of NACA 23012
  peaks at `x/c = 0.1436`, not at the nominal `x_f = 0.15`, and that location is
  stable to five decimal places from 201 to 3201 points.

  The vertical definition is used because it is the only one that is well posed
  for an arbitrary imported airfoil, whose camber line is not known a priori.
- **A1.5 — Surfaces are interpolated in `sqrt(x)`, not `x`.** An airfoil
  surface behaves like `z ~ sqrt(x)` at the nose, which has infinite slope
  there. In `xi = sqrt(x - x_le)` it is very nearly linear, so a monotone cubic
  (PCHIP) is accurate right up to the leading edge. PCHIP rather than a natural
  cubic spline because it is shape-preserving: a spline's overshoot near the
  nose would appear directly as a wrong leading-edge thickness.
- **A1.6 — Cosine clustering is the inverse Beta(½, ½) CDF.** The Beta CDF for
  `a = b = 1/2` is `(2/pi)·arcsin(sqrt(t))`, whose inverse is
  `(1 - cos(pi·u))/2` — classical cosine spacing exactly. Generalising to
  independent exponents gives one knob per end, guaranteed monotone, with the
  classical distributions recovered to machine precision (`a = b = 1` is
  uniform). This is why the clustering parameters are Beta exponents where
  *smaller means denser*, which reads backwards until you know where it comes
  from.
- **A1.7 — Repaneling splines against arc length with natural end conditions.**
  Arc length because a surface is double-valued in `x`; natural (not periodic)
  end conditions because the trailing edge is a genuine corner with a finite
  included angle, and smoothing across it would change the Kutta condition the
  Phase 2 solver applies there.
- **A1.8 — Panel counts are split between surfaces by arc length.** Default
  `split="arclength"` gives both surfaces the same resolution; `split="even"`
  gives them the same count. Identical for a symmetric section, a few percent
  apart for a strongly cambered one.

### Limitations

- **L1.1 — The published `k1` for the NACA 210 mean line is internally
  inconsistent.** Feeding the tabulated pair (`m = 0.0580`, `k1 = 361.4`) into
  thin airfoil theory gives `Cl_i = 0.3084`, 2.8% above the 0.3 that *defines*
  the series. Sensitivity does not explain it: `d(ln k1)/d(ln m) ≈ -2.5` and the
  tabulated `m` is 0.13% from the true root, which accounts for about a tenth of
  the discrepancy. The derived pair gives `Cl_i = 0.30000`.

  This package uses the derived value. The discrepancy is pinned in a test so
  that it stays attributed to the table and cannot later be blamed on a solver
  change. The other four standard rows agree to 0.3%.
- **L1.2 — Only 4- and 5-digit sections are implemented.** The 6-series mean
  lines and thickness forms are defined by conformal mapping, not by closed-form
  polynomials, and are refused rather than approximated.
- **L1.3 — Cambered leading-edge radius is good to about 1%, no better.** For
  *symmetric* sections the nose-radius estimator reproduces the closed-form
  `1.1019·t²` to 0.01%, and moves by only 0.002% between 201 and 3201 points.
  For *cambered* sections it lands within about 0.7% (measured: +0.2% for 2412,
  +0.7% for 4412, −0.6% for 23012) but wanders by up to 0.8% with point count.

  The scatter is the same size as the departure, so **the sign of the departure
  from the symmetric value is not resolved** and no claim is made about it. The
  limitation is the leading-edge frame: for a cambered section the nose axis
  comes from the spline tangent at the refined leading edge, which carries its
  own discretisation error. An early attempt to predict the departure as
  `1.1019·t²·cos(theta_0)` was wrong — it predicted −0.5% for NACA 2412 where
  the measurement gives +0.2% — and has been withdrawn rather than tuned to fit.
- **L1.4 — `k2/k1` for the reflexed series is ill-conditioned.**
  `r = [3(m − x_f)² − m³]/(1 − m)³` is a difference of two nearly equal numbers.
  `d(ln r)/d(ln m)` reaches 34 at `x_f = 0.10`, so the four-decimal rounding of
  the published `m` moves `r` by 20%. Evaluating the same formula *at the
  table's own `m`* reproduces the table to five significant figures, which
  separates the formula (correct) from its conditioning (genuinely poor). The
  tests assert both facts separately.
- **L1.5 — Maximum-camber location is ill-conditioned for 4-digit sections.**
  Near its peak the 4-digit mean line is a flat parabola (`y_c'' = -2m/p²`, only
  −0.25 for NACA 2412), so the argmax shifts by several thousandths of a chord
  under perturbations of order 1e-6. The peak *value* is not ill-conditioned and
  is asserted tightly; the location is asserted to ±0.015c.
- **L1.6 — Shoelace area understates a convex section.** The discrete polygon
  cuts the corners, converging at second order: the error falls by exactly a
  factor of 4 per doubling (measured 4.00, 4.00, 3.99). A 201-point NACA 0012
  understates the true area by 0.016%. This matters when comparing areas at
  *different* point counts — most of the change in a 201 → 161 repanel is this
  effect, not resplining error.
- **L1.7 — The leading-edge point of a cambered section is not the origin.**
  It is the point furthest from the trailing edge, and the perpendicular offset
  construction puts that a few thousandths of a chord above and slightly ahead
  of `(0, 0)` — for NACA 2412, at `(-2.97e-5, +2.79e-3)`. The contour still
  passes through the origin. A consequence is that `normalize()` is not the
  identity on a cambered NACA section.

### Validation performed

- **V1.1 — Against closed-form results.** Thickness-polynomial maximum and its
  station; open/closed trailing-edge gaps; leading-edge radius `1.1019·t²`;
  enclosed area as the exact integral of the thickness polynomial;
  trailing-edge included angle from the analytic surface slope; 4-digit camber
  peak value and location; slope continuity at the camber junction.
- **V1.2 — Against an analytic ellipse.** Area `pi·a·b`, thickness
  `2b·sqrt(1 − ((x−a)/a)²)`, zero camber, nose radius `b²/a`, and Ramanujan's
  perimeter. An ellipse is used so that the container's geometry code is checked
  against something the NACA generator had no hand in producing.
- **V1.3 — Panel normals by the divergence theorem.** For `F = (x, z)`,
  `div F = 2`, so `∮ F·n ds = 2·Area` — exactly, on a polygon. Inward normals
  would give `−2·Area`, so the sign of that sum *is* the orientation. This
  appeals only to the shoelace area and is independent of the rotation formula
  under test. Verified to 1e-12 relative on four sections, plus the open
  trailing-edge case where the missing base segment is added back explicitly.
- **V1.4 — Against published data.** Abbott & von Doenhoff 5-digit mean-line
  constants, standard and reflexed; see A1.3, L1.1, L1.4.
- **V1.5 — Internal consistency of derived constants.** Every solved 5-digit
  mean line is checked to reach its design lift coefficient to 1e-9 relative,
  and every reflexed one to give `Cm_c/4 = 0` to 1e-12 absolute.

### Versions as built

| Package | Version |
|---|---|
| Python | 3.12.13 |
| NumPy | 2.5.1 |
| SciPy | 1.18.0 |
| Matplotlib | 3.11.1 |
| Typer | 0.27.1 |
| pytest | 9.1.1 |
