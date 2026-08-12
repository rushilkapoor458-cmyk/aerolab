# aerolab

A 2D/3D subsonic aerodynamics toolkit — the virtual half of a small
aerodynamic testing facility. The other half is a physical open-circuit wind
tunnel; Phase 7 is the bridge between them.

The goal is not "code that produces plots". It is a solver whose error bounds
are known, stated, and validated against published data.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Environment, package skeleton, test harness | **complete** |
| 1 | Geometry: NACA generators, `.dat` import, repaneling | **complete** |
| 2 | Inviscid 2D: Hess–Smith panel method | **complete** |
| 3 | Viscous: integral boundary layer, transition, profile drag | **complete** |
| 4 | Viscous–inviscid coupling, sequential | **abandoned**, diagnosed — spectral radius 15.5, [`NOTES.md`](NOTES.md) L4.5 |
| 5 | Polars, CLI, PDF reporting, compressibility corrections | **complete** |
| 6 | Finite wings: vortex lattice | **complete** |
| 7 | Tunnel corrections and experimental validation | **complete** |
| 8 | **Simultaneous Newton coupling** — replaces Phase 4 | **complete** for attached flow |
| 9–10 | Drela lag closure, shear stress as a fourth unknown | implemented and validated on a flat plate; does not yet converge on an aerofoil — [`NOTES.md`](NOTES.md) L10.1 |

### What is solved, and to what accuracy

Every figure below is measured against an exact solution or published data,
never against this package's own earlier output.

| Check | Result | Reference |
|---|---|---|
| Blasius `f''(0)`, `H`, `H*`, `Re_θ c_f/2` | 6 figures | exact, solved here |
| Blasius `θ` through the integral method | 0.031% | exact |
| Falkner–Skan `H` held, β = −0.1 / −0.15 | 0.09% / 0.57% | exact |
| Turbulent flat plate `H`, `θ` (lag closure) | 1.8% / 1.8% | Coles, 1/7-power |
| Cylinder surface `Cp` | 2.7e-15 | exact |
| Joukowski `Cl` | 2.5e-5 | conformal map |
| NACA 0012 `dCl/dα` | 6.914 /rad | 6.93 ± 0.02 |
| NACA 0012 `Cd`, Re 3e6, coupled | 0.00556 (−7.4%) | A&vD 0.0060 |
| Transition `x/c`, Re 3e6, N = 9 | 0.455 | XFOIL 0.45–0.50 |
| Elliptic wing span efficiency | 0.9964 | 1.0000 exact |
| Critical Mach vs sonic `Cp*` | 7.7e-14 | exact |
| Tunnel correction round trip | 0.0 | exact |

### Where it stops

The coupled solver converges wherever Head's entrainment correlation is valid,
which on a NACA 0012 at Re = 3e6 means up to about **5–6 degrees**. Past that
the correlation stops determining the shape factor — `dH1/dH` falls by a factor
of 460 between H = 1.4 and H = 4.0 — and the solver says so and refuses the
result rather than returning it. The fix is written up as L10.1: XFOIL's split
transition interval, a change to the station layout rather than the closure.

## Install

