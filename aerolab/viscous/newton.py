"""Simultaneous viscous-inviscid solution by Newton's method.

This replaces the sequential coupling of :mod:`aerolab.viscous.coupling`, which
could not be made to converge for a reason that turned out to be structural
rather than incidental. Both facts matter, so both are recorded here.

Why the sequential method failed
--------------------------------
Sequential coupling treats the problem as a fixed-point iteration: the inviscid
solver produces ``Ue``, the boundary layer consumes it and produces a
displacement effect, and the displacement effect changes ``Ue``. Written as a
map ``m -> M(m)`` on the mass defect, convergence requires the spectral radius
of ``dM/dm`` to be below one. Measured on a NACA 0012 at 6 degrees it is
**15.5**, with 98.6% of the dominant eigenvector in the last 2% of the chord.

Under-relaxation cannot fix that. Relaxing by ``omega`` replaces the
amplification factor with ``|1 + omega(rho - 1)|``, and for a positive real
eigenvalue greater than one that exceeds unity for **every** ``omega > 0``. It
is a theorem, not a tuning problem, and the measured residuals at
``omega = 0.20, 0.10, 0.05, 0.02`` — 1.03, 0.64, 0.95, 1.97 — follow it.

There is a second, independent obstacle. Solving the boundary layer for a
*prescribed* edge velocity is singular at separation: the Goldstein singularity
is a property of the direct problem, and it would remain even if the iteration
were stable.

What this module does instead
-----------------------------
Both obstacles come from the same choice — treating ``Ue`` as an input to the
boundary layer. Here ``Ue`` is an **unknown**, solved simultaneously with the
momentum and shape-parameter equations. Three unknowns per station,

.. math:: \\left(\\theta_i,\\ \\delta^*_i,\\ U_{e,i}\\right)

and three residuals: the momentum integral, a shape-parameter equation, and the
interaction law

.. math:: U_{e,i} = U^{inv}_{e,i} + \\sum_j A_{ij}\\, m_j,
          \\qquad m_j = U_{e,j}\\,\\delta^*_j

which states exactly how the outer flow responds to the displacement effect.
The matrix :math:`A` is assembled once per angle of attack by solving the
already-factorised panel system against a unit mass defect at each station, so
it is exact rather than a difference approximation.

Newton's method on the whole system converges at a rate set by the Jacobian's
conditioning, not by the spectral radius of any sub-iteration — which is why
``rho = 15.5`` stops being relevant. And because ``Ue`` is free to adjust, the
system stays regular through separation.

Closure
-------
Laminar stations use the kinetic-energy (shape-parameter) equation with Drela's
laminar closure, every constant of which is checked against the exact
Falkner-Skan family in :mod:`aerolab.viscous.falkner_skan`. Turbulent stations
use Head's entrainment equation with Ludwieg-Tillmann skin friction — the same
closure already validated in :mod:`aerolab.viscous.closure`, now solved
simultaneously rather than marched. Nothing new is asserted about turbulence
that was not already tested.

The one thing Head's closure cannot do is represent reversed flow: the
Ludwieg-Tillmann correlation is positive everywhere, so a turbulent station past
separation gets a small positive skin friction instead of a negative one. The
displacement effect is still captured, which is what sets the lift; the friction
drag in a separated region is not. See NOTES.md, L8.4.

Conventions
-----------
``alpha`` is in **radians**. Lengths are in chords, velocities are
non-dimensionalised by freestream speed, and ``reynolds`` is based on chord.
``s`` runs from the stagnation point along each surface and from the trailing
edge along the wake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import lu_solve

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.airfoil import Airfoil
from aerolab.inviscid.hess_smith import HessSmithSystem, PanelSolution
from aerolab.inviscid.influence import panel_influence
from aerolab.viscous.closure import thwaites_shape_factor
from aerolab.viscous.transition import (
    DEFAULT_N_CRIT,
    amplification_rate,
    critical_reynolds_theta,
)
from aerolab.viscous.wake import DEFAULT_WAKE_LENGTH, DEFAULT_WAKE_PANELS, Wake, build_wake

FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]

__all__ = [
    "H_STAGNATION",
    "PrescribedLayer",
    "solve_prescribed",
    "build_interaction",
    "build_layout",
    "LAMBDA_STAGNATION",
    "NewtonSolution",
    "StationLayout",
    "solve_newton",
    "newton_polar",
]

#: Shape factor at a plane stagnation point, from the exact Falkner-Skan
#: solution at ``beta = 1``. Used as the leading-edge starting condition.
#: Computed, not quoted: ``solve_falkner_skan(1.0).h`` gives 2.21623.
H_STAGNATION = 2.21623

#: Thwaites' parameter at a plane stagnation point, likewise exact.
#:
#: For ``Ue = K s`` the Falkner-Skan solution at ``beta = 1`` gives
#: ``theta**2 K / nu = delta_2**2`` with ``delta_2 = 0.292344``, hence 0.085465.
#: The value normally quoted for Thwaites' method is 0.075, which comes from
#: Thwaites' own integral rather than from the exact solution and is 12% low in
#: ``theta``; the exact value is used here because it is available.
LAMBDA_STAGNATION = 0.085465

#: Smallest shape factor the closure relations are evaluated at.
#:
#: Head's ``H <= 1.6`` branch contains ``(H - 1.1)**-1.287`` and is singular at
#: 1.1. A strongly accelerated turbulent layer can approach that, so ``H`` is
#: passed through a smooth floor before any correlation sees it. The floor is
#: smooth rather than a clip because a clip would make the Jacobian
#: discontinuous wherever it binds, and Newton's method needs a derivative.
H_FLOOR = 1.13

DEFAULT_TOLERANCE = 1e-9
DEFAULT_MAX_ITERATIONS = 60
DEFAULT_MAX_OUTER = 25

#: How close the transition position must come to settling, in chords.
#:
#: Transition is located by a correlation, on a grid whose stations near
#: mid-chord are about 0.01 chord apart. Demanding that it settle to 1e-4 asks
#: for a position ten times finer than the grid can express and a hundred times
#: finer than the correlation means anything, so the outer loop chases noise and
#: never terminates. 1e-3 chord is below the grid spacing and far below the
#: uncertainty in n_crit itself.
TRANSITION_TOLERANCE = 1e-3

#: Relaxation applied to each transition update.
#:
#: The update is a Newton step on n(s_tr) = n_crit, which would justify taking
#: it whole. Half of it is taken because the amplification integral depends on
#: the solution, which changes when transition moves — so the two chase each
#: other, and an undamped update oscillates about the answer instead of
#: settling on it.
TRANSITION_RELAXATION = 0.5

#: Transition closer than this fraction of a surface to its trailing edge is
#: treated as no transition at all.
#:
#: Near the trailing edge the transition criterion becomes bistable, and the
#: bistability is an artefact. Place transition at the surface end and the
#: laminar layer is found to separate just before it; place it at that
#: separation point and the shortened laminar run no longer separates, so the
#: criterion sends it back to the end. Measured on a NACA 4412 at Re = 1e6 the
#: outer loop cycled between 0.9926 and 0.9964 indefinitely.
#:
#: Both answers describe the same flow. A turbulent run 2% of a chord long
#: changes the momentum thickness by well under 1% and the drag by less, so the
#: distinction the criterion is trying to draw carries no physics. Snapping it
#: closed removes the cycle without changing any answer.
TRANSITION_SNAP = 0.02


# ---------------------------------------------------------------------------
# Smooth, unguarded closure
#
# The public correlations in aerolab.viscous.closure refuse inputs outside their
# fitted range, which is right for a user calling them directly and wrong inside
# a Newton iteration: an intermediate iterate may stray outside the range and
# still be on its way to a perfectly good solution. The versions here evaluate
# the same formulas with the guard replaced by a smooth floor on H, and they are
# asserted to agree with the public ones to machine precision inside the guarded
# range in tests/test_viscous_newton.py.
#
# They are also written to accept complex arguments, because the Jacobian is
# formed by complex-step differentiation: f'(x) = Im[f(x + ih)]/h is exact to
# machine precision for any analytic f, with none of the cancellation error of a
# real finite difference. That is what makes hand-differentiating these fits
# unnecessary — and hand-differentiation is where an error would hide.
# ---------------------------------------------------------------------------


def _soft_floor(x: ComplexArray, floor: float, width: float = 0.02) -> ComplexArray:
    """Smooth lower bound: ``~x`` well above ``floor``, ``~floor`` well below."""
    d = x - floor
    return floor + 0.5 * (d + np.sqrt(d * d + width * width))


def _pick(condition: NDArray[np.bool_], a: ComplexArray, b: ComplexArray) -> ComplexArray:
    """``np.where`` with a real-valued condition, safe for complex branches."""
    return np.where(condition, a, b)


def _laminar_h_star(h: ComplexArray) -> ComplexArray:
    low = h.real < 4.0
    return _pick(
        low,
        1.515 + 0.076 * (4.0 - h) ** 2 / h,
        1.515 + 0.040 * (h - 4.0) ** 2 / h,
    )


def _laminar_cf_reth(h: ComplexArray) -> ComplexArray:
    low = h.real < 7.4
    safe_high = _pick(low, np.full_like(h, 8.0), h)
    return _pick(
        low,
        -0.067 + 0.01977 * (7.4 - h) ** 2 / (h - 1.0),
        -0.067 + 0.022 * (1.0 - 1.4 / (safe_high - 6.0)) ** 2,
    )


def _laminar_diss_reth(h: ComplexArray) -> ComplexArray:
    low = h.real < 4.0
    # The 5.5 power of a negative base is not real; the branch is unused there,
    # but it must still evaluate to something finite for np.where.
    safe_low = _pick(low, 4.0 - h, np.ones_like(h))
    return _pick(
        low,
        0.207 + 0.00205 * safe_low**5.5,
        0.207 - 0.0016 * (h - 4.0) ** 2 / (1.0 + 0.02 * (h - 4.0) ** 2),
    )


#: Width of the blend across the discontinuity in Head's H1 correlation.
#:
#: Head's two branches are separate fits and they **do not meet**: at the switch
#: point H = 1.6 they give 5.3095 and 5.2866, a jump of 0.023. Marching the
#: equations, as the direct method does, steps over that jump without noticing.
#: Newton's method cannot: the residual it is driving to zero contains a
#: difference of H1 across an interval, so once an interval straddles H = 1.6
#: the residual has a floor equal to the jump and the line search collapses to
#: zero step length. Measured on a NACA 0012 at Re = 3e6 the iteration stalled
#: at a residual of 6.7e-3, which is the jump scaled by the interval.
#:
#: The blend is a tanh over this half-width in H, so the correlation becomes
#: analytic. It moves H1 by at most 0.011 (0.2%) and only for 1.54 < H < 1.66.
#: The public head_h1_from_h keeps the published form, discontinuity and all.
H1_BLEND_WIDTH = 0.02


def _head_h1(h: ComplexArray) -> ComplexArray:
    hs = _soft_floor(h, H_FLOOR)
    low = 3.3 + 0.8234 * (hs - 1.1) ** -1.287
    high = 3.3 + 1.5501 * (_soft_floor(hs, 0.75) - 0.6778) ** -3.064
    blend = 0.5 * (1.0 + np.tanh((hs - 1.6) / H1_BLEND_WIDTH))
    return (1.0 - blend) * low + blend * high


def _head_entrainment(h1: ComplexArray) -> ComplexArray:
    return 0.0306 * _soft_floor(h1 - 3.0, 0.05, 0.01) ** -0.6169


def _ludwieg_tillmann_cf(h: ComplexArray, re_theta: ComplexArray) -> ComplexArray:
    hs = _soft_floor(h, H_FLOOR)
    rt = _soft_floor(re_theta, 25.0, 5.0)
    return 0.246 * 10.0 ** (-0.678 * hs) * rt**-0.268


# ---------------------------------------------------------------------------
# Station layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StationLayout:
    """Where the boundary-layer unknowns live, and how they map onto panels.

    Three sides are laid out end to end into one global station index: the upper
    surface from the stagnation point to the trailing edge, then the lower
    surface likewise, then the wake. Each side has its own arc length starting
    at zero.

    Attributes
    ----------
    s : ndarray
        ``(n_stations,)`` arc length along the station's own side, in chords.
    side : ndarray
        ``(n_stations,)`` side index: 0 upper, 1 lower, 2 wake.
    panel : ndarray
        ``(n_stations,)`` index of the panel or wake panel the station sits on.
    sign : ndarray
        ``(n_stations,)`` ``-1`` where the panel tangent opposes the flow
        direction (the whole upper surface, because Selig ordering runs
        trailing edge to leading edge there) and ``+1`` elsewhere. The edge
        velocity is ``sign * v_tangential``, which keeps it positive and keeps
        the relation to the panel solution linear.
    starts : ndarray
        ``(3,)`` first global index of each side.
    counts : ndarray
        ``(3,)`` number of stations on each side.
    stagnation_s : float
        Arc length of the stagnation point along the airfoil contour.
    stagnation_panel : int
        Last panel on the upper surface.
    """

    s: FloatArray
    side: NDArray[np.int64]
    panel: NDArray[np.int64]
    sign: FloatArray
    starts: NDArray[np.int64]
    counts: NDArray[np.int64]
    stagnation_s: float
    stagnation_panel: int

    @property
    def n_stations(self) -> int:
        """Total number of boundary-layer stations."""
        return int(self.s.size)

    def side_slice(self, index: int) -> slice:
        """Global index range of one side."""
        start = int(self.starts[index])
        return slice(start, start + int(self.counts[index]))


def _locate_stagnation(
    v_tangential: FloatArray, s_control: FloatArray, n_surface: int
) -> tuple[int, float]:
    """Find where the tangential velocity changes sign near the leading edge.

    Returns the last upper-surface panel index and the interpolated arc length.
    The tangential velocity is negative over the upper surface and positive over
    the lower one, so the stagnation point is the single sign change; searching
    for it rather than assuming the leading-edge panel is what makes the layout
    correct at incidence, where the stagnation point moves well onto the lower
    surface.
    """
    v = v_tangential[:n_surface]
    crossings = np.nonzero((v[:-1] < 0.0) & (v[1:] >= 0.0))[0]
    if crossings.size == 0:
        raise ConvergenceError(
            "no stagnation point was found on the airfoil: the tangential "
            "velocity does not change sign anywhere on the surface. This means "
            "the inviscid solution is not a valid airfoil flow.",
            iterations=0,
            residual=float(np.min(np.abs(v))),
            tolerance=0.0,
        )
    index = int(crossings[0])
    span = v[index + 1] - v[index]
    fraction = 0.0 if abs(span) < 1e-30 else float(-v[index] / span)
    fraction = min(max(fraction, 0.0), 1.0)
    stagnation = float(
        s_control[index] + fraction * (s_control[index + 1] - s_control[index])
    )
    return index, stagnation


def build_layout(system: HessSmithSystem, wake: Wake, panel: PanelSolution) -> StationLayout:
    """Lay out boundary-layer stations on the panel control points and the wake.

    Parameters
    ----------
    system : HessSmithSystem
        The factorised panel system.
    wake : Wake
        The panelled wake.
    panel : PanelSolution
        An inviscid solution, used only to locate the stagnation point.

    Returns
    -------
    StationLayout

    Notes
    -----
    Stations sit on panel control points rather than on a resampled grid. That
    makes the mapping between the boundary layer and the inviscid problem exact
    — the transpiration a station produces is applied to the panel it lives on,
    with no interpolation in either direction — and interpolation between two
    grids is where the previous coupling lost its stagnation metadata (D4.1).
    """
    airfoil = system.airfoil
    n_surface = airfoil.n_points - 1
    arc = airfoil.arc_length
    s_control = 0.5 * (arc[:-1] + arc[1:])[:n_surface]

    stagnation_panel, stagnation_s = _locate_stagnation(
        panel.v_tangential, s_control, n_surface
    )

    upper_panels = np.arange(stagnation_panel, -1, -1)
    upper_s = stagnation_s - s_control[upper_panels]
    lower_panels = np.arange(stagnation_panel + 1, n_surface)
    lower_s = s_control[lower_panels] - stagnation_s

    if upper_s.size < 3 or lower_s.size < 3:
        raise ValidityRangeError(
            f"the stagnation point at panel {stagnation_panel} leaves only "
            f"{min(upper_s.size, lower_s.size)} stations on one surface. Repanel "
            "with more points, or reduce the angle of attack."
        )

    counts = np.array([upper_s.size, lower_s.size, wake.s.size], dtype=np.int64)
    starts = np.array([0, counts[0], counts[0] + counts[1]], dtype=np.int64)

    return StationLayout(
        s=np.concatenate([upper_s, lower_s, wake.s]),
        side=np.concatenate(
            [np.full(c, i, dtype=np.int64) for i, c in enumerate(counts)]
        ),
        panel=np.concatenate(
            [upper_panels, lower_panels, np.arange(wake.s.size)]
        ).astype(np.int64),
        sign=np.concatenate(
            [-np.ones(counts[0]), np.ones(counts[1]), np.ones(counts[2])]
        ),
        starts=starts,
        counts=counts,
        stagnation_s=stagnation_s,
        stagnation_panel=stagnation_panel,
    )


def _derivative_matrix(s: FloatArray) -> FloatArray:
    """Three-point non-uniform first-derivative operator on a 1-D grid.

    Second-order accurate in the interior and at both ends. The grid is the
    panel control points, which are clustered at the leading edge, so a uniform
    formula would be first-order there — exactly where the mass defect changes
    fastest.
    """
    n = s.size
    matrix = np.zeros((n, n))
    if n < 3:
        raise ValidityRangeError(
            f"a side needs at least 3 stations to differentiate, got {n}"
        )

    h1 = s[1:-1] - s[:-2]
    h2 = s[2:] - s[1:-1]
    rows = np.arange(1, n - 1)
    matrix[rows, rows - 1] = -h2 / (h1 * (h1 + h2))
    matrix[rows, rows] = (h2 - h1) / (h1 * h2)
    matrix[rows, rows + 1] = h1 / (h2 * (h1 + h2))

    for row, (a, b, c) in ((0, (0, 1, 2)), (n - 1, (n - 3, n - 2, n - 1))):
        sa, sb, sc = s[a], s[b], s[c]
        x = s[row]
        matrix[row, a] = (2 * x - sb - sc) / ((sa - sb) * (sa - sc))
        matrix[row, b] = (2 * x - sa - sc) / ((sb - sa) * (sb - sc))
        matrix[row, c] = (2 * x - sa - sb) / ((sc - sa) * (sc - sb))

    return matrix


# ---------------------------------------------------------------------------
# Exact linear response of the outer flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InteractionOperator:
    """The outer flow's exact linear response to the displacement effect.

    Attributes
    ----------
    ue_inviscid : ndarray
        ``(n_stations,)`` edge velocity with no displacement effect at all.
    matrix : ndarray
        ``(n_stations, n_stations)`` sensitivity ``dUe_i / dm_j`` of the edge
        velocity at station ``i`` to the mass defect at station ``j``.
    derivative : ndarray
        ``(n_stations, n_stations)`` operator taking the mass defect to the
        transpiration velocity, ``v_n = dm/ds``, side by side.
    """

    ue_inviscid: FloatArray
    matrix: FloatArray
    derivative: FloatArray

    def edge_velocity(self, mass_defect: FloatArray) -> FloatArray:
        """Edge velocity produced by a given mass defect."""
        return self.ue_inviscid + self.matrix @ mass_defect


def build_interaction(
    system: HessSmithSystem, wake: Wake, layout: StationLayout, alpha: float
) -> InteractionOperator:
    """Assemble the exact ``dUe/dm`` matrix for one geometry and incidence.

    Parameters
    ----------
    system : HessSmithSystem
        Factorised panel system.
    wake : Wake
        Panelled wake, whose geometry depends on incidence.
    layout : StationLayout
        Station layout.
    alpha : float
        Angle of attack in **radians**.

    Returns
    -------
    InteractionOperator

    Notes
    -----
    The panel problem is linear in its right-hand side, so the response to a
    unit mass defect at each station is obtained by one back-substitution
    against the existing factorisation — all of them at once, as a single solve
    with a matrix right-hand side. Nothing here is a finite difference, so the
    Jacobian rows that come from it are exact to machine precision.

    Both couplings are included: the airfoil's transpiration changes the
    velocity in the wake, and the wake's sources change the velocity on the
    airfoil, each through the full panel solution rather than as a direct
    induction. Leaving out the second is a common simplification and it is
    wrong by a few percent in ``Cl`` near the trailing edge, because the wake
    sources sit where the Kutta condition is applied.
    """
    n_panels = system.n_panels
    n_surface = system.airfoil.n_points - 1
    n_wake = wake.n_panels
    n_stations = layout.n_stations

    # Mass defect -> (panel transpiration, wake source strength).
    derivative = np.zeros((n_stations, n_stations))
    for index in range(3):
        sl = layout.side_slice(index)
        derivative[sl, sl] = _derivative_matrix(layout.s[sl])

    to_panel = np.zeros((n_panels, n_stations))
    to_wake = np.zeros((n_wake, n_stations))
    surface = layout.side < 2
    to_panel[layout.panel[surface], np.nonzero(surface)[0]] = 1.0
    wake_rows = layout.side == 2
    to_wake[layout.panel[wake_rows], np.nonzero(wake_rows)[0]] = 1.0
    to_panel = to_panel @ derivative
    to_wake = to_wake @ derivative
    if system.has_base_panel:
        to_panel[n_surface:, :] = 0.0

    # Influence of the wake sheet on the airfoil control points, and of the
    # airfoil on the wake control points.
    wake_on_body, _ = panel_influence(wake.starts, wake.ends, system.control_points)
    body_source_on_wake, body_vortex_on_wake = panel_influence(
        system.starts, system.ends, wake.control_points
    )
    wake_on_wake, _ = panel_influence(wake.starts, wake.ends, wake.control_points)
    diagonal = np.arange(n_wake)
    wake_on_wake[diagonal, diagonal, :] = 0.0

    upper, lower = system.kutta_indices

    def response(
        transpiration: FloatArray, wake_strength: FloatArray, stream: FloatArray
    ) -> FloatArray:
        """Signed edge velocity at every station for one loading case.

        ``transpiration`` is ``(n_panels, k)``, ``wake_strength`` is
        ``(n_wake, k)`` and ``stream`` is ``(2, k)``.
        """
        external = np.einsum("pmk,mj->pkj", wake_on_body, wake_strength)
        rhs = np.zeros((n_panels + 1, transpiration.shape[1]))
        rhs[:n_panels] = transpiration - np.einsum(
            "pkj,pk->pj", external, system.normals
        )
        rhs[n_panels] = -(
            np.einsum("kj,k->j", external[upper], system.tangents[upper])
            + np.einsum("kj,k->j", external[lower], system.tangents[lower])
        )
        rhs[:n_panels] -= np.einsum("kj,pk->pj", stream, system.normals)
        rhs[n_panels] -= (
            np.einsum("kj,k->j", stream, system.tangents[upper])
            + np.einsum("kj,k->j", stream, system.tangents[lower])
        )

        solution = lu_solve(system._lu, rhs)
        sources, gamma = solution[:n_panels], solution[n_panels]

        v_body = (
            system._source_tangent @ sources
            + np.outer(system._vortex_tangent, gamma)
            + system.tangents @ stream
        )
        induced_on_wake = (
            np.einsum("wpk,pj->wkj", body_source_on_wake, sources)
            + np.einsum("wpk,j->wkj", body_vortex_on_wake, gamma)
            + np.einsum("wmk,mj->wkj", wake_on_wake, wake_strength)
        )
        v_wake = np.einsum("wkj,wk->wj", induced_on_wake, wake.tangents) + np.einsum(
            "kj,wk->wj", stream, wake.tangents
        )

        out = np.empty((n_stations, transpiration.shape[1]))
        out[surface] = v_body[layout.panel[surface]]
        out[wake_rows] = v_wake[layout.panel[wake_rows]]
        return layout.sign[:, None] * out

    stream = HessSmithSystem.freestream(alpha).reshape(2, 1)
    zeros_panel = np.zeros((n_panels, 1))
    zeros_wake = np.zeros((n_wake, 1))
    ue_inviscid = response(zeros_panel, zeros_wake, stream)[:, 0]

    no_stream = np.zeros((2, n_stations))
    matrix = response(to_panel, to_wake, no_stream)

    return InteractionOperator(
        ue_inviscid=ue_inviscid, matrix=matrix, derivative=derivative
    )


# ---------------------------------------------------------------------------
# Residuals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Problem:
    """Everything the residual function needs that does not change during Newton."""

    layout: StationLayout
    interaction: InteractionOperator
    reynolds: float
    te_gap: float
    left: NDArray[np.int64]
    right: NDArray[np.int64]
    spacing: FloatArray
    wall: FloatArray
    turbulent: FloatArray
    first: NDArray[np.int64]
    te_upper: int
    te_lower: int
    wake_first: int
    te_length: float


def _build_problem(
    layout: StationLayout,
    interaction: InteractionOperator,
    reynolds: float,
    te_gap: float,
    turbulent: FloatArray,
) -> _Problem:
    left, right, wall = [], [], []
    for index in range(3):
        sl = layout.side_slice(index)
        indices = np.arange(sl.start, sl.stop)
        left.append(indices[:-1])
        right.append(indices[1:])
        wall.append(np.full(indices.size - 1, 0.0 if index == 2 else 1.0))
    left_a = np.concatenate(left)
    right_a = np.concatenate(right)
    return _Problem(
        layout=layout,
        interaction=interaction,
        reynolds=reynolds,
        te_gap=te_gap,
        left=left_a,
        right=right_a,
        spacing=layout.s[right_a] - layout.s[left_a],
        wall=np.concatenate(wall),
        turbulent=turbulent,
        first=layout.starts.copy(),
        te_upper=int(layout.starts[1]) - 1,
        te_lower=int(layout.starts[2]) - 1,
        wake_first=int(layout.starts[2]),
        te_length=float(layout.s[int(layout.starts[2])]),
    )


def _interval_residuals(
    theta_l: ComplexArray,
    theta_r: ComplexArray,
    dstar_l: ComplexArray,
    dstar_r: ComplexArray,
    ue_l: ComplexArray,
    ue_r: ComplexArray,
    spacing: FloatArray,
    turbulent: FloatArray,
    wall: FloatArray,
    reynolds: float,
) -> tuple[ComplexArray, ComplexArray]:
    """Momentum and shape-parameter residuals on every interval at once.

    Returns
    -------
    (momentum, shape) : tuple of ndarray
        Both divided through by the mean momentum thickness, which makes them
        dimensionless and of comparable size. Without that scaling the shape
        residual on a laminar interval is four orders of magnitude smaller than
        the momentum residual, and the Newton step is dominated by whichever
        happens to have the larger units rather than by the larger error.

    Notes
    -----
    The momentum integral

    .. math:: \\frac{d\\theta}{ds} + (2 + H)\\frac{\\theta}{U_e}
              \\frac{dU_e}{ds} = \\frac{c_f}{2}

    is discretised at the interval midpoint, with
    :math:`(\\theta/U_e)dU_e = \\theta\\, d(\\ln U_e)` written in logarithmic
    form. That is not cosmetic: it is exact for the exponential edge-velocity
    variation that occurs near a stagnation point, where a linear difference in
    ``Ue`` loses most of its accuracy.

    The second equation is the **kinetic energy** equation where the flow is
    laminar,

    .. math:: \\theta\\frac{dH^*}{ds} + H^*(1-H)\\frac{\\theta}{U_e}
              \\frac{dU_e}{ds} = 2c_D - H^*\\frac{c_f}{2}

    and **Head's entrainment** equation where it is turbulent,

    .. math:: \\frac{d}{ds}\\left(U_e\\theta H_1\\right) = U_e F(H_1)

    blended linearly across the interval containing transition by the turbulent
    fraction. Both determine the shape factor; using the kinetic-energy form
    for the laminar run is what allows ``H`` to pass through separation, since
    Drela's laminar skin friction is a function of ``H`` alone and goes
    negative, whereas Thwaites' correlation is parameterised by a pressure
    gradient that becomes meaningless there.
    """
    theta_bar = 0.5 * (theta_l + theta_r)
    h_l, h_r = dstar_l / theta_l, dstar_r / theta_r
    h_bar = 0.5 * (h_l + h_r)
    dln_ue = np.log(ue_r) - np.log(ue_l)
    ds_over_theta = spacing / theta_bar
    weight = turbulent

    reth_l = reynolds * ue_l * theta_l
    reth_r = reynolds * ue_r * theta_r

    cf_lam_l = _laminar_cf_reth(h_l) / reth_l
    cf_lam_r = _laminar_cf_reth(h_r) / reth_r
    cf_turb_l = 0.5 * _ludwieg_tillmann_cf(h_l, reth_l)
    cf_turb_r = 0.5 * _ludwieg_tillmann_cf(h_r, reth_r)
    cf_l = wall * ((1.0 - weight) * cf_lam_l + weight * cf_turb_l)
    cf_r = wall * ((1.0 - weight) * cf_lam_r + weight * cf_turb_r)
    cf_bar = 0.5 * (cf_l + cf_r)

    momentum = (
        (theta_r - theta_l) / theta_bar
        + (2.0 + h_bar) * dln_ue
        - cf_bar * ds_over_theta
    )

    hs_l, hs_r = _laminar_h_star(h_l), _laminar_h_star(h_r)
    hs_bar = 0.5 * (hs_l + hs_r)
    cd_l = _laminar_diss_reth(h_l) * hs_l / (2.0 * reth_l)
    cd_r = _laminar_diss_reth(h_r) * hs_r / (2.0 * reth_r)
    shape_laminar = (
        (hs_r - hs_l)
        + hs_bar * (1.0 - h_bar) * dln_ue
        - (2.0 * 0.5 * (cd_l + cd_r) - hs_bar * 0.5 * (wall * cf_lam_l + wall * cf_lam_r))
        * ds_over_theta
    )

    h1_l, h1_r = _head_h1(h_l), _head_h1(h_r)
    h1_bar = 0.5 * (h1_l + h1_r)
    entrainment = 0.5 * (_head_entrainment(h1_l) + _head_entrainment(h1_r))
    shape_turbulent = (
        h1_bar * (theta_r - theta_l) / theta_bar
        + (h1_r - h1_l)
        + h1_bar * dln_ue
        - entrainment * ds_over_theta
    )

    shape = (1.0 - weight) * shape_laminar + weight * shape_turbulent
    return momentum, shape


def _trailing_edge_pair(
    theta: ComplexArray, dstar: ComplexArray, ue: ComplexArray, problem: _Problem
) -> tuple[ComplexArray, ComplexArray]:
    """Momentum and shape residuals across the trailing-edge gap.

    The wake does not begin where the surface stations end. The last surface
    control point sits half a panel *before* the trailing edge and the first
    wake control point half a panel *after* it, and between them the edge
    velocity recovers sharply from its trailing-edge minimum — measured on a
    NACA 0012 at Re = 3e6, from 0.823 to 0.903 over 0.014 chord.

    Handing the wake an algebraic starting condition, ``theta_wake = theta_upper
    + theta_lower``, silently skips that interval. The momentum it skips is
    ``theta (H+2) d(ln U_e) = 1.9e-3``, which is 35% of the momentum thickness —
    so the wake never sheds it, the far-wake momentum defect comes out a third
    too large, and the drag with it. The symptom was a Squire-Young drag of
    0.0077 against a published 0.0060, while the *surface* trailing-edge state
    that fed it was correct to 6%.

    So the joint is an interval like any other, integrated from the combined
    trailing-edge state to the first wake station. The upper and lower layers
    merge there: momentum thicknesses add, displacement thicknesses add along
    with the blunt-base gap, and the edge velocity is the mean of the two, since
    the wake has one edge velocity and the two surfaces arrive with their own.
    """
    combined_theta = theta[problem.te_upper] + theta[problem.te_lower]
    combined_dstar = (
        dstar[problem.te_upper] + dstar[problem.te_lower] + problem.te_gap
    )
    combined_ue = 0.5 * (ue[problem.te_upper] + ue[problem.te_lower])
    index = problem.wake_first
    one = np.ones(1)
    momentum, shape = _interval_residuals(
        np.atleast_1d(combined_theta),
        np.atleast_1d(theta[index]),
        np.atleast_1d(combined_dstar),
        np.atleast_1d(dstar[index]),
        np.atleast_1d(combined_ue),
        np.atleast_1d(ue[index]),
        np.atleast_1d(problem.te_length),
        one,
        0.0 * one,
        problem.reynolds,
    )
    return momentum[0], shape[0]


def _residuals(state: ComplexArray, problem: _Problem) -> ComplexArray:
    """Full residual vector: momentum, shape, and interaction, in that order."""
    n = problem.layout.n_stations
    theta, dstar, ue = state[:n], state[n : 2 * n], state[2 * n :]
    out = np.zeros(3 * n, dtype=state.dtype)

    momentum, shape = _interval_residuals(
        theta[problem.left],
        theta[problem.right],
        dstar[problem.left],
        dstar[problem.right],
        ue[problem.left],
        ue[problem.right],
        problem.spacing,
        problem.turbulent,
        problem.wall,
        problem.reynolds,
    )
    out[problem.right] = momentum
    out[n + problem.right] = shape

    # Leading-edge starting conditions, from the exact stagnation-point solution.
    s = problem.layout.s
    for side in (0, 1):
        i = int(problem.first[side])
        out[i] = (
            problem.reynolds * theta[i] ** 2 * ue[i] / s[i]
        ) / LAMBDA_STAGNATION - 1.0
        out[n + i] = dstar[i] / theta[i] / H_STAGNATION - 1.0

    # The wake inherits the two surface layers, integrated across the joint.
    w = problem.wake_first
    out[w], out[n + w] = _trailing_edge_pair(theta, dstar, ue, problem)

    out[2 * n :] = (
        ue - problem.interaction.ue_inviscid - problem.interaction.matrix @ (ue * dstar)
    )
    return out


def _jacobian(state: FloatArray, problem: _Problem) -> FloatArray:
    """Assemble the Jacobian: complex-step for the closure, exact for the rest.

    Notes
    -----
    The interval residuals are differentiated by the complex step
    :math:`f'(x) = \\mathrm{Im}[f(x + ih)]/h`, which for an analytic ``f`` is
    exact to machine precision at any ``h`` small enough not to underflow —
    there is no subtraction and therefore no cancellation error, unlike a real
    finite difference. Every closure relation used here was written to be
    analytic for exactly this reason.

    Six evaluations suffice for the whole matrix, one per variable of the
    interval stencil, because all intervals are perturbed simultaneously and
    they do not interact. The interaction rows are written down analytically:
    they are bilinear in ``Ue`` and ``delta*``.
    """
    n = problem.layout.n_stations
    step = 1e-30
    jac = np.zeros((3 * n, 3 * n))

    theta, dstar, ue = state[:n], state[n : 2 * n], state[2 * n :]
    args = [
        theta[problem.left],
        theta[problem.right],
        dstar[problem.left],
        dstar[problem.right],
        ue[problem.left],
        ue[problem.right],
    ]
    # (block offset, stencil side) for each of the six stencil variables.
    targets = [
        (0, problem.left),
        (0, problem.right),
        (n, problem.left),
        (n, problem.right),
        (2 * n, problem.left),
        (2 * n, problem.right),
    ]
    rows = problem.right
    for position, (offset, columns) in enumerate(targets):
        perturbed = [np.asarray(a, dtype=np.complex128) for a in args]
        perturbed[position] = perturbed[position] + 1j * step
        momentum, shape = _interval_residuals(
            *perturbed, problem.spacing, problem.turbulent, problem.wall,
            problem.reynolds,
        )
        jac[rows, offset + columns] += momentum.imag / step
        jac[n + rows, offset + columns] += shape.imag / step

    s = problem.layout.s
    for side in (0, 1):
        i = int(problem.first[side])
        jac[i, i] = 2.0 * problem.reynolds * theta[i] * ue[i] / s[i] / LAMBDA_STAGNATION
        jac[i, 2 * n + i] = (
            problem.reynolds * theta[i] ** 2 / s[i] / LAMBDA_STAGNATION
        )
        jac[n + i, i] = -dstar[i] / theta[i] ** 2 / H_STAGNATION
        jac[n + i, n + i] = 1.0 / theta[i] / H_STAGNATION

    w = problem.wake_first
    for column in (
        problem.te_upper, problem.te_lower, w,
        n + problem.te_upper, n + problem.te_lower, n + w,
        2 * n + problem.te_upper, 2 * n + problem.te_lower, 2 * n + w,
    ):
        probe = state.astype(np.complex128)
        probe[column] += 1j * step
        momentum, shape = _trailing_edge_pair(
            probe[:n], probe[n : 2 * n], probe[2 * n :], problem
        )
        jac[w, column] = momentum.imag / step
        jac[n + w, column] = shape.imag / step

    matrix = problem.interaction.matrix
    jac[2 * n :, n : 2 * n] = -matrix * ue[None, :]
    jac[2 * n :, 2 * n :] = np.eye(n) - matrix * dstar[None, :]
    return jac


# ---------------------------------------------------------------------------
# Transition
# ---------------------------------------------------------------------------


def _transition_locations(
    state: FloatArray,
    problem: _Problem,
    reynolds: float,
    n_crit: float,
    current: list[float] | None = None,
) -> tuple[list[float], list[str]]:
    """Update the transition position so that ``n(s_tr) = n_crit`` is satisfied.

    Parameters
    ----------
    state : ndarray
        Current solution vector.
    problem : _Problem
        The problem the state solves, for the layout and station spacing.
    reynolds : float
        Reynolds number based on chord.
    n_crit : float
        Amplification factor at transition.
    current : list of float, optional
        Transition position the state was solved with, one per surface. The
        default treats the solution as laminar everywhere.

    Returns
    -------
    (locations, causes) : tuple
        Arc length of transition on each surface, and what set it:
        ``"amplification"``, ``"laminar-separation"`` or ``"none"``.

    Notes
    -----
    Scanning for the first station where the amplification factor exceeds
    ``n_crit`` **cannot work**, and the reason is worth stating because it is not
    obvious and it cost a working solver. Imposing transition at ``s_tr`` makes
    the layer turbulent downstream of it, and a turbulent station has an
    enormous critical Reynolds number, so the amplification factor stops growing
    there by construction. The factor can therefore never exceed whatever it had
    reached at ``s_tr``. Measured on a NACA 0012 at Re = 3e6 with transition
    imposed at ``s = 0.438``, it plateaus at **7.93** against ``n_crit = 9`` — so
    the scan reports "no transition", the next pass runs the layer laminar to
    the trailing edge, that pass reports transition far aft, and the outer loop
    oscillates between the two for ever. That is exactly what it did.

    The condition is not "``n`` exceeds ``n_crit`` somewhere". It is
    ``n(s_{tr}) = n_{crit}`` **at** the transition point, which is a scalar
    equation in ``s_tr``. It is solved here by a Newton step,

    .. math:: s_{tr} \\leftarrow s_{tr} +
              \\frac{n_{crit} - n(s_{tr})}{dn/ds}

    with the growth rate taken from the last laminar station. Since ``n`` is
    monotone in ``s_tr`` this converges in a handful of outer passes from any
    starting guess, and it converges *to* a position rather than oscillating
    between two.

    A laminar layer that separates first overrides the amplification result. A
    separated laminar profile has an inflection point well away from the wall
    and is violently unstable, so transition follows almost immediately;
    treating separation as a trigger is what allows a laminar separation bubble
    to reattach instead of running laminar through a region where no laminar
    layer could survive.
    """
    from aerolab.viscous.closure import H_SEPARATION_LAMINAR

    n = problem.layout.n_stations
    theta, dstar, ue = state[:n], state[n : 2 * n], state[2 * n :]
    layout = problem.layout
    limits = (
        [float(layout.s[layout.side_slice(i)][-1]) for i in (0, 1)]
        if current is None
        else list(current)
    )
    locations: list[float] = []
    causes: list[str] = []

    for side in (0, 1):
        sl = layout.side_slice(side)
        s = layout.s[sl]
        h = np.clip(dstar[sl] / theta[sl], 1.0001, None)
        re_theta = reynolds * ue[sl] * theta[sl]
        critical = critical_reynolds_theta(h)
        rate = amplification_rate(h)

        growth = np.diff(re_theta)
        active = (re_theta[1:] > critical[1:]) & (growth > 0.0)
        increments = np.where(active, 0.5 * (rate[1:] + rate[:-1]) * growth, 0.0)

        # Only the part of the solution that was actually solved laminar carries
        # information about amplification.
        laminar = int(np.searchsorted(s, min(limits[side], s[-1]), side="right"))
        laminar = max(min(laminar, s.size), 2)
        amplification = np.concatenate([[0.0], np.cumsum(increments[: laminar - 1])])

        location, cause = float(s[-1]), "none"
        reached = np.nonzero(amplification >= n_crit)[0]
        if reached.size:
            j = int(reached[0])
            span = amplification[j] - amplification[j - 1]
            fraction = 1.0 if span <= 0.0 else (n_crit - amplification[j - 1]) / span
            location = float(s[j - 1] + fraction * (s[j] - s[j - 1]))
            cause = "amplification"
        elif laminar < s.size:
            # The laminar run was cut short before the factor got there. Step the
            # transition point downstream by as much as the local growth rate
            # says is needed.
            j = laminar - 1
            slope = (
                rate[j] * growth[j - 1] / max(s[j] - s[j - 1], 1e-12)
                if j >= 1 and re_theta[j] > critical[j]
                else 0.0
            )
            target = (
                s[j] + (n_crit - amplification[-1]) / slope
                if slope > 0.0
                else s[-1]
            )
            location = float(min(target, s[-1]))
            cause = "amplification" if location < s[-1] else "none"

        upstream = min(location, limits[side])
        separated = np.nonzero((h >= H_SEPARATION_LAMINAR) & (s <= upstream))[0]
        if separated.size:
            j = int(separated[0])
            if j > 0:
                span = h[j] - h[j - 1]
                fraction = (
                    1.0 if span <= 0.0 else (H_SEPARATION_LAMINAR - h[j - 1]) / span
                )
                candidate = float(s[j - 1] + fraction * (s[j] - s[j - 1]))
            else:
                candidate = float(s[j])
            if candidate < location:
                location, cause = candidate, "laminar-separation"

        if location > (1.0 - TRANSITION_SNAP) * s[-1]:
            location, cause = float(s[-1]), "none"
        locations.append(location)
        causes.append(cause)

    return locations, causes


def _turbulent_weights(
    layout: StationLayout, left: NDArray[np.int64], right: NDArray[np.int64],
    locations: list[float],
) -> FloatArray:
    """Fraction of each interval that is turbulent, in ``[0, 1]``.

    A discrete transition index would make the residual a step function of the
    solution and the outer iteration would cycle between two neighbouring
    stations for ever. A fraction makes it continuous, so the outer loop
    converges on a transition position rather than oscillating between two
    panels.
    """
    weight = np.zeros(left.size)
    for side in (0, 1):
        sl = layout.side_slice(side)
        mask = (left >= sl.start) & (left < sl.stop)
        s_left, s_right = layout.s[left[mask]], layout.s[right[mask]]
        weight[mask] = np.clip(
            (s_right - locations[side]) / np.maximum(s_right - s_left, 1e-15), 0.0, 1.0
        )
    weight[(left >= layout.side_slice(2).start)] = 1.0
    return weight


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewtonSolution:
    """A simultaneously converged viscous-inviscid solution at one incidence.

    Attributes
    ----------
    panel : PanelSolution
        Inviscid solution carrying the converged transpiration and wake sources,
        so its pressures and forces are the viscous ones.
    layout : StationLayout
        Where the boundary-layer stations sit.
    theta, delta_star, ue : ndarray
        ``(n_stations,)`` momentum thickness, displacement thickness (both in
        chords) and edge velocity (non-dimensional).
    transition_s : tuple of float
        Transition arc length on the upper and lower surface, in chords from the
        stagnation point. ``inf`` if the surface never transitioned.
    transition_cause : tuple of str
        ``"amplification"``, ``"laminar-separation"`` or ``"none"``.
    iterations, outer_iterations : int
        Newton steps taken in the last outer pass, and outer passes.
    residual : float
        Final infinity norm of the residual vector.
    converged : bool
        Whether the residual fell below the tolerance **and** the transition
        location stopped moving.
    history : ndarray
        Residual at every Newton step of the last outer pass.
    """

    panel: PanelSolution
    layout: StationLayout
    theta: FloatArray
    delta_star: FloatArray
    ue: FloatArray
    reynolds: float
    transpiration: FloatArray
    wake_strengths: FloatArray
    transition_s: tuple[float, float]
    transition_cause: tuple[str, str]
    iterations: int
    outer_iterations: int
    residual: float
    converged: bool
    tolerance: float
    history: FloatArray = field(default_factory=lambda: np.empty(0))

    @property
    def alpha(self) -> float:
        """Angle of attack in **radians**."""
        return self.panel.alpha

    @property
    def cl(self) -> float:
        """Lift coefficient, from integrating the coupled surface pressure."""
        return self.panel.cl_pressure

    @property
    def cm_quarter_chord(self) -> float:
        """Pitching moment about the quarter chord, positive nose-up."""
        return self.panel.cm_quarter_chord

    @property
    def shape_factor(self) -> FloatArray:
        """``H = delta*/theta`` at every station."""
        return self.delta_star / self.theta

    @cached_property
    def cd(self) -> float:
        """Profile drag, by Squire-Young evaluated at the end of the wake.

        Notes
        -----
        .. math:: C_d = 2\\theta_\\infty
                  \\left(U_{e,\\infty}\\right)^{\\frac{H_\\infty + 5}{2}}

        Taking it at the far end of the wake rather than at the trailing edge is
        what makes it a *total* drag: pressure and friction have both already
        been converted into momentum defect by the time the wake has relaxed, so
        no separate form-drag term is needed and none is added. At the trailing
        edge the same formula is an extrapolation, and the difference between
        the two is a useful check that the wake is long enough — it is reported
        as :attr:`wake_convergence`.
        """
        h = float(self.shape_factor[-1])
        return float(2.0 * self.theta[-1] * self.ue[-1] ** ((h + 5.0) / 2.0))

    @property
    def wake_convergence(self) -> float:
        """Relative change in the Squire-Young drag over the last tenth of the wake.

        A small number means the wake has relaxed far enough that the drag no
        longer depends on where it is truncated. A large one means it has not,
        and the drag should not be trusted.
        """
        start = self.layout.side_slice(2).start
        stations = np.arange(start, self.layout.n_stations)
        if stations.size < 4:
            return np.inf
        h = self.shape_factor[stations]
        drag = 2.0 * self.theta[stations] * self.ue[stations] ** ((h + 5.0) / 2.0)
        tail = max(stations.size // 10, 2)
        return float(abs(drag[-1] - drag[-tail]) / abs(drag[-1]))

    @property
    def max_shape_factor(self) -> float:
        """Largest ``H`` anywhere on the two surfaces."""
        return float(np.max(self.shape_factor[self.layout.side < 2]))

    @property
    def closure_in_range(self) -> bool:
        """Whether every surface station stayed inside Head's fitted range.

        Head's entrainment correlation was fitted for ``H`` up to 3.0. Beyond
        that the solver is extrapolating, and it is extrapolating a relation
        whose sensitivity has almost vanished: ``dH1/dH`` falls from -16.6 at
        ``H = 1.4`` to -0.036 at ``H = 4.0``, a factor of 460. The shape
        equation therefore stops determining ``H`` at exactly the point where
        separation begins, and the solve either fails or, worse, converges on a
        shape factor of 40. This flag is how that is reported instead of
        happening quietly. See NOTES.md, L8.5.
        """
        from aerolab.viscous.closure import HEAD_H_MAX

        return self.max_shape_factor <= HEAD_H_MAX

    @property
    def separated(self) -> bool:
        """Whether any **turbulent** station has passed the separation shape factor.

        Only turbulent stations count. A laminar shape factor of 2.6 is entirely
        ordinary — Blasius alone is 2.59 — so applying the turbulent separation
        threshold to the laminar run reports separation on every attached
        airfoil at zero incidence, which it did before this was fixed.
        """
        from aerolab.viscous.closure import TURBULENT_SEPARATION_H

        turbulent = np.zeros(self.layout.n_stations, dtype=bool)
        for side in (0, 1):
            sl = self.layout.side_slice(side)
            turbulent[sl] = self.layout.s[sl] > self.transition_s[side]
        return bool(np.any(self.shape_factor[turbulent] > TURBULENT_SEPARATION_H))

    def check(self) -> "NewtonSolution":
        """Raise unless the solve converged with its closure inside its range."""
        from aerolab.viscous.closure import HEAD_H_UNINFORMATIVE

        if self.converged and self.max_shape_factor > HEAD_H_UNINFORMATIVE:
            raise ConvergenceError(
                f"the solve converged but the shape factor reached "
                f"{self.max_shape_factor:.2f}, where Head's entrainment "
                f"correlation has stopped responding to it (dH1/dH is 460 times "
                f"smaller than at H = 1.4). The shape factor is no longer "
                f"determined by the equations, so this is not a prediction "
                f"(NOTES.md, L8.5).",
                iterations=self.iterations,
                residual=self.residual,
                tolerance=self.tolerance,
            )
        if not self.converged:
            reason = (
                "the transition position never settled"
                if self.residual < self.tolerance
                else "the residual never reached the tolerance"
            )
            raise ConvergenceError(
                f"the simultaneous Newton solve did not converge at alpha = "
                f"{np.rad2deg(self.alpha):.2f} deg, Re = {self.reynolds:.3g}: "
                f"{reason} in {self.outer_iterations} outer passes",
                iterations=self.iterations,
                residual=self.residual,
                tolerance=self.tolerance,
            )
        return self

    def __repr__(self) -> str:
        state = "converged" if self.converged else "NOT CONVERGED"
        return (
            f"<NewtonSolution alpha={np.rad2deg(self.alpha):.2f} deg, "
            f"Cl={self.cl:.4f}, Cd={self.cd:.5f}, {self.iterations} steps, "
            f"residual {self.residual:.1e}, Hmax={self.max_shape_factor:.2f}"
            f"{'' if self.closure_in_range else ' (closure extrapolated)'}, {state}>"
        )


def _initial_state(
    layout: StationLayout, ue_inviscid: FloatArray, reynolds: float, te_gap: float
) -> FloatArray:
    """A starting guess: Thwaites on the inviscid edge velocity.

    Newton's method needs somewhere to start, and the uncoupled boundary layer
    is the obvious place. It is only a guess — the stagnation-point condition
    and the interaction law are both violated by it — but it has the right order
    of magnitude everywhere, which is all that is needed.
    """
    n = layout.n_stations
    theta = np.zeros(n)
    dstar = np.zeros(n)
    ue = np.maximum(np.abs(ue_inviscid), 1e-3)

    for side in (0, 1):
        sl = layout.side_slice(side)
        s, u = layout.s[sl], ue[sl]
        first = np.sqrt(LAMBDA_STAGNATION * s[0] / (reynolds * u[0]))
        integral = np.concatenate(
            [[0.0], np.cumsum(0.5 * (u[1:] ** 5 + u[:-1] ** 5) * np.diff(s))]
        )
        squared = first**2 * (u[0] / u) ** 6 + 0.45 * integral / (reynolds * u**6)
        theta[sl] = np.sqrt(np.maximum(squared, 1e-14))
        # The shape factor has to come from Thwaites' parameter, not from a
        # constant. The starting guess is what the first transition estimate is
        # made on, and a constant H = 2.2 makes the amplification rate too low
        # and the critical Reynolds number too high everywhere at once — so e^N
        # never fires, the solver starts from "laminar to the trailing edge",
        # and at high Reynolds number that state has no solution at all.
        gradient = _derivative_matrix(s) @ u
        lambda_ = np.clip(reynolds * theta[sl] ** 2 * gradient, -0.09, 0.09)
        dstar[sl] = thwaites_shape_factor(lambda_) * theta[sl]

    wake = layout.side_slice(2)
    theta_te = theta[wake.start - 1] + theta[layout.starts[1] - 1]
    dstar_te = dstar[wake.start - 1] + dstar[layout.starts[1] - 1] + te_gap
    relax = np.linspace(0.0, 1.0, layout.counts[2])
    theta[wake] = theta_te
    dstar[wake] = dstar_te * (1.0 - relax) + 1.3 * theta_te * relax

    return np.concatenate([theta, dstar, ue])


#: Largest multiplicative change any unknown may take in one Newton step.
#:
#: The step is taken in the logarithms of the unknowns, so this is a factor:
#: 1.0 allows a station to change by e = 2.72 either way in a single step.
MAX_LOG_STEP = 1.0


def _log_step(
    state: FloatArray, jacobian: FloatArray, residual: FloatArray
) -> FloatArray:
    """Newton step in the logarithms of the unknowns.

    Notes
    -----
    Every unknown here — momentum thickness, displacement thickness, edge
    velocity — is positive, and the natural step is multiplicative rather than
    additive. Working in ``ln`` makes that automatic: no iterate can go
    negative, and a limit on the step is a limit on a *ratio*, which means the
    same thing at every station.

    Taking additive steps and clipping them instead does not work, and the way
    it fails is instructive. The clip is global — one fraction applied to the
    whole Newton direction — so a single station with a small ``Ue`` can veto
    the entire step. Near the stagnation point ``Ue`` is small by construction,
    and on a NACA 0012 at 2 degrees it was 0.013 there: a Newton direction
    asking that station to change by 5 shrank the step for all 435 unknowns to
    2e-4, the residual stalled at 3.3, and the solve failed. The same case
    converges in four steps in logarithmic variables.

    The chain rule is a column scaling, since
    ``dR/d(ln x_j) = (dR/dx_j) x_j``, so the physical Jacobian is reused
    unchanged and nothing has to be differentiated twice.
    """
    scaled = jacobian * state[None, :]
    delta = np.linalg.solve(scaled, -residual)
    largest = float(np.max(np.abs(delta)))
    if largest > MAX_LOG_STEP:
        delta = delta * (MAX_LOG_STEP / largest)
    return delta


def _remap_state(previous: "NewtonSolution", layout: StationLayout) -> FloatArray:
    """Carry a solution from one station layout onto another, by arc length.

    Notes
    -----
    The layout depends on where the stagnation point sits, and that moves with
    incidence, so consecutive angles in a sweep rarely share a grid. Copying the
    state vector across regardless is a silent disaster: at 0 and 1 degrees on a
    NACA 0012 the stagnation point shifts by one panel, so the upper surface
    gains a station and the lower loses one, the **total length is unchanged**,
    and a length check passes while every station means something different.
    The symptom was a lift coefficient of 1.11 at one degree.

    Interpolating side by side in arc length is both safe and better: it keeps
    the continuation useful when the grid changes instead of throwing the guess
    away.
    """
    n = layout.n_stations
    state = np.empty(3 * n)
    for side in range(3):
        target = layout.side_slice(side)
        source = previous.layout.side_slice(side)
        s_old = previous.layout.s[source]
        s_new = layout.s[target]
        for block, values in enumerate(
            (previous.theta, previous.delta_star, previous.ue)
        ):
            state[block * n + target.start : block * n + target.stop] = np.interp(
                s_new, s_old, values[source]
            )
    return state


def solve_newton(
    airfoil: Airfoil,
    alpha: float,
    reynolds: float,
    *,
    n_crit: float = DEFAULT_N_CRIT,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_outer: int = DEFAULT_MAX_OUTER,
    wake_length: float = DEFAULT_WAKE_LENGTH,
    wake_panels: int = DEFAULT_WAKE_PANELS,
    system: HessSmithSystem | None = None,
    previous: "NewtonSolution | None" = None,
    validate: bool = True,
) -> NewtonSolution:
    """Solve the viscous and inviscid problems simultaneously at one incidence.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alpha : float
        Angle of attack in **radians**.
    reynolds : float
        Reynolds number based on chord.
    n_crit : float, optional
        Amplification factor at transition for the e^N method. 9 is a quiet
        tunnel or free flight; 4 to 7 suits a small open-circuit tunnel.
    tolerance : float, optional
        Convergence tolerance on the infinity norm of the residual vector. The
        residuals are scaled to be dimensionless, so this is comparable across
        problems.
    max_iterations : int, optional
        Newton steps allowed per outer pass.
    max_outer : int, optional
        Outer passes allowed for the transition location to settle.
    wake_length : float, optional
        Wake length in chords.
    wake_panels : int, optional
        Number of wake panels.
    system : HessSmithSystem, optional
        A pre-factorised system, for sweeping incidence.
    previous : NewtonSolution, optional
        A solution at a neighbouring angle, used as the starting guess. It is
        interpolated onto this angle's station layout by arc length, so it need
        not have been solved on the same grid.
    validate : bool, optional
        If True (default), raise when the solve has not converged.

    Returns
    -------
    NewtonSolution

    Raises
    ------
    ConvergenceError
        If ``validate`` is set and the solve did not converge. The exception
        carries the iteration count and final residual, so a failure is never
        silent and never returns a plausible-looking number.

    Notes
    -----
    Two nested loops. The inner one is Newton's method on the full system of
    ``3 n`` equations, with a step limiter that keeps the thicknesses positive
    and a backtracking line search on the residual norm. The outer one updates
    the transition location, which is held fixed while Newton runs because it
    enters through a correlation rather than through the differential equations.

    The stagnation point is located once, from the inviscid solution, and held
    for the whole solve. It moves by well under one panel when the displacement
    effect is added, and re-locating it would mean rebuilding the station layout
    and the interaction matrix at every outer pass. See NOTES.md, A8.5.
    """
    if reynolds <= 0.0:
        raise ValidityRangeError(f"Reynolds number must be positive, got {reynolds}")
    if n_crit <= 0.0:
        raise ValidityRangeError(f"n_crit must be positive, got {n_crit}")

    if system is None:
        system = HessSmithSystem(airfoil)
    wake = build_wake(airfoil, alpha, length=wake_length, n_panels=wake_panels)
    inviscid = system.solve(alpha, validate=False)
    layout = build_layout(system, wake, inviscid)
    interaction = build_interaction(system, wake, layout, alpha)
    n = layout.n_stations

    state = (
        _initial_state(layout, interaction.ue_inviscid, reynolds, airfoil.te_gap)
        if previous is None
        else _remap_state(previous, layout)
    )

    left = np.concatenate(
        [np.arange(layout.side_slice(i).start, layout.side_slice(i).stop - 1)
         for i in range(3)]
    )
    right = left + 1

    # Estimate transition from the starting guess before the first Newton pass.
    #
    # Starting instead from "laminar everywhere" is the obvious thing to do and
    # it does not work. At Re = 3e6 a laminar layer carried to the trailing edge
    # separates long before it gets there, so the first pass is asked to solve a
    # state that has no solution, and the iterate it leaves behind is a worse
    # starting point than the one it was given. One cheap e^N pass on the
    # starting guess avoids the whole problem.
    ends = [float(layout.s[layout.side_slice(i)][-1]) for i in (0, 1)]
    seed = _build_problem(
        layout, interaction, reynolds, airfoil.te_gap,
        _turbulent_weights(layout, left, right, ends),
    )
    if previous is None:
        locations, causes = _transition_locations(state, seed, reynolds, n_crit)
    else:
        # Continuing from a neighbouring angle. Estimating transition as if the
        # state were laminar everywhere is wrong here and quietly ruinous: the
        # previous solution is turbulent over most of its length, so the
        # amplification integral over it barely grows, the estimate comes back
        # as "no transition", and the first Newton pass is handed a fully
        # laminar configuration that has no solution. The previous angle's own
        # transition position is the right starting point.
        locations = [
            float(np.clip(value, 0.0, end)) if np.isfinite(value) else end
            for value, end in zip(previous.transition_s, ends)
        ]
        causes = list(previous.transition_cause)
    history: list[float] = []
    residual = np.inf
    steps = 0
    outer = 0
    settled = False

    def newton(start: FloatArray, problem: _Problem) -> tuple[FloatArray, float, int, list[float]]:
        """Newton's method on the full system, at a fixed transition position."""
        current = start.copy()
        trace: list[float] = []
        norm = np.inf
        taken = 0
        for taken in range(1, max_iterations + 1):
            vector = _residuals(current.astype(np.complex128), problem).real
            norm = float(np.max(np.abs(vector)))
            trace.append(norm)
            if norm < tolerance:
                break
            delta = _log_step(current, _jacobian(current, problem), vector)
            fraction = 1.0
            accepted = False
            for _ in range(14):
                trial = current * np.exp(fraction * delta)
                trial_norm = float(
                    np.max(np.abs(_residuals(trial.astype(np.complex128), problem).real))
                )
                if np.isfinite(trial_norm) and trial_norm < norm:
                    accepted = True
                    break
                fraction *= 0.5
            if not accepted:
                # No step along the Newton direction reduces the residual.
                # Halving further would report a smaller step, not a better
                # answer, so stop and let the caller see what was reached.
                break
            current = current * np.exp(fraction * delta)
        return current, norm, taken, trace

    cold = state.copy()
    best_state, best_residual = state.copy(), np.inf
    visited: list[list[float]] = []
    span = [float(layout.s[layout.side_slice(i)][-1]) for i in (0, 1)]

    for outer in range(1, max_outer + 1):
        problem = _build_problem(
            layout, interaction, reynolds, airfoil.te_gap,
            _turbulent_weights(layout, left, right, locations),
        )

        trial_state, residual, steps, history = newton(state, problem)
        if residual < best_residual:
            best_state, best_residual = trial_state.copy(), residual
        if residual >= tolerance:
            # A failed pass leaves an iterate that is worse than the starting
            # guess, and updating the transition position from it feeds garbage
            # into the next pass — which is how this loop used to spiral. Retry
            # once from the cold start before believing the failure.
            trial_state, residual, steps, history = newton(cold, problem)
            if residual < best_residual:
                best_state, best_residual = trial_state.copy(), residual
        if residual >= tolerance:
            break
        state = trial_state

        new_locations, causes = _transition_locations(
            state, problem, reynolds, n_crit, locations
        )
        # Cap how far transition may travel in one pass. The Newton update for
        # the transition position extrapolates a growth rate, and an
        # extrapolation early in the solve can land the whole surface in the
        # laminar regime, which at high Reynolds number has no solution at all.
        capped: list[float] = []
        for side, (target, previous) in enumerate(zip(new_locations, locations)):
            limit = 0.25 * span[side]
            move = TRANSITION_RELAXATION * (target - previous)
            capped.append(
                float(np.clip(previous + np.clip(move, -limit, limit), 0.0, ends[side]))
            )
        moved = max(abs(a - b) for a, b in zip(capped, locations))
        # A transition position that returns to somewhere it has already been
        # is in a limit cycle, not drifting. The cycles that occur are small and
        # physically empty — two descriptions of the same flow — so once the
        # solution itself has converged, revisiting a position is convergence.
        cycled = any(
            max(abs(a - b) for a, b in zip(capped, seen)) < TRANSITION_TOLERANCE
            for seen in visited
        )
        visited.append(list(locations))
        locations = capped
        if moved < TRANSITION_TOLERANCE or cycled:
            settled = True
            break

    if not settled:
        # Report the best iterate reached rather than whatever the last failed
        # pass started from, so an unconverged result is at least the closest
        # this got — and is still flagged unconverged.
        state, residual = best_state, min(residual, best_residual)
    mass = state[2 * n :] * state[n : 2 * n]
    rates = interaction.derivative @ mass
    surface = layout.side < 2
    transpiration = np.zeros(system.n_panels)
    transpiration[layout.panel[surface]] = rates[surface]
    wake_strengths = np.zeros(wake.n_panels)
    wake_strengths[layout.panel[~surface]] = rates[~surface]

    from aerolab.viscous.wake import wake_influence

    panel = system.solve(
        alpha,
        transpiration=transpiration,
        external_velocity=wake_influence(wake, wake_strengths, system.control_points),
        validate=False,
    )

    result = NewtonSolution(
        panel=panel,
        layout=layout,
        theta=state[:n],
        delta_star=state[n : 2 * n],
        ue=state[2 * n :],
        reynolds=float(reynolds),
        transpiration=transpiration,
        wake_strengths=wake_strengths,
        transition_s=tuple(
            np.inf if value >= end - 1e-9 else float(value)
            for value, end in zip(locations, ends)
        ),
        transition_cause=(causes[0], causes[1]),
        iterations=steps,
        outer_iterations=outer,
        residual=residual,
        converged=bool(settled and residual < tolerance),
        tolerance=tolerance,
        history=np.array(history),
    )
    return result.check() if validate else result


