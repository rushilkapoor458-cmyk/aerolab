"""Polars: angle-of-attack sweeps, batch runs, and CSV interchange.

A polar is one section at one Reynolds number over a range of incidence. This
module computes them, runs many of them in parallel, and reads and writes them
as CSV so results can leave the package.

Which solver
------------
By default the **uncoupled** Phase 3 solver: inviscid panel method, then
boundary layer on the resulting edge velocity. It converges, its error bounds
are known and written down (transition modelling dominates at about 32%,
everything else under 5%), and it is what can honestly be compared against
tunnel data. The coupled Phase 4 solver is available with ``coupled=True`` and
will refuse to return an unconverged point — which, as of this phase, it does
for every point. See NOTES.md, L4.3.

Cost
----
The panel system is factorised once per polar and every angle reuses it, so a
sweep is dominated by the boundary-layer integration rather than the linear
algebra. Batch runs parallelise across **polars**, not across angles, because a
single polar shares that factorisation and splitting it would throw the saving
away.
"""

from __future__ import annotations

import csv
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from aerolab.compressible.corrections import (
    CorrectionMethod,
    apply_correction,
    critical_mach_number,
)
from aerolab.exceptions import ValidityRangeError
from aerolab.geometry.airfoil import Airfoil
from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem
from aerolab.viscous.boundary_layer import solve_boundary_layer
from aerolab.viscous.transition import DEFAULT_N_CRIT, TransitionMethod

FloatArray = NDArray[np.float64]

__all__ = [
    "PolarPoint",
    "Polar",
    "PolarRequest",
    "compute_polar",
    "batch_polars",
    "parse_alpha_range",
    "load_airfoil",
]

#: Panel count used unless told otherwise. 400 panels puts the inviscid lift
#: within 0.3% of its converged value and the D'Alembert residual near 1e-4;
#: see NOTES.md, L2.3.
DEFAULT_PANELS = 401


@dataclass(frozen=True)
class PolarPoint:
    """One angle of attack.

    Attributes
    ----------
    alpha : float
        Angle of attack in **radians**.
    cl, cd, cm : float
        Lift, profile drag and quarter-chord pitching moment. ``cm`` is positive
        nose-up. ``cd`` is NaN if the boundary layer could not be solved.
    cd_inviscid : float
        Residual pressure drag from the inviscid solve. Zero in exact potential
        flow, so a numerical error measure rather than a drag.
    transition_upper, transition_lower : float
        Transition stations ``x/c``, NaN if the surface stayed laminar.
    separation_upper, separation_lower : float
        Turbulent separation stations ``x/c``, NaN if attached to the trailing
        edge.
    cp_min : float
        Most negative pressure coefficient, which sets the critical Mach number.
    max_local_mach : float
        Peak local Mach number after the compressibility correction.
    converged : bool
        Whether every stage of this point succeeded.
    note : str
        Empty when fine; otherwise why the point is suspect.
    """

    alpha: float
    cl: float
    cd: float
    cm: float
    cd_inviscid: float
    transition_upper: float
    transition_lower: float
    separation_upper: float
    separation_lower: float
    cp_min: float
    max_local_mach: float
    converged: bool
    note: str = ""

    @property
    def alpha_deg(self) -> float:
        """Angle of attack in degrees, for reporting."""
        return float(np.rad2deg(self.alpha))

    @property
    def lift_to_drag(self) -> float:
        """Lift-to-drag ratio, NaN where the drag is unavailable."""
        if not np.isfinite(self.cd) or self.cd <= 0.0:
            return float("nan")
        return self.cl / self.cd


#: Column order for CSV interchange. Angles are written in **degrees**, which is
#: the boundary at which this package converts.
CSV_COLUMNS = (
    "alpha_deg",
    "cl",
    "cd",
    "cm",
    "cd_inviscid",
    "transition_upper",
    "transition_lower",
    "separation_upper",
    "separation_lower",
    "cp_min",
    "max_local_mach",
    "converged",
    "note",
)