Requires [miniforge](https://github.com/conda-forge/miniforge) (or any conda).

```bash
conda env create -f environment.yml
conda activate aerolab
pip install -e ".[dev]"
```

## Run it

One command runs everything and prints each result beside the reference it is
checked against. Takes about 8 seconds.

```bash
python run_demo.py
```

```bash
pytest -q
```

```python
from aerolab.geometry import naca, repanel, read_dat, Panels

af = naca("2412")                     # 4- and 5-digit, analytic camber lines
af.max_thickness                      # Extremum(value=0.1200, x=0.2982)
af.le_radius, af.area, af.te_gap

coarse = repanel(af, 161)             # cosine-clustered, independent LE/TE control
panels = Panels(coarse)               # control points, tangents, outward normals

imported = read_dat("s1223.dat")      # Selig/Lednicer detected, not guessed
imported.detected_format              # 'lednicer'
```

```python
import numpy as np
from aerolab.geometry import naca
from aerolab.inviscid import HessSmithSystem

system = HessSmithSystem(naca("2412", 401))   # factorised once
sol = system.solve(np.deg2rad(5.0))           # alpha in RADIANS

sol.cl_pressure, sol.cl_kutta_joukowski       # two independent routes
sol.cm_quarter_chord                          # positive nose-up
sol.cd_pressure                               # ~0 by D'Alembert: an error measure
sol.cp, sol.control_points                    # surface pressure distribution
sol.velocity_at([[2.0, 0.5]])                 # field query anywhere

# A sweep costs no further factorisations: the freestream enters linearly.
sols = system.solve_sweep(np.deg2rad(np.arange(-6, 16, 0.5)))
```

`solve()` **refuses** to return a result whose two lift calculations disagree by
more than 0.5%; pass `validate=False` to override deliberately.

The **coupled** solver — the boundary layer and the outer flow solved
simultaneously by Newton's method, so the displacement effect feeds back into
the pressure field:

```python
import numpy as np
from aerolab.geometry import naca
from aerolab.viscous import solve_newton, newton_polar

r = solve_newton(naca("0012", 161), np.deg2rad(4.0), reynolds=3e6)
r.cl, r.cd, r.cm_quarter_chord
r.transition_x               # (upper, lower) as x/c
r.theta, r.delta_star, r.ue, r.shear     # the four unknowns, per station
r.max_shape_factor, r.closure_in_range   # is the closure being extrapolated?

# A sweep, each angle continued from the last:
sweep = newton_polar(naca("0012", 161), np.deg2rad(np.arange(0, 6, 1.0)), 3e6)
```

It converges in four to seven Newton steps and **raises rather than returning a
number** if it does not. `turbulent_closure="lag"` selects Drela's lag closure
instead of Head's; see L10.1 before using it.

The boundary layer alone, on a prescribed edge velocity — this is what the
exact-solution checks run against:

```python
from aerolab.viscous import solve_prescribed, solve_falkner_skan

exact = solve_falkner_skan(0.0)        # Blasius, solved not tabulated
exact.h, exact.h_star, exact.shear     # 2.59110, 1.57259, 0.469600

layer = solve_prescribed(s, ue, reynolds=1e6,
                         theta_initial=..., shape_initial=exact.h)
```

The **uncoupled** solver (Phase 3), kept because it is cheaper and its errors
are separately characterised:

```python
from aerolab.viscous import solve_boundary_layer

bl = solve_boundary_layer(sol, reynolds=3e6, n_crit=9.0)   # or method="michel"
bl.cd_profile                                  # Squire-Young profile drag
bl.upper.transition_x, bl.upper.theta          # per-surface development
bl.upper.laminar_separation_x                  # lambda <= -0.0842
bl.upper.turbulent_separation_x                # H > 2.6
```

`n_crit` is the knob to calibrate against a real tunnel: 9 is free flight,
4–7 a small open-circuit tunnel. It moves the drag by **32%** across that range,
which is far more than any other modelling choice — see `NOTES.md`, L3.3.

## Command line

```bash
aerolab geometry --airfoil naca2412
aerolab polar   --airfoil naca2412 --re 5e5 --alpha -6:16:0.5 --out polar.csv
aerolab polar   --airfoil naca0012 --re 3e6 --alpha 0:5:1 --coupled --out c.csv
aerolab batch   --airfoils naca0012,naca2412,naca4412 --re 2e5,1e6 --out polars/
aerolab report  --airfoil naca2412 --re 5e5 --out report.pdf
aerolab wing    --airfoil naca2412 --re 5e5 --span 6 --taper 0.5 --out wing.csv
aerolab tunnel  --measured run.csv --predicted polar.csv --height 0.3 --chord 0.1
```

Angles are in **degrees** here and in the CSV — that is the boundary where this
package converts. Exit code 2 means the run finished but some points were
flagged, so a script can tell a clean run from one with caveats.

`--mach` applies a Kármán–Tsien (or `--correction prandtl-glauert`) correction
and flags any point whose local Mach exceeds 0.7.

`--coupled` runs the simultaneous Newton solver; without it you get the cheaper
uncoupled boundary layer. Use it above Re ≈ 5×10⁵ and below about 6 degrees.

`--n-crit` is worth calibrating **only above about Re = 5×10⁵**. Below that the
laminar layer separates before the amplification factor reaches N, so transition
is set by the separation bubble and the parameter has no effect at all — see
`NOTES.md`, L7.5.

## Running a tunnel test

`tunnel_test/` holds a complete first experiment: a NACA 0012 model at 100 mm
chord, predicted polars, and a blank measurement sheet to fill in from the
balance.

| File | What it is |
|---|---|
| `naca0012_100mm_cut.svg` | 1:1 outline in millimetres, spar hole included — send straight to a laser cutter |
| `naca0012_build_drawing.png` | dimensioned drawing, installation view, blockage figures, build notes |
| `naca0012_ordinates.txt` | ordinates at the standard NACA stations, in mm |
| `naca0012_model.dat`, `..._mm.csv` | coordinates for the solver and for CAD |
| `prediction_Ncrit9_quiet.csv`, `..._Ncrit5_...csv` | what to test against |
| `measurements_blank.csv` | measurement sheet, angle column filled |

Build it, run it, then:

```bash
aerolab tunnel --measured tunnel_test/measurements.csv \
               --predicted tunnel_test/prediction_Ncrit9_quiet.csv \
               --height 0.3 --chord 0.1
```

That removes the wall corrections and separates **bias** (your angle datum is
off), **rms** (real disagreement) and **scatter** (your repeatability) — three
things with completely different causes that a single error number would hide.

## Test

```bash
pytest -q        # 727 tests, about 4 minutes
```

## Panel-independence study

![convergence](docs/panel_independence.png)

The method is first order — error halves as panels double. Regenerate with:

```python
from aerolab.validation.panel_independence import run_panel_study, plot_panel_study
studies = [run_panel_study(c, 5.0) for c in ("0012", "2412", "4412", "23012")]
plot_panel_study(studies, "docs/panel_independence.png")
```

## Conventions

Angles are in **radians** at every function boundary; degrees appear only in
the CLI, in file formats, and on plot axes. Airfoil coordinates are
non-dimensionalised by chord. Pitching moment is positive nose-up about the
quarter chord. The full table is in [`NOTES.md`](NOTES.md).

## `NOTES.md`

Every modelling assumption and every known limitation is recorded in
[`NOTES.md`](NOTES.md) as it is made. Read it before trusting a number.