def newton_polar(
    airfoil: Airfoil,
    alphas: FloatArray,
    reynolds: float,
    *,
    n_crit: float = DEFAULT_N_CRIT,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_outer: int = DEFAULT_MAX_OUTER,
    wake_length: float = DEFAULT_WAKE_LENGTH,
    wake_panels: int = DEFAULT_WAKE_PANELS,
) -> list[NewtonSolution]:
    """Sweep incidence, continuing each solve from the previous one.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alphas : ndarray
        Angles of attack in **radians**, in the order they should be marched.
    reynolds : float
        Reynolds number based on chord.
    n_crit, tolerance, max_iterations, max_outer, wake_length, wake_panels
        As for :func:`solve_newton`.

    Returns
    -------
    list of NewtonSolution
        One per angle, in the order given. Points that fail to converge are
        returned rather than raised, so a sweep that fails at the top of the
        curve still yields everything below it. Call ``check()`` for a
        guarantee.

    Notes
    -----
    Continuation matters less here than it did for the sequential method — a
    cold Newton start converges at most angles — but it still roughly halves the
    iteration count, and near the top of the lift curve it is what supplies a
    starting point close enough for Newton to find the solution at all.

    The station layout depends on where the stagnation point sits, so it changes
    with incidence and the state vector cannot always be carried across. When
    the length changes the next angle simply starts cold, which is handled
    silently because it is not an error.
    """
    system = HessSmithSystem(airfoil)
    results: list[NewtonSolution] = []
    guess: NewtonSolution | None = None

    for alpha in np.atleast_1d(np.asarray(alphas, dtype=np.float64)):
        result = solve_newton(
            airfoil, float(alpha), reynolds,
            n_crit=n_crit, tolerance=tolerance,
            max_iterations=max_iterations, max_outer=max_outer,
            wake_length=wake_length, wake_panels=wake_panels,
            system=system, previous=guess, validate=False,
        )
        if not result.converged and guess is not None:
            # The neighbouring solution was not a good enough starting point.
            # A cold start sometimes is, and costs one more solve.
            cold = solve_newton(
                airfoil, float(alpha), reynolds,
                n_crit=n_crit, tolerance=tolerance,
                max_iterations=max_iterations, max_outer=max_outer,
                wake_length=wake_length, wake_panels=wake_panels,
                system=system, previous=None, validate=False,
            )
            if cold.residual < result.residual:
                result = cold
        results.append(result)
        if result.converged:
            guess = result

    return results


