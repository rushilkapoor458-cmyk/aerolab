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

### Versions as built

| Package | Version |
|---|---|
| Python | 3.12.13 |
| NumPy | 2.5.1 |
| SciPy | 1.18.0 |
| Matplotlib | 3.11.1 |
| Typer | 0.27.1 |
| pytest | 9.1.1 |
