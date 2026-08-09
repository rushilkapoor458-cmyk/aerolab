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
| 2 | Inviscid 2D: Hess–Smith panel method | not started |
| 3 | Viscous: integral boundary layer, transition, profile drag | not started |
| 4 | Viscous–inviscid coupling via transpiration | not started |
| 5 | Polars, CLI, PDF reporting, compressibility corrections | not started |
| 6 | Finite wings: vortex lattice | not started |
| 7 | Tunnel corrections and experimental validation | not started |

## Install

Requires [miniforge](https://github.com/conda-forge/miniforge) (or any conda).

```bash
conda env create -f environment.yml
conda activate aerolab
pip install -e ".[dev]"
```

## Use

```bash
aerolab version
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

## Test

```bash
pytest
```

## Conventions

Angles are in **radians** at every function boundary; degrees appear only in
the CLI, in file formats, and on plot axes. Airfoil coordinates are
non-dimensionalised by chord. Pitching moment is positive nose-up about the
quarter chord. The full table is in [`NOTES.md`](NOTES.md).

## `NOTES.md`

Every modelling assumption and every known limitation is recorded in
[`NOTES.md`](NOTES.md) as it is made. Read it before trusting a number.