# ---------------------------------------------------------------------------
# The boundary layer alone, on a prescribed edge velocity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrescribedLayer:
    """Integral boundary layer solved for a given edge velocity distribution.

    This is the coupled solver's boundary-layer half with the interaction
    removed, and it exists to be validated. Blasius, Falkner-Skan and Howarth
    all prescribe ``Ue`` and have known answers, so solving this problem is how
    the discretisation, the closure and the starting conditions are checked
    against exact results before any of them is asked to work inside a coupled
    solve. When a coupled answer is wrong, this says whether the boundary layer
    or the coupling is at fault — which is how the trailing-edge momentum defect
    was found.

    Attributes
    ----------
    s, ue : ndarray
        Arc length and prescribed edge velocity, as supplied.
    theta, delta_star : ndarray
        Momentum and displacement thickness, in chords.
    residual : float
        Infinity norm of the converged residual.
    converged : bool
        Whether the residual fell below the tolerance.
    """

    s: FloatArray
    ue: FloatArray
    theta: FloatArray
    delta_star: FloatArray
    reynolds: float
    residual: float
    converged: bool
    iterations: int

    @property
    def shape_factor(self) -> FloatArray:
        """``H = delta*/theta``."""
        return self.delta_star / self.theta

    @property
    def reynolds_theta(self) -> FloatArray:
        """``Re_theta``, based on momentum thickness and edge velocity."""
        return self.reynolds * self.ue * self.theta

    @property
    def cf(self) -> FloatArray:
        """Laminar skin friction on the **local edge** dynamic pressure."""
        from aerolab.viscous.closure import laminar_cf_reynolds_theta

        return 2.0 * laminar_cf_reynolds_theta(self.shape_factor) / self.reynolds_theta