@dataclass(frozen=True)
class Polar:
    """A sweep of one section at one condition.

    Attributes
    ----------
    name : str
        Section name.
    reynolds : float
        Chord Reynolds number.
    mach : float
        Freestream Mach number.
    n_crit : float
        Amplification factor used for transition.
    method : str
        Transition criterion.
    correction : str
        Compressibility correction applied.
    coupled : bool
        Whether the viscous-inviscid coupling was used.
    points : tuple of PolarPoint
        One per angle, in the order computed.
    """

    name: str
    reynolds: float
    mach: float
    n_crit: float
    method: str
    correction: str
    coupled: bool
    points: tuple[PolarPoint, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.points)

    def __repr__(self) -> str:
        good = sum(1 for p in self.points if p.converged)
        return (
            f"<Polar {self.name!r} Re={self.reynolds:.3g} M={self.mach:.2f}: "
            f"{len(self.points)} points, {good} converged>"
        )

    def _column(self, name: str) -> FloatArray:
        return np.array([getattr(p, name) for p in self.points], dtype=np.float64)

    @cached_property
    def alpha(self) -> FloatArray:
        """Angles of attack in **radians**."""
        return self._column("alpha")

    @cached_property
    def alpha_deg(self) -> FloatArray:
        """Angles of attack in degrees."""
        return np.rad2deg(self.alpha)

    @cached_property
    def cl(self) -> FloatArray:
        """Lift coefficients."""
        return self._column("cl")

    @cached_property
    def cd(self) -> FloatArray:
        """Profile drag coefficients."""
        return self._column("cd")

    @cached_property
    def cm(self) -> FloatArray:
        """Quarter-chord pitching moments, positive nose-up."""
        return self._column("cm")

    @cached_property
    def converged(self) -> NDArray[np.bool_]:
        """Whether each point succeeded."""
        return np.array([p.converged for p in self.points], dtype=bool)

    @cached_property
    def lift_slope(self) -> float:
        """Lift-curve slope per **radian**, fitted over the linear range.

        Fitted between -4 and 4 degrees, where every section in scope is linear.
        Restricting the fit matters: including stalled points would drag the
        slope down and quietly misreport a healthy section.
        """
        usable = self.converged & (np.abs(self.alpha_deg) <= 4.0)
        if int(np.count_nonzero(usable)) < 3:
            return float("nan")
        return float(np.polyfit(self.alpha[usable], self.cl[usable], 1)[0])

    @cached_property
    def zero_lift_angle(self) -> float:
        """Zero-lift angle in **radians**, from the same linear fit."""
        usable = self.converged & (np.abs(self.alpha_deg) <= 4.0)
        if int(np.count_nonzero(usable)) < 3:
            return float("nan")
        slope, intercept = np.polyfit(self.alpha[usable], self.cl[usable], 1)
        return float(-intercept / slope)

    @cached_property
    def cl_max(self) -> float:
        """Highest lift coefficient among converged points."""
        usable = self.converged
        return float(np.max(self.cl[usable])) if usable.any() else float("nan")

    @cached_property
    def cd_min(self) -> float:
        """Lowest profile drag among converged points."""
        usable = self.converged & np.isfinite(self.cd)
        return float(np.min(self.cd[usable])) if usable.any() else float("nan")

    @cached_property
    def best_lift_to_drag(self) -> tuple[float, float]:
        """Best ``Cl/Cd`` and the angle in **radians** where it occurs."""
        usable = self.converged & np.isfinite(self.cd) & (self.cd > 0.0)
        if not usable.any():
            return float("nan"), float("nan")
        ratio = np.where(usable, self.cl / np.where(usable, self.cd, 1.0), -np.inf)
        best = int(np.argmax(ratio))
        return float(ratio[best]), float(self.alpha[best])

    @cached_property
    def critical_mach(self) -> float:
        """Critical Mach number at the most heavily loaded converged point."""
        suctions = self._column("cp_min")[self.converged]
        if suctions.size == 0:
            return float("nan")
        try:
            return critical_mach_number(float(np.min(suctions)))
        except ValidityRangeError:
            return float("nan")

    @property
    def warnings(self) -> list[str]:
        """Notes attached to individual points, for surfacing to a user."""
        return [
            f"alpha = {p.alpha_deg:+.2f} deg: {p.note}"
            for p in self.points
            if p.note
        ]

    # ------------------------------------------------------------ interchange

    def to_csv(self, path: str | Path) -> Path:
        """Write the polar as CSV, with the run conditions as comment lines.

        Parameters
        ----------
        path : str or Path
            Destination.

        Returns
        -------
        Path
            The file written.

        Notes
        -----
        Angles are written in **degrees**. The header comments are prefixed with
        ``#`` and carry the conditions, so a polar file is self-describing and
        can be reloaded without being told what it was.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as handle:
            handle.write(f"# aerolab polar\n")
            handle.write(f"# name = {self.name}\n")
            handle.write(f"# reynolds = {self.reynolds:.6g}\n")
            handle.write(f"# mach = {self.mach:.6g}\n")
            handle.write(f"# n_crit = {self.n_crit:.6g}\n")
            handle.write(f"# method = {self.method}\n")
            handle.write(f"# correction = {self.correction}\n")
            handle.write(f"# coupled = {self.coupled}\n")
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            for point in self.points:
                writer.writerow(
                    [
                        f"{point.alpha_deg:.6f}",
                        f"{point.cl:.6f}",
                        f"{point.cd:.7f}",
                        f"{point.cm:.6f}",
                        f"{point.cd_inviscid:.3e}",
                        f"{point.transition_upper:.5f}",
                        f"{point.transition_lower:.5f}",
                        f"{point.separation_upper:.5f}",
                        f"{point.separation_lower:.5f}",
                        f"{point.cp_min:.5f}",
                        f"{point.max_local_mach:.5f}",
                        int(point.converged),
                        point.note,
                    ]
                )
        return out

    @classmethod
    def from_csv(cls, path: str | Path) -> "Polar":
        """Read a polar written by :meth:`to_csv`.

        Parameters
        ----------
        path : str or Path
            File to read.

        Returns
        -------
        Polar
        """
        source = Path(path)
        meta: dict[str, str] = {}
        rows: list[dict[str, str]] = []
        with source.open(newline="", encoding="utf-8") as handle:
            data_lines = []
            for line in handle:
                if line.startswith("#"):
                    if "=" in line:
                        key, _, value = line[1:].partition("=")
                        meta[key.strip()] = value.strip()
                else:
                    data_lines.append(line)
            rows = list(csv.DictReader(data_lines))

        points = tuple(
            PolarPoint(
                alpha=float(np.deg2rad(float(row["alpha_deg"]))),
                cl=float(row["cl"]),
                cd=float(row["cd"]),
                cm=float(row["cm"]),
                cd_inviscid=float(row["cd_inviscid"]),
                transition_upper=float(row["transition_upper"]),
                transition_lower=float(row["transition_lower"]),
                separation_upper=float(row["separation_upper"]),
                separation_lower=float(row["separation_lower"]),
                cp_min=float(row["cp_min"]),
                max_local_mach=float(row["max_local_mach"]),
                converged=bool(int(row["converged"])),
                note=row.get("note", "") or "",
            )
            for row in rows
        )
        return cls(
            name=meta.get("name", source.stem),
            reynolds=float(meta.get("reynolds", "nan")),
            mach=float(meta.get("mach", "0")),
            n_crit=float(meta.get("n_crit", "9")),
            method=meta.get("method", "en"),
            correction=meta.get("correction", "none"),
            coupled=meta.get("coupled", "False") == "True",
            points=points,
        )


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def parse_alpha_range(spec: str) -> FloatArray:
    """Parse a ``start:stop:step`` angle specification, in **degrees**.

    Parameters
    ----------
    spec : str
        ``"-6:16:0.5"`` for -6 to 16 degrees in half-degree steps. A bare number
        gives a single angle; ``"a,b,c"`` gives an explicit list.

    Returns
    -------
    ndarray
        Angles in degrees, inclusive of the stop value where it lands on a step.

    Raises
    ------
    ValidityRangeError
        If the specification cannot be read, or the step is zero or points the
        wrong way.

    Notes
    -----
    Splitting on ``":"`` handles negative starts without special-casing, since
    the minus sign never appears as a separator. The stop value is included when
    it falls on a step, because ``-6:16:0.5`` reads as "up to and including 16"
    to anyone writing a test matrix.
    """
    text = spec.strip()
    if not text:
        raise ValidityRangeError("empty angle specification")

    if "," in text:
        try:
            return np.array([float(part) for part in text.split(",")])
        except ValueError as error:
            raise ValidityRangeError(
                f"could not read the angle list {spec!r}: {error}"
            ) from error

    parts = text.split(":")
    try:
        values = [float(part) for part in parts]
    except ValueError as error:
        raise ValidityRangeError(
            f"could not read the angle specification {spec!r}; expected "
            "start:stop:step, a comma-separated list, or a single number"
        ) from error

    if len(values) == 1:
        return np.array(values)
    if len(values) != 3:
        raise ValidityRangeError(
            f"expected start:stop:step, got {len(values)} parts in {spec!r}"
        )

    start, stop, step = values
    if step == 0.0:
        raise ValidityRangeError("angle step cannot be zero")
    if (stop - start) * step < 0.0:
        raise ValidityRangeError(
            f"the step {step} points away from the stop value in {spec!r}"
        )
    count = int(np.floor(abs(stop - start) / abs(step) + 1e-9)) + 1
    return start + step * np.arange(count)


def load_airfoil(specification: str, n_points: int = DEFAULT_PANELS) -> Airfoil:
    """Resolve an airfoil from a NACA designation or a ``.dat`` file path.

    Parameters
    ----------
    specification : str
        ``"naca2412"``, ``"2412"``, or a path to a coordinate file.
    n_points : int, optional
        Points to generate, for NACA sections. Imported files are repanelled to
        this count so that a polar's resolution does not depend on how finely
        whoever published the coordinates chose to sample them.

    Returns
    -------
    Airfoil
    """
    candidate = Path(specification)
    if candidate.exists():
        from aerolab.geometry.dat_io import read_dat
        from aerolab.geometry.repanel import repanel

        return repanel(read_dat(candidate).airfoil, n_points)
    return naca(specification, n_points)


def compute_polar(
    airfoil: Airfoil,
    alphas_deg: FloatArray,
    reynolds: float,
    *,
    mach: float = 0.0,
    n_crit: float = DEFAULT_N_CRIT,
    method: TransitionMethod = "en",
    correction: CorrectionMethod = "karman-tsien",
    coupled: bool = False,
    name: str | None = None,
) -> Polar:
    """Sweep angle of attack for one section at one condition.

    Parameters
    ----------
    airfoil : Airfoil
        Section to sweep.
    alphas_deg : ndarray
        Angles of attack in **degrees** — this is a reporting-level entry point
        and degrees are what a test matrix is written in. Converted immediately.
    reynolds : float
        Chord Reynolds number.
    mach : float, optional
        Freestream Mach number for the compressibility correction. Zero leaves
        pressures uncorrected.
    n_crit : float, optional
        Amplification factor at transition.
    method : {"en", "michel"}, optional
        Transition criterion.
    correction : {"karman-tsien", "prandtl-glauert", "none"}, optional
        Compressibility correction.
    coupled : bool, optional
        Use the Phase 4 viscous-inviscid coupling. It does not currently
        converge and every point will be marked unconverged; see NOTES.md, L4.3.
    name : str, optional
        Label; defaults to the airfoil's own name.

    Returns
    -------
    Polar

    Notes
    -----
    A point that fails is **recorded as failed**, with the reason in its note,
    rather than dropped. A polar with a hole in it is far easier to interpret
    than one that silently stops at the angle where the physics got hard.
    """
    if reynolds <= 0.0:
        raise ValidityRangeError(f"Reynolds number must be positive, got {reynolds}")

    system = HessSmithSystem(airfoil)
    points: list[PolarPoint] = []

    for alpha_deg in np.atleast_1d(np.asarray(alphas_deg, dtype=np.float64)):
        alpha = float(np.deg2rad(alpha_deg))
        points.append(
            _solve_point(
                system, airfoil, alpha, reynolds, mach, n_crit, method,
                correction, coupled,
            )
        )

    return Polar(
        name=name or airfoil.name,
        reynolds=float(reynolds),
        mach=float(mach),
        n_crit=float(n_crit),
        method=method,
        correction=correction,
        coupled=coupled,
        points=tuple(points),
    )


def _solve_point(
    system: HessSmithSystem,
    airfoil: Airfoil,
    alpha: float,
    reynolds: float,
    mach: float,
    n_crit: float,
    method: TransitionMethod,
    correction: CorrectionMethod,
    coupled: bool,
) -> PolarPoint:
    """Solve one angle, converting any failure into a recorded, flagged point."""
    nan = float("nan")
    try:
        if coupled:
            # The simultaneous Newton solver (Phase 8), not the sequential
            # coupling of Phase 4, which never converged. Both are still in the
            # package; only this one is offered here.
            from aerolab.viscous.newton import solve_newton

            result = solve_newton(
                airfoil, alpha, reynolds, n_crit=n_crit,
                system=system, validate=False,
            )
            panel = result.panel
            note = "" if result.converged else (
                f"the Newton solve did not converge, residual "
                f"{result.residual:.2e}"
            )
            converged = result.converged
            if converged and not result.closure_in_range:
                note = (
                    f"shape factor reached {result.max_shape_factor:.2f}, "
                    "outside the range Head's correlation was fitted over"
                )
            coupled_drag = result.cd
            coupled_transition = result.transition_x
            layer = None
        else:
            coupled_drag = None
            coupled_transition = None
            panel = system.solve(alpha, validate=False)
            layer = solve_boundary_layer(
                panel, reynolds, method=method, n_crit=n_crit, validate=False
            )
            note = ""
            converged = True

        field = apply_correction(panel.cp, mach, method=correction)
        if field.warning:
            note = f"{note}; {field.warning}" if note else field.warning
            converged = False

        drag = layer.cd_profile if coupled_drag is None else coupled_drag
        if layer is not None and layer.separation_is_significant():
            station = min(
                s.turbulent_separation_x
                for s in layer.surfaces
                if s.turbulent_separation_x is not None
            )
            extra = (
                f"separated at x/c = {station:.3f}, so the drag is a lower bound"
            )
            note = f"{note}; {extra}" if note else extra
            converged = False

        if layer is None:
            transition_upper, transition_lower = coupled_transition
            separation_upper = separation_lower = nan
        else:
            upper, lower = layer.surfaces
            transition_upper = upper.transition_x if upper.transition_x else nan
            transition_lower = lower.transition_x if lower.transition_x else nan
            separation_upper = (
                upper.turbulent_separation_x
                if upper.turbulent_separation_x is not None
                else nan
            )
            separation_lower = (
                lower.turbulent_separation_x
                if lower.turbulent_separation_x is not None
                else nan
            )
        return PolarPoint(
            alpha=alpha,
            cl=panel.cl_pressure,
            cd=drag,
            cm=panel.cm_quarter_chord,
            cd_inviscid=panel.cd_pressure,
            transition_upper=transition_upper,
            transition_lower=transition_lower,
            separation_upper=separation_upper,
            separation_lower=separation_lower,
            cp_min=float(np.min(field.cp)),
            max_local_mach=field.max_local_mach,
            converged=converged,
            note=note,
        )
    except Exception as error:  # noqa: BLE001 - a failed angle must not kill a sweep
        return PolarPoint(
            alpha=alpha, cl=nan, cd=nan, cm=nan, cd_inviscid=nan,
            transition_upper=nan, transition_lower=nan,
            separation_upper=nan, separation_lower=nan,
            cp_min=nan, max_local_mach=nan,
            converged=False,
            note=f"{type(error).__name__}: {error}",
        )


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolarRequest:
    """One polar to compute, in a form that survives being sent to a subprocess.

    Attributes
    ----------
    airfoil : str
        NACA designation or path to a coordinate file.
    reynolds : float
        Chord Reynolds number.
    alphas_deg : tuple of float
        Angles in degrees.
    mach, n_crit : float
        Condition and transition parameter.
    method, correction : str
        Transition criterion and compressibility correction.
    coupled : bool
        Whether to use the Phase 4 coupling.
    n_points : int
        Panel resolution.
    """

    airfoil: str
    reynolds: float
    alphas_deg: tuple[float, ...]
    mach: float = 0.0
    n_crit: float = DEFAULT_N_CRIT
    method: TransitionMethod = "en"
    correction: CorrectionMethod = "karman-tsien"
    coupled: bool = False
    n_points: int = DEFAULT_PANELS

    @property
    def label(self) -> str:
        """Short identifier, suitable as a filename stem."""
        stem = Path(self.airfoil).stem if "/" in self.airfoil else self.airfoil
        return f"{stem}_Re{self.reynolds:.0e}_M{self.mach:g}".replace("+", "")


def run_request(request: PolarRequest) -> Polar:
    """Compute one :class:`PolarRequest`.

    Defined at module level, and taking a single picklable argument, so that it
    can be dispatched to a process pool. Both constraints are why the request is
    a dataclass of plain values rather than a prepared :class:`Airfoil`.
    """
    airfoil = load_airfoil(request.airfoil, request.n_points)
    return compute_polar(
        airfoil,
        np.array(request.alphas_deg),
        request.reynolds,
        mach=request.mach,
        n_crit=request.n_crit,
        method=request.method,
        correction=request.correction,
        coupled=request.coupled,
        name=airfoil.name,
    )


def batch_polars(
    requests: list[PolarRequest], *, workers: int | None = None
) -> list[Polar]:
    """Compute many polars in parallel.

    Parameters
    ----------
    requests : list of PolarRequest
        Cases to run.
    workers : int, optional
        Process count. Defaults to the number of CPUs, capped at the number of
        requests. Pass 1 to run in-process, which is what the tests do — a
        process pool inside a test runner is a good way to hang a suite.

    Returns
    -------
    list of Polar
        In the same order as ``requests``.

    Notes
    -----
    Parallelism is across **polars**, not across angles. A single polar shares
    one factorised panel system between all its angles, and splitting it would
    throw that saving away to buy back less than it cost.
    """
    if not requests:
        return []

    count = workers if workers is not None else min(
        len(requests), os.cpu_count() or 1
    )
    if count <= 1:
        return [run_request(request) for request in requests]

    with ProcessPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run_request, requests))


# ---------------------------------------------------------------------------
# Finite wings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WingPolarPoint:
    """One angle of attack on a finite wing.

    Attributes
    ----------
    alpha : float
        Angle of attack in **radians**.
    cl : float
        Wing lift coefficient on planform area.
    cdi : float
        Induced drag, from the Trefftz plane.
    cd_profile : float
        Profile drag, from strip theory: the section drag at each strip's own
        local lift coefficient, weighted by chord.
    span_efficiency : float
        ``e`` for the loading at this angle.
    strips_outside_polar : int
        Strips whose local lift fell outside the range covered by the section
        polar, and were therefore clamped to its ends.
    """

    alpha: float
    cl: float
    cdi: float
    cd_profile: float
    span_efficiency: float
    strips_outside_polar: int

    @property
    def cd(self) -> float:
        """Total drag: induced plus profile."""
        return self.cdi + self.cd_profile

    @property
    def alpha_deg(self) -> float:
        """Angle of attack in degrees."""
        return float(np.rad2deg(self.alpha))

    @property
    def lift_to_drag(self) -> float:
        """Wing lift-to-drag ratio."""
        return self.cl / self.cd if self.cd > 0.0 else float("nan")


def wing_polar(
    wing,
    alphas_deg: FloatArray,
    section_polar: Polar,
    *,
    n_span: int = 40,
    n_chord: int = 4,
) -> list[WingPolarPoint]:
    """Sweep a finite wing, combining induced and profile drag.

    Parameters
    ----------
    wing : Wing
        Planform.
    alphas_deg : ndarray
        Angles of attack in **degrees**.
    section_polar : Polar
        Two-dimensional polar of the wing's section, at the appropriate
        Reynolds number. Only its converged points are used.
    n_span, n_chord : int, optional
        Lattice resolution.

    Returns
    -------
    list of WingPolarPoint

    Notes
    -----
    Strip theory assumes each spanwise strip behaves as a two-dimensional
    section at its own local lift coefficient. That is a good approximation
    where the loading varies slowly along the span and a poor one near the tips,
    where the flow is strongly three-dimensional — so the tip strips contribute
    the least reliable part of the profile drag. They also carry the least
    chord, which limits the damage.

    Strips whose local lift falls outside the section polar are **clamped to its
    ends and counted**, not extrapolated. The count is reported on every point
    so that a wing whose tips are working outside the available data cannot be
    mistaken for one that is not.
    """
    from aerolab.inviscid.vlm import solve_vlm

    usable = section_polar.converged & np.isfinite(section_polar.cd)
    if int(np.count_nonzero(usable)) < 2:
        raise ValidityRangeError(
            "the section polar has fewer than two converged points, so strip "
            "theory has nothing to interpolate"
        )
    section_cl = section_polar.cl[usable]
    section_cd = section_polar.cd[usable]
    order = np.argsort(section_cl)
    section_cl, section_cd = section_cl[order], section_cd[order]

    points: list[WingPolarPoint] = []
    for alpha_deg in np.atleast_1d(np.asarray(alphas_deg, dtype=np.float64)):
        result = solve_vlm(
            wing, float(np.deg2rad(alpha_deg)), n_span=n_span, n_chord=n_chord
        )
        outside = int(
            np.count_nonzero(
                (result.section_cl < section_cl[0])
                | (result.section_cl > section_cl[-1])
            )
        )
        strip_cd = np.interp(result.section_cl, section_cl, section_cd)
        edges = wing._span_edges(n_span)
        width = np.diff(edges)
        profile = float(np.sum(strip_cd * result.chord * width) / wing.area)

        points.append(
            WingPolarPoint(
                alpha=float(np.deg2rad(alpha_deg)),
                cl=result.cl,
                cdi=result.cdi,
                cd_profile=profile,
                span_efficiency=result.span_efficiency,
                strips_outside_polar=outside,
            )
        )
    return points
