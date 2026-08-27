"""The wake: geometry, boundary layer, and displacement sources.

Why a wake is not optional
--------------------------
Potential flow puts a stagnation point at a sharp trailing edge, so ``Ue -> 0``
and ``dUe/ds`` diverges there. A boundary layer marched into that responds with
``d(delta*)/ds`` of order 1 — a free shear layer spreads at 0.1 to 0.2 — and the
transpiration velocity it implies reaches 60% of freestream, concentrated in the
last 2% of chord. Fed back into the outer flow, that destroys the solution.

The cure is to let the boundary layer leave the airfoil. Downstream of the
trailing edge the two surface layers merge into a wake which carries its own
displacement thickness, and representing that displacement with source panels
along the wake line moves the rear stagnation point **off the body**. The
trailing-edge velocity is then finite, ``dUe/ds`` is bounded, and the coupled
fixed point becomes attracting.

Model
-----
Geometry
    A straight line from the trailing-edge midpoint along the freestream
    direction, panelled with geometric stretching so the panels are finest where
    the displacement gradient is largest. A real wake curves; this one does not,
    and the error that introduces is second order in the wake deflection because
    the sources are weak and their influence on the airfoil falls off with
    distance. See NOTES.md, A4.6.

Initial conditions
    Momentum thickness adds: ``theta_w = theta_upper + theta_lower``. Displacement
    thickness adds too, plus the trailing-edge gap, which is real displaced area:
    ``delta*_w = delta*_upper + delta*_lower + h_te``.

Marching
    The momentum integral with **no wall shear**, since a wake has no wall:

    .. math:: \\frac{d\\theta}{ds} = -(H + 2)\\frac{\\theta}{U_e}\\frac{dU_e}{ds}

    closed by Head's entrainment equation, also with ``cf = 0``. In a constant-
    pressure wake this correctly conserves momentum thickness while the shape
    factor relaxes towards 1, which is what a wake does.

Conventions
-----------
``s`` runs downstream from the trailing edge, in chords. ``Ue`` is
non-dimensionalised by freestream speed. Angles are in radians.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp
from scipy.interpolate import CubicSpline

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.airfoil import Airfoil
from aerolab.inviscid.influence import panel_frames, panel_influence
from aerolab.viscous import closure

FloatArray = NDArray[np.float64]

__all__ = [
    "Wake",
    "WakeBoundaryLayer",
    "build_wake",
    "solve_wake_layer",
    "wake_source_strengths",
]

#: Default wake length in chords.
#:
#: The wake's influence on the airfoil falls off with distance, so a long wake
#: buys nothing. One chord captures the near field that matters; doubling it
#: moves the lift by under 0.1%, which is checked in the tests.
DEFAULT_WAKE_LENGTH = 1.0

#: Default number of wake panels.
DEFAULT_WAKE_PANELS = 40

#: Geometric stretching ratio along the wake.
#:
#: Uniform by default, deliberately. Clustering panels against the trailing edge
#: is the obvious thing to do and it is wrong here: the merged layer relaxes its
#: shape factor over a few thousandths of a chord, faster than an integral
#: method can honestly represent, and a first panel of 0.0006c chases that
#: relaxation into source strengths of order 1 that oscillate between stations.
#: A first panel near 0.02c gives a smooth sheet of strength 0.35 and a
#: converging iteration. The sensitivity to this choice is measured in the
#: tests. See NOTES.md, A4.7.
DEFAULT_WAKE_GROWTH = 1.0

#: Shape factor floor in the wake.
#:
#: A wake relaxes towards H = 1 but never reaches it. The floor keeps the
#: entrainment closure inside the range its correlations were fitted over.
WAKE_MIN_SHAPE_FACTOR = 1.05


@dataclass(frozen=True)
class Wake:
    """Panelled wake line trailing the airfoil.

    Attributes
    ----------
    starts, ends : ndarray
        ``(n, 2)`` panel endpoints, in chords.
    control_points : ndarray
        ``(n, 2)`` panel midpoints.
    tangents, normals : ndarray
        ``(n, 2)`` unit vectors. The normal is the tangent rotated by -90
        degrees, matching the airfoil convention.
    lengths : ndarray
        ``(n,)`` panel lengths, in chords.
    s : ndarray
        ``(n,)`` arc length of each control point from the trailing edge.
    """

    starts: FloatArray
    ends: FloatArray
    control_points: FloatArray
    tangents: FloatArray
    normals: FloatArray
    lengths: FloatArray
    s: FloatArray

    @property
    def n_panels(self) -> int:
        """Number of wake panels."""
        return int(self.starts.shape[0])

    @property
    def total_length(self) -> float:
        """Wake length, in chords."""
        return float(np.sum(self.lengths))


@dataclass(frozen=True)
class WakeBoundaryLayer:
    """Boundary-layer development along the wake.

    Attributes
    ----------
    s : ndarray
        Arc length from the trailing edge, in chords.
    ue : ndarray
        Edge velocity, non-dimensionalised by freestream speed.
    theta, delta_star : ndarray
        Momentum and displacement thickness, in chords.
    shape_factor : ndarray
        ``H = delta*/theta``.
    """

    s: FloatArray
    ue: FloatArray
    theta: FloatArray
    delta_star: FloatArray
    shape_factor: FloatArray


def build_wake(
    airfoil: Airfoil,
    alpha: float,
    *,
    length: float = DEFAULT_WAKE_LENGTH,
    n_panels: int = DEFAULT_WAKE_PANELS,
    growth: float = DEFAULT_WAKE_GROWTH,
) -> Wake:
    """Panel a straight wake trailing the airfoil.

    Parameters
    ----------
    airfoil : Airfoil
        Section the wake trails from.
    alpha : float
        Angle of attack in **radians**, setting the wake direction.
    length : float, optional
        Wake length in chords.
    n_panels : int, optional
        Number of panels.
    growth : float, optional
        Geometric stretching ratio, greater than or equal to 1.

    Returns
    -------
    Wake

    Raises
    ------
    ValidityRangeError
        If the length, panel count or growth ratio is unusable.

    Notes
    -----
    The wake leaves along the freestream direction rather than along the
    trailing-edge bisector. At small incidence the two differ by a degree or
    two, and the wake sources are weak enough that the difference is second
    order; at high incidence a real wake curves anyway, which a straight line
    cannot represent either way.
    """
    if length <= 0.0:
        raise ValidityRangeError(f"wake length must be positive, got {length}")
    if n_panels < 4:
        raise ValidityRangeError(f"need at least 4 wake panels, got {n_panels}")
    if growth < 1.0:
        raise ValidityRangeError(f"growth ratio must be at least 1, got {growth}")

    if np.isclose(growth, 1.0):
        edges = np.linspace(0.0, length, n_panels + 1)
    else:
        steps = growth ** np.arange(n_panels)
        edges = np.concatenate([[0.0], np.cumsum(steps)])
        edges *= length / edges[-1]

    direction = np.array([np.cos(alpha), np.sin(alpha)])
    origin = airfoil.te_point
    points = origin[None, :] + edges[:, None] * direction[None, :]

    starts, ends = points[:-1], points[1:]
    lengths, tangents, local_normals = panel_frames(starts, ends)
    return Wake(
        starts=starts,
        ends=ends,
        control_points=0.5 * (starts + ends),
        tangents=tangents,
        normals=-local_normals,
        lengths=lengths,
        s=0.5 * (edges[:-1] + edges[1:]),
    )


def solve_wake_layer(
    s: FloatArray,
    ue: FloatArray,
    theta_start: float,
    delta_star_start: float,
    reynolds: float,
) -> WakeBoundaryLayer:
    """March the wake boundary layer downstream from the trailing edge.

    Parameters
    ----------
    s : ndarray
        Stations from the trailing edge, in chords, increasing.
    ue : ndarray
        Edge velocity at those stations.
    theta_start, delta_star_start : float
        Momentum and displacement thickness leaving the trailing edge, in
        chords. Both are the sum over the two surfaces; the displacement also
        includes the trailing-edge gap.
    reynolds : float
        Reynolds number based on chord.

    Returns
    -------
    WakeBoundaryLayer

    Raises
    ------
    ConvergenceError
        If the march fails to integrate.

    Notes
    -----
    Momentum integral with ``cf = 0``, closed by Head's entrainment. In a
    constant-pressure wake ``dUe/ds`` vanishes, so ``theta`` is conserved
    exactly — momentum is not created or destroyed in a wake — while entrainment
    drives ``H`` down towards 1. Both are asserted in the tests.
    """
    if theta_start <= 0.0:
        raise ValidityRangeError(
            f"wake momentum thickness must be positive, got {theta_start}"
        )
    shape_start = float(
        np.clip(delta_star_start / theta_start, WAKE_MIN_SHAPE_FACTOR, 2.95)
    )

    ue_spline = CubicSpline(s, np.maximum(ue, 1e-6))
    due_ds_spline = ue_spline.derivative()
    h1_start = float(closure.head_h1_from_h(np.array([shape_start]))[0])

    def derivatives(station: float, state: FloatArray) -> FloatArray:
        theta = max(state[0], 1e-12)
        h1 = max(state[1], 3.3 + 1e-9)
        shape = float(
            np.clip(closure.head_h_from_h1(np.array([h1]))[0], WAKE_MIN_SHAPE_FACTOR, 2.95)
        )
        edge = max(float(ue_spline(station)), 1e-6)
        # No wall in a wake, so no wall shear: the cf/2 term is absent.
        dtheta = -(shape + 2.0) * theta / edge * float(due_ds_spline(station))
        entrainment = float(closure.head_entrainment(np.array([h1]))[0])
        return np.array([dtheta, (entrainment - h1 * dtheta) / theta])

    result = solve_ivp(
        derivatives,
        (float(s[0]), float(s[-1])),
        np.array([theta_start, h1_start]),
        method="RK45",
        dense_output=True,
        rtol=1e-8,
        atol=1e-12,
        max_step=float(s[-1] - s[0]) / 20.0,
    )
    if not result.success:
        raise ConvergenceError(
            f"the wake boundary layer failed to integrate: {result.message}",
            iterations=int(result.nfev),
            residual=float("nan"),
            tolerance=1e-8,
        )

    state = result.sol(s)
    theta = np.maximum(state[0], 1e-12)
    h1 = np.maximum(state[1], 3.3 + 1e-9)
    shape = np.clip(closure.head_h_from_h1(h1), WAKE_MIN_SHAPE_FACTOR, 2.95)
    return WakeBoundaryLayer(
        s=s,
        ue=ue,
        theta=theta,
        delta_star=shape * theta,
        shape_factor=shape,
    )


def wake_source_strengths(layer: WakeBoundaryLayer) -> FloatArray:
    """Source strength on each wake panel, from the displacement gradient.

    Parameters
    ----------
    layer : WakeBoundaryLayer
        Converged wake layer.

    Returns
    -------
    ndarray
        ``d(Ue delta*)/ds`` at each station, the strength per unit length of the
        wake source sheet.
    """
    flux = layer.ue * layer.delta_star
    return CubicSpline(layer.s, flux).derivative()(layer.s)


def wake_influence(
    wake: Wake, strengths: FloatArray, points: FloatArray
) -> FloatArray:
    """Velocity induced at ``points`` by the wake source sheet.

    Parameters
    ----------
    wake : Wake
        Panelled wake.
    strengths : ndarray
        ``(n_panels,)`` source strength per unit length.
    points : ndarray
        ``(p, 2)`` field points, in chords.

    Returns
    -------
    ndarray
        ``(p, 2)`` induced velocity.

    Notes
    -----
    Wake sources are **prescribed**, not solved for: their strengths come from
    the wake boundary layer. So this is an explicit evaluation, and its result
    enters the airfoil system as a right-hand-side contribution.
    """
    source, _ = panel_influence(wake.starts, wake.ends, np.atleast_2d(points))
    return np.einsum("pmk,m->pk", source, strengths)


def wake_self_tangential(wake: Wake, strengths: FloatArray) -> FloatArray:
    """Tangential velocity the wake induces at its own control points.

    A source panel induces no tangential velocity at its own midpoint — the
    self-influence is purely normal — so the diagonal is simply zeroed rather
    than replaced. The normal component jumps across the sheet and is not
    wanted here.
    """
    source, _ = panel_influence(wake.starts, wake.ends, wake.control_points)
    diagonal = np.arange(wake.n_panels)
    source[diagonal, diagonal, :] = 0.0
    induced = np.einsum("pmk,m->pk", source, strengths)
    return np.sum(induced * wake.tangents, axis=1)