def solve_prescribed(
    s: FloatArray,
    ue: FloatArray,
    reynolds: float,
    *,
    theta_initial: float | None = None,
    shape_initial: float | None = None,
    transition_s: float = np.inf,
    wall: bool = True,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    validate: bool = True,
) -> PrescribedLayer:
    """Solve the integral boundary layer for a prescribed edge velocity.

    Parameters
    ----------
    s : ndarray
        Arc length from the start of the layer, strictly increasing, in chords.
    ue : ndarray
        Edge velocity at each station, non-dimensionalised by freestream speed.
        Must be positive everywhere.
    reynolds : float
        Reynolds number based on chord, so ``Re_theta = Re * ue * theta``.
    theta_initial, shape_initial : float, optional
        Momentum thickness and shape factor at the first station. Give both to
        start from a known profile, as the Blasius and Falkner-Skan checks do.
        Omit both to use the exact plane-stagnation condition.
    transition_s : float, optional
        Arc length of transition. The default leaves the layer laminar.
    wall : bool, optional
        False for a wake, where skin friction is zero.
    tolerance, max_iterations : optional
        Newton controls.
    validate : bool, optional
        If True (default), raise when the solve has not converged.

    Returns
    -------
    PrescribedLayer

    Raises
    ------
    ConvergenceError
        If ``validate`` is set and Newton did not converge.
    ValidityRangeError
        If ``s`` is not increasing, ``ue`` is not positive, or exactly one of
        ``theta_initial`` and ``shape_initial`` is given.

    Notes
    -----
    This problem keeps the Goldstein singularity that the coupled solver
    removes, because ``Ue`` is prescribed rather than solved for. That is not a
    defect here but a feature: failing to converge at laminar separation is the
    correct behaviour for the direct problem, and observing it is evidence the
    discretisation is faithful. On Howarth's linearly retarded flow the residual
    stalls near ``H = 4.04`` and goes no further, which is the singularity, and
    the coupled solver passes straight through the same condition.
    """
    s = np.asarray(s, dtype=np.float64)
    ue = np.asarray(ue, dtype=np.float64)
    if s.ndim != 1 or s.shape != ue.shape:
        raise ValidityRangeError("s and ue must be one-dimensional and the same length")
    if np.any(np.diff(s) <= 0.0):
        raise ValidityRangeError("s must be strictly increasing")
    if np.any(ue <= 0.0):
        raise ValidityRangeError(
            "the prescribed edge velocity must be positive everywhere; a zero "
            "makes Re_theta zero and every closure relation singular"
        )
    if (theta_initial is None) != (shape_initial is None):
        raise ValidityRangeError("give both theta_initial and shape_initial, or neither")

    n = s.size
    spacing = np.diff(s)
    left = np.arange(n - 1)
    right = left + 1
    turbulent = np.clip((s[right] - transition_s) / np.maximum(spacing, 1e-15), 0.0, 1.0)
    wall_flag = np.full(n - 1, 1.0 if wall else 0.0)

    if theta_initial is None:
        gradient = float((_derivative_matrix(s) @ ue)[0])
        start_theta = float(
            np.sqrt(max(LAMBDA_STAGNATION / (reynolds * max(gradient, 1e-12)), 1e-16))
        )
        start_shape = H_STAGNATION
    else:
        start_theta, start_shape = float(theta_initial), float(shape_initial)

    integral = np.concatenate(
        [[0.0], np.cumsum(0.5 * (ue[1:] ** 5 + ue[:-1] ** 5) * spacing)]
    )
    theta = np.sqrt(
        np.maximum(
            start_theta**2 * (ue[0] / ue) ** 6 + 0.45 * integral / (reynolds * ue**6),
            1e-16,
        )
    )
    state = np.concatenate([theta, start_shape * theta])

    def residuals(vector: ComplexArray) -> ComplexArray:
        th, ds_ = vector[:n], vector[n:]
        momentum, shape = _interval_residuals(
            th[left], th[right], ds_[left], ds_[right],
            ue[left].astype(vector.dtype), ue[right].astype(vector.dtype),
            spacing, turbulent, wall_flag, reynolds,
        )
        out = np.zeros(2 * n, dtype=vector.dtype)
        out[right] = momentum
        out[n + right] = shape
        out[0] = th[0] / start_theta - 1.0
        out[n] = ds_[0] / th[0] / start_shape - 1.0
        return out

    step = 1e-30
    residual = np.inf
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        vector = residuals(state.astype(np.complex128)).real
        residual = float(np.max(np.abs(vector)))
        if residual < tolerance:
            break
        jac = np.zeros((2 * n, 2 * n))
        for column in range(2 * n):
            probe = state.astype(np.complex128)
            probe[column] += 1j * step
            jac[:, column] = residuals(probe).imag / step
        delta = _log_step(state, jac, vector)
        fraction = 1.0
        for _ in range(14):
            trial = state * np.exp(fraction * delta)
            trial_norm = float(np.max(np.abs(residuals(trial.astype(np.complex128)).real)))
            if np.isfinite(trial_norm) and trial_norm < residual:
                break
            fraction *= 0.5
        state = state * np.exp(fraction * delta)

    layer = PrescribedLayer(
        s=s, ue=ue, theta=state[:n], delta_star=state[n:], reynolds=float(reynolds),
        residual=residual, converged=residual < tolerance, iterations=iterations,
    )
    if validate and not layer.converged:
        raise ConvergenceError(
            "the prescribed-Ue boundary layer did not converge",
            iterations=iterations, residual=residual, tolerance=tolerance,
        )
    return layer
