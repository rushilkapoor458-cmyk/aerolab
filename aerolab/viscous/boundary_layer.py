"""Integral boundary-layer solver: Thwaites, then transition, then Head.

Marches each surface from the stagnation point to the trailing edge, using the
inviscid edge velocity from the Phase 2 panel solution. This is a **one-way**
calculation: the boundary layer reads the inviscid solution and does not feed
back into it. That is the defining limitation of the phase and it is why the
predicted drag is trustworthy only while the flow is attached and the
displacement effect is small. Phase 4 closes the loop.

Sequence on each surface
------------------------
1. **Thwaites** from the stagnation point, giving ``theta`` by quadrature rather
   than by marching an ODE.
2. **Transition**, by Michel's criterion or an e^N envelope method.
3. **Head's entrainment method** with Ludwieg-Tillmann skin friction, marched as
   a two-equation ODE system to the trailing edge or to separation.
4. **Squire-Young** at the trailing edge for profile drag.

Conventions
-----------
``s`` is surface distance from the stagnation point, non-dimensionalised by
chord and increasing downstream on both surfaces. ``Ue`` is non-dimensionalised
by freestream speed. ``theta`` and ``delta*`` are in chords. ``cf`` uses the
**local edge** dynamic pressure. ``Re`` with no subscript is based on chord.
Angles play no part in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import cumulative_trapezoid, solve_ivp
from scipy.interpolate import CubicSpline

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.repanel import clustered_fractions
from aerolab.inviscid.hess_smith import PanelSolution
from aerolab.viscous import closure
from aerolab.viscous.transition import (
    DEFAULT_N_CRIT,
    TransitionMethod,
    TransitionResult,
    predict_transition,
)

FloatArray = NDArray[np.float64]
Surface = Literal["upper", "lower"]

__all__ = [
    "EdgeDistribution",
    "SurfaceBoundaryLayer",
    "BoundaryLayerSolution",
    "edge_distributions",
    "solve_boundary_layer",
]

#: Shape factor assumed at the start of the turbulent run.
#:
#: Momentum thickness is continuous through transition; the shape factor is not,
#: and an integral method has no way to resolve the transition region. 1.4 is the
#: conventional value and is what Cebeci and Bradshaw use.
#:
#: It is not a negligible choice. Varying it from 1.3 to 1.5 moves the NACA 0012
#: profile drag at Re = 3e6 by 4%, comparable to the width of the whole
#: acceptance band. That sensitivity is measured in the tests rather than
#: assumed away, and it is one of the reasons an uncoupled calculation cannot
#: be pushed much below 5% accuracy. See NOTES.md, L3.4.
TURBULENT_START_H = 1.4

#: Default number of stations per surface.
DEFAULT_STATIONS = 1000

#: Separation forward of this station invalidates the profile drag.
#:
#: Every uncoupled solution separates somewhere in the last one or two percent
#: of chord, because the inviscid edge velocity approaches a stagnation point at
#: the trailing edge and no boundary layer survives that (see NOTES.md, L3.1).
#: Treating it as a failure would make every result an error. Separation forward
#: of this station is a different matter: it means the section is genuinely
#: stalling and Squire-Young no longer describes the wake.
DEFAULT_SEPARATION_LIMIT_X = 0.95


@dataclass(frozen=True)
class EdgeDistribution:
    """Inviscid edge velocity along one surface, from the stagnation point.

    Attributes
    ----------
    surface : {"upper", "lower"}
        Which surface.
    s : ndarray
        Surface distance from the stagnation point, in chords, increasing.
    x : ndarray
        Chordwise station ``x/c`` at each point, for reporting.
    ue : ndarray
        Edge speed, non-dimensionalised by freestream speed. Non-negative, zero
        at the stagnation point.
    stagnation_s : float
        Arc length of the stagnation point measured along the **airfoil
        contour**, not along this surface. Phase 4 needs it to map a
        transpiration velocity computed on these stations back onto panels.
    stagnation_index : int
        Index of the last panel before the stagnation point.
    """

    surface: Surface
    s: FloatArray
    x: FloatArray
    ue: FloatArray
    stagnation_s: float = 0.0
    stagnation_index: int = 0


@dataclass(frozen=True)
class SurfaceBoundaryLayer:
    """Boundary-layer development along one surface.

    Attributes
    ----------
    surface : {"upper", "lower"}
        Which surface.
    s, x, ue : ndarray
        Station arrays, as in :class:`EdgeDistribution`.
    theta, delta_star : ndarray
        Momentum and displacement thickness, in chords.
    shape_factor : ndarray
        ``H = delta*/theta``.
    cf : ndarray
        Skin friction on the local edge dynamic pressure.
    re_theta : ndarray
        Momentum-thickness Reynolds number.
    turbulent : ndarray of bool
        Whether each station is in the turbulent run.
    transition : TransitionResult
        Where and how transition was predicted.
    laminar_separation_x, turbulent_separation_x : float or None
        Chordwise stations of separation, if it occurred.
    reached_trailing_edge : bool
        False if the march stopped early at separation.
    s_total : float
        Full surface arc length from the stagnation point to the trailing edge,
        in chords. Retained even when the arrays are truncated at separation,
        because Phase 4 must extrapolate the displacement thickness over the
        remaining stretch.
    stagnation_s, stagnation_index : float, int
        Stagnation location, carried through from the edge distribution.
    """

    surface: Surface
    s: FloatArray
    x: FloatArray
    ue: FloatArray
    theta: FloatArray
    delta_star: FloatArray
    shape_factor: FloatArray
    cf: FloatArray
    re_theta: FloatArray
    turbulent: NDArray[np.bool_]
    transition: TransitionResult
    laminar_separation_x: float | None
    turbulent_separation_x: float | None
    reached_trailing_edge: bool
    s_total: float = 0.0
    stagnation_s: float = 0.0
    stagnation_index: int = 0

    @property
    def transition_x(self) -> float | None:
        """Chordwise station of transition, or None if the run stayed laminar."""
        if self.transition.index is None:
            return None
        return float(self.x[self.transition.index])

    @cached_property
    def squire_young_drag(self) -> float:
        """Profile-drag contribution of this surface.

        Returns
        -------
        float
            ``2 * theta_te * Ue_te**((H_te + 5)/2)``, the far-wake momentum
            thickness scaled to freestream conditions, doubled to form a drag
            coefficient.

        Notes
        -----
        Squire-Young relates the momentum thickness far downstream to conditions
        at the trailing edge by assuming the wake relaxes towards ``H = 1``
        under a specific pressure recovery. It is only meaningful for an
        attached boundary layer arriving at the trailing edge; if this surface
        separated, the value returned is a lower bound and
        :attr:`reached_trailing_edge` is False.
        """
        return float(
            2.0
            * self.theta[-1]
            * self.ue[-1] ** ((self.shape_factor[-1] + 5.0) / 2.0)
        )

    def __repr__(self) -> str:
        transition = (
            f"xtr={self.transition_x:.4f}"
            if self.transition_x is not None
            else "no transition"
        )
        return (
            f"<SurfaceBoundaryLayer {self.surface}: {transition}, "
            f"theta_te={self.theta[-1]:.5f}c, H_te={self.shape_factor[-1]:.3f}, "
            f"{'attached' if self.reached_trailing_edge else 'SEPARATED'}>"
        )


@dataclass(frozen=True)
class BoundaryLayerSolution:
    """Boundary layers on both surfaces, and the profile drag they imply.

    Attributes
    ----------
    upper, lower : SurfaceBoundaryLayer
        The two surface solutions.
    reynolds : float
        Chord Reynolds number.
    alpha : float
        Angle of attack in **radians**, carried through from the panel solution.
    """

    upper: SurfaceBoundaryLayer
    lower: SurfaceBoundaryLayer
    reynolds: float
    alpha: float

    @property
    def surfaces(self) -> tuple[SurfaceBoundaryLayer, SurfaceBoundaryLayer]:
        """Both surfaces, upper first."""
        return self.upper, self.lower

    @cached_property
    def cd_profile(self) -> float:
        """Profile drag coefficient, from Squire-Young on both surfaces.

        Returns
        -------
        float
            Sum of the two surface contributions, non-dimensionalised by chord
            and freestream dynamic pressure.

        Notes
        -----
        This is **pressure plus friction drag of the section in two-dimensional
        attached flow**. It excludes induced drag, which is three-dimensional and
        belongs to Phase 6, and it excludes any base drag from a blunt trailing
        edge, which potential flow cannot supply (see NOTES.md, L2.1).
        """
        return sum(surface.squire_young_drag for surface in self.surfaces)

    @property
    def attached(self) -> bool:
        """Whether both surfaces reached the trailing edge without separating.

        Almost always False, and that is expected rather than alarming: the
        inviscid edge velocity approaches a stagnation point at the trailing
        edge, so an uncoupled boundary layer separates in the last percent or so
        of chord on essentially every case. Use :attr:`separation_is_significant`
        to distinguish that artefact from a section that is genuinely stalling.
        """
        return all(surface.reached_trailing_edge for surface in self.surfaces)

    def separation_is_significant(
        self, limit_x: float = DEFAULT_SEPARATION_LIMIT_X
    ) -> bool:
        """Whether either surface separated forward of ``limit_x``."""
        return any(
            surface.turbulent_separation_x is not None
            and surface.turbulent_separation_x < limit_x
            for surface in self.surfaces
        )

    def check(
        self, limit_x: float = DEFAULT_SEPARATION_LIMIT_X
    ) -> "BoundaryLayerSolution":
        """Raise if either surface separated forward of ``limit_x``.

        Parameters
        ----------
        limit_x : float, optional
            Chordwise station forward of which separation is treated as real
            rather than as the trailing-edge artefact.

        Raises
        ------
        ValidityRangeError
            If a surface separated forward of ``limit_x``. Squire-Young assumes
            an attached layer arriving at the trailing edge, so the drag would
            be a plausible-looking underestimate rather than a prediction.

        Notes
        -----
        Separation *aft* of ``limit_x`` is reported through
        :attr:`SurfaceBoundaryLayer.turbulent_separation_x` but does not raise.
        Drawing the line somewhere is unavoidable while the calculation is
        uncoupled; the alternative is either to raise on every case or to raise
        on none.
        """
        for surface in self.surfaces:
            station = surface.turbulent_separation_x
            if station is not None and station < limit_x:
                raise ValidityRangeError(
                    f"the {surface.surface} surface separated at x/c = "
                    f"{station:.4f}, forward of the limit {limit_x:.2f}. "
                    "Squire-Young assumes an attached boundary layer at the "
                    "trailing edge, so the profile drag would be an "
                    "underestimate of unknown size. Pass validate=False to "
                    "inspect the solution anyway."
                )
        return self

    def __repr__(self) -> str:
        separation = (
            "attached"
            if self.attached
            else f"sep at x/c={min(s.turbulent_separation_x for s in self.surfaces if s.turbulent_separation_x is not None):.3f}"
        )
        return (
            f"<BoundaryLayerSolution Re={self.reynolds:.3g}, "
            f"alpha={np.rad2deg(self.alpha):.2f} deg, "
            f"Cd={self.cd_profile:.5f}, {separation}>"
        )


# ---------------------------------------------------------------------------
# Edge velocity extraction
# ---------------------------------------------------------------------------


def edge_distributions(
    solution: PanelSolution, stations: int = DEFAULT_STATIONS
) -> tuple[EdgeDistribution, EdgeDistribution]:
    """Split the panel solution into two edge-velocity distributions.

    Parameters
    ----------
    solution : PanelSolution
        Converged inviscid solution.
    stations : int, optional
        Number of stations per surface after resampling.

    Returns
    -------
    upper, lower : EdgeDistribution
        Each running from the stagnation point downstream.

    Raises
    ------
    ValidityRangeError
        If no stagnation point can be found on the surface panels.

    Notes
    -----
    The stagnation point is located by the sign change of the tangential
    velocity. In Selig order the contour is traversed forward along the upper
    surface, so the flow runs *against* the traversal there and ``v_tangential``
    is negative; on the lower surface it runs with the traversal and is
    positive. The single negative-to-positive crossing near the leading edge is
    therefore the stagnation point, and its location is refined by linear
    interpolation between the bracketing panel midpoints.

    Stations are clustered towards the stagnation point, where the edge velocity
    rises from zero and the Thwaites integrand changes fastest.

    A base panel, if the section has one, is excluded: it belongs to neither
    surface and the flow over it is not a boundary layer in any useful sense.
    """
    system = solution.system
    n_surface = system.airfoil.n_points - 1
    v_tangential = solution.v_tangential[:n_surface]

    arc = system.airfoil.arc_length
    s_control = 0.5 * (arc[:-1] + arc[1:])[:n_surface]
    x_control = system.control_points[:n_surface, 0]

    crossings = np.nonzero(
        (v_tangential[:-1] < 0.0) & (v_tangential[1:] >= 0.0)
    )[0]
    if crossings.size == 0:
        raise ValidityRangeError(
            "no stagnation point found: the tangential velocity never changes "
            "from negative to positive along the surface. The angle of attack "
            "may be far outside the range where attached flow is meaningful."
        )
    index = int(crossings[0])

    lower_v, upper_v = v_tangential[index], v_tangential[index + 1]
    fraction = -lower_v / (upper_v - lower_v)
    s_stagnation = float(
        s_control[index] + fraction * (s_control[index + 1] - s_control[index])
    )

    def build(
        name: Surface, order: slice | NDArray[np.intp], sign: float
    ) -> EdgeDistribution:
        s_raw = np.abs(s_control[order] - s_stagnation)
        ue_raw = sign * v_tangential[order]
        x_raw = x_control[order]

        s_raw = np.concatenate([[0.0], s_raw])
        ue_raw = np.concatenate([[0.0], ue_raw])
        x_raw = np.concatenate([[x_raw[0]], x_raw])

        keep = np.concatenate([[True], np.diff(s_raw) > 1e-12])
        s_raw, ue_raw, x_raw = s_raw[keep], ue_raw[keep], x_raw[keep]

        # Cosine clustering at *both* ends. The stagnation end needs it because
        # the Thwaites integrand changes fastest there. The trailing-edge end
        # needs it because the inviscid solution approaches a stagnation point
        # at a finite-angle trailing edge, so dUe/ds grows without bound over
        # the last one percent of chord. Clustering only at the stagnation end
        # left the drag wandering by 2.3% and non-monotonically with station
        # count; clustering at both ends converges it cleanly to within 0.9%.
        grid = s_raw[-1] * clustered_fractions(stations, 0.5, 0.5)
        ue_spline = CubicSpline(s_raw, ue_raw)
        x_spline = CubicSpline(s_raw, x_raw)
        return EdgeDistribution(
            surface=name,
            s=grid,
            x=x_spline(grid),
            ue=np.clip(ue_spline(grid), 0.0, None),
            stagnation_s=s_stagnation,
            stagnation_index=index,
        )

    upper = build("upper", np.arange(index, -1, -1), -1.0)
    lower = build("lower", np.arange(index + 1, n_surface), 1.0)
    return upper, lower


# ---------------------------------------------------------------------------
# Laminar run
# ---------------------------------------------------------------------------


def _thwaites(
    s: FloatArray, ue: FloatArray, due_ds: FloatArray, reynolds: float
) -> tuple[FloatArray, FloatArray]:
    """Momentum thickness and Thwaites' parameter along a laminar run.

    Returns ``(theta, lambda_)``, both on the supplied stations.

    The quadrature ``theta**2 = 0.45/(Re Ue**6) * integral(Ue**5 ds)`` is
    indeterminate at the stagnation point, where both numerator and denominator
    vanish. Its limit for a linear ``Ue = k s`` is ``theta**2 = 0.075/(Re k)``,
    which is used for the first station; that limit also fixes
    ``lambda = 0.075`` there, the classical stagnation value.

    The integral is evaluated by Gauss-Legendre quadrature on each interval,
    with the integrand taken from a spline of ``Ue`` and raised to the fifth
    power at the quadrature nodes. Two cheaper schemes both fail near the
    stagnation point, where ``Ue ~ k s`` makes the integrand behave like
    ``s**5``:

    - the trapezoid rule overestimates the first interval threefold,
      ``h**6/2`` against the exact ``h**6/6``;
    - splining ``Ue**5`` and integrating *that* spline is worse still, because a
      cubic through a quintic with a fifth-order zero oscillates at the
      boundary. It put ``lambda = 1.06`` at the second station against the
      correct 0.075.

    Since ``theta**2`` is the *ratio* of this integral to ``Ue**6``, both errors
    land directly on ``lambda``, exactly where transition prediction reads the
    shape factor. Splining ``Ue`` itself is safe — it is smooth and very nearly
    linear there — and eight-node quadrature then integrates its fifth power
    essentially exactly.
    """
    ue_spline = CubicSpline(s, ue)
    nodes, weights = np.polynomial.legendre.leggauss(8)
    lower, upper = s[:-1], s[1:]
    half = 0.5 * (upper - lower)
    middle = 0.5 * (upper + lower)
    samples = middle[:, None] + half[:, None] * nodes[None, :]
    integral = np.concatenate([[0.0], np.cumsum(half * (ue_spline(samples) ** 5 @ weights))])
    theta_squared = np.empty_like(s)

    with np.errstate(divide="ignore", invalid="ignore"):
        theta_squared[1:] = 0.45 * integral[1:] / (reynolds * ue[1:] ** 6)

    slope = due_ds[0]
    if ue[0] > 1e-12:
        # The run starts at finite velocity — a flat plate, or any surface that
        # does not begin at a stagnation point. The layer starts with zero
        # thickness and the sign of the gradient is irrelevant, which is what
        # makes Howarth's decelerating flow representable.
        theta_squared[0] = 0.0
    elif slope > 0.0:
        theta_squared[0] = 0.075 / (reynolds * slope)
    else:
        raise ValidityRangeError(
            f"the edge velocity starts at zero but is not accelerating "
            f"(dUe/ds = {slope:.4e}). A boundary layer beginning at a "
            "stagnation point must see an accelerating flow; this usually means "
            "the stagnation point was mislocated."
        )

    bad = ~np.isfinite(theta_squared) | (theta_squared < 0.0)
    if np.any(bad[1:]):
        first = int(np.argmax(bad[1:])) + 1
        raise ValidityRangeError(
            f"Thwaites' quadrature produced a non-physical momentum thickness at "
            f"s/c = {s[first]:.5f}, where the edge velocity is {ue[first]:.3e}. "
            "This normally means the inviscid edge velocity has a zero away from "
            "the stagnation point."
        )

    theta = np.sqrt(theta_squared)
    return theta, reynolds * theta_squared * due_ds


# ---------------------------------------------------------------------------
# Turbulent run
# ---------------------------------------------------------------------------


def _march_head(
    s_start: float,
    theta_start: float,
    s_end: float,
    ue_spline: CubicSpline,
    due_ds_spline: CubicSpline,
    reynolds: float,
    separation_h: float,
) -> tuple[CubicSpline | None, float | None]:
    """Integrate Head's entrainment method downstream.

    Returns the dense solution and the arc length at separation, if any.

    The state is ``[theta, H1]``. Head's two equations are the momentum integral

    .. math:: \\frac{d\\theta}{ds} = \\frac{c_f}{2}
              - (H + 2)\\frac{\\theta}{U_e}\\frac{dU_e}{ds}

    and the entrainment equation ``d(theta*H1)/ds = F(H1)``, rearranged for
    ``dH1/ds``. Separation is detected as a terminal event rather than by
    inspecting the result afterwards, so the integrator stops at the crossing
    instead of marching into a region where the correlations are invalid.
    """
    h1_start = float(closure.head_h1_from_h(np.array([TURBULENT_START_H]))[0])

    def derivatives(s: float, state: FloatArray) -> FloatArray:
        theta, h1 = state
        theta = max(theta, 1e-12)
        h1 = max(h1, 3.3 + 1e-9)
        h = float(closure.head_h_from_h1(np.array([h1]))[0])
        h = float(np.clip(h, 1.0, 3.0))
        ue = max(float(ue_spline(s)), 1e-9)
        re_theta = max(reynolds * ue * theta, 100.0)
        cf = float(closure.ludwieg_tillmann_cf(np.array([h]), np.array([re_theta]))[0])
        dtheta = 0.5 * cf - (h + 2.0) * theta / ue * float(due_ds_spline(s))
        entrainment = float(closure.head_entrainment(np.array([h1]))[0])
        return np.array([dtheta, (entrainment - h1 * dtheta) / theta])

    def separated(s: float, state: FloatArray) -> float:
        h1 = max(state[1], 3.3 + 1e-9)
        h = float(closure.head_h_from_h1(np.array([h1]))[0])
        return separation_h - h

    separated.terminal = True
    separated.direction = -1.0

    result = solve_ivp(
        derivatives,
        (s_start, s_end),
        np.array([theta_start, h1_start]),
        method="RK45",
        events=separated,
        dense_output=True,
        rtol=1e-8,
        atol=1e-12,
        max_step=(s_end - s_start) / 40.0,
    )
    if not result.success:
        raise ConvergenceError(
            f"Head's method failed to integrate the turbulent run: {result.message}",
            iterations=int(result.nfev),
            residual=float("nan"),
            tolerance=1e-8,
        )

    separation_s = None
    if result.t_events[0].size > 0:
        separation_s = float(result.t_events[0][0])
    return result.sol, separation_s


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _solve_surface(
    edge: EdgeDistribution,
    reynolds: float,
    method: TransitionMethod,
    n_crit: float,
    separation_h: float,
    forced_transition_x: float | None,
) -> SurfaceBoundaryLayer:
    """Solve one surface from the stagnation point to the trailing edge."""
    s, ue = edge.s, edge.ue
    s_total = float(s[-1])
    ue_spline = CubicSpline(s, ue)
    due_ds_spline = ue_spline.derivative()
    due_ds = due_ds_spline(s)

    theta, lambda_ = _thwaites(s, ue, due_ds, reynolds)
    clipped = np.clip(lambda_, closure.LAMBDA_MIN, closure.LAMBDA_MAX)
    shape = closure.thwaites_shape_factor(clipped)
    shear = closure.thwaites_shear(clipped)
    re_theta = reynolds * ue * theta
    with np.errstate(divide="ignore", invalid="ignore"):
        cf = np.where(re_theta > 0.0, 2.0 * shear / np.maximum(re_theta, 1e-12), 0.0)

    separated = np.nonzero(lambda_ <= closure.LAMBDA_SEPARATION)[0]
    laminar_separation_index = int(separated[0]) if separated.size else None
    laminar_separation_x = (
        float(edge.x[laminar_separation_index])
        if laminar_separation_index is not None
        else None
    )

    limit = laminar_separation_index if laminar_separation_index is not None else s.size
    transition = predict_transition(
        s[:limit], ue[:limit], theta[:limit], shape[:limit], reynolds,
        method=method, n_crit=n_crit,
    )

    if forced_transition_x is not None:
        forced = np.nonzero(edge.x >= forced_transition_x)[0]
        if forced.size:
            index = int(forced[0])
            transition = TransitionResult(
                True, float(s[index]), index, "forced", transition.n_factor
            )

    if not transition.occurred and laminar_separation_index is not None:
        # A laminar layer that separates before transition forms a separation
        # bubble; transition happens inside it and the layer reattaches
        # turbulent. An integral method cannot resolve the bubble, so the short-
        # bubble assumption is used: transition is placed at separation and the
        # bubble's own drag is neglected. See NOTES.md, L3.3.
        transition = TransitionResult(
            True,
            float(s[laminar_separation_index]),
            laminar_separation_index,
            "laminar-separation",
            transition.n_factor,
        )

    turbulent = np.zeros_like(s, dtype=bool)
    turbulent_separation_x: float | None = None
    reached_te = True

    if transition.occurred:
        index = int(transition.index)
        turbulent[index:] = True
        dense, separation_s = _march_head(
            float(s[index]), float(theta[index]), float(s[-1]),
            ue_spline, due_ds_spline, reynolds, separation_h,
        )
        end = float(separation_s) if separation_s is not None else float(s[-1])
        active = turbulent & (s <= end)
        state = dense(s[active])
        theta = theta.copy()
        shape = shape.copy()
        cf = cf.copy()
        theta[active] = state[0]
        h1 = np.maximum(state[1], 3.3 + 1e-9)
        shape[active] = np.clip(closure.head_h_from_h1(h1), 1.0, 3.0)
        re_theta = reynolds * ue * theta
        cf[active] = closure.ludwieg_tillmann_cf(
            shape[active], np.maximum(re_theta[active], 100.0)
        )

        if separation_s is not None:
            reached_te = False
            beyond = np.nonzero(s > end)[0]
            cut = int(beyond[0]) if beyond.size else s.size
            turbulent_separation_x = float(edge.x[min(cut, s.size - 1)])
            s, ue, theta, shape, cf, re_theta, turbulent = (
                a[:cut] for a in (s, ue, theta, shape, cf, re_theta, turbulent)
            )
            # Rebuild by keyword. Constructing this positionally silently drops
            # stagnation_s and stagnation_index back to their defaults, and
            # since only separated surfaces take this branch, the loss shows up
            # nowhere until Phase 4 tries to map a transpiration velocity back
            # onto panels. See NOTES.md, D4.1.
            edge = EdgeDistribution(
                surface=edge.surface,
                s=s,
                x=edge.x[:cut],
                ue=ue,
                stagnation_s=edge.stagnation_s,
                stagnation_index=edge.stagnation_index,
            )

    return SurfaceBoundaryLayer(
        surface=edge.surface,
        s=s,
        x=edge.x,
        ue=ue,
        theta=theta,
        delta_star=shape * theta,
        shape_factor=shape,
        cf=cf,
        re_theta=re_theta,
        turbulent=turbulent,
        transition=transition,
        laminar_separation_x=laminar_separation_x,
        turbulent_separation_x=turbulent_separation_x,
        reached_trailing_edge=reached_te,
        s_total=s_total,
        stagnation_s=edge.stagnation_s,
        stagnation_index=edge.stagnation_index,
    )


def solve_boundary_layer(
    solution: PanelSolution,
    reynolds: float,
    *,
    method: TransitionMethod = "en",
    n_crit: float = DEFAULT_N_CRIT,
    separation_h: float = closure.TURBULENT_SEPARATION_H,
    stations: int = DEFAULT_STATIONS,
    forced_transition_x: tuple[float | None, float | None] = (None, None),
    separation_limit_x: float = DEFAULT_SEPARATION_LIMIT_X,
    validate: bool = True,
) -> BoundaryLayerSolution:
    """Solve the boundary layer on both surfaces of an inviscid solution.

    Parameters
    ----------
    solution : PanelSolution
        Converged inviscid solution from Phase 2.
    reynolds : float
        Reynolds number based on **chord**.
    method : {"en", "michel"}, optional
        Transition criterion.
    n_crit : float, optional
        Amplification factor at transition for the e^N method. 9 is a
        low-turbulence tunnel or free flight; use 4 to 7 for a small
        open-circuit tunnel.
    separation_h : float, optional
        Shape factor taken to indicate turbulent separation.
    stations : int, optional
        Stations per surface.
    forced_transition_x : tuple, optional
        ``(upper, lower)`` chordwise stations at which to trip the boundary
        layer, or None to let the criterion decide. Use this to model a trip
        strip.
    separation_limit_x : float, optional
        Separation forward of this station is treated as real and invalidates
        the drag; separation aft of it is the trailing-edge artefact and is only
        reported.
    validate : bool, optional
        If True (default), raise when a surface separates forward of
        ``separation_limit_x``, because the drag would then be an underestimate
        of unknown size.

    Returns
    -------
    BoundaryLayerSolution

    Raises
    ------
    ValidityRangeError
        If no stagnation point is found, or if ``validate`` is set and a surface
        separates before the trailing edge.
    ConvergenceError
        If the turbulent march fails to integrate.

    Notes
    -----
    The edge velocity comes straight from the inviscid solution with no
    displacement correction, so this over-predicts the edge velocity slightly
    and therefore under-predicts the drag. The error grows with angle of attack
    and is the reason Phase 4 exists.
    """
    if reynolds <= 0.0:
        raise ValidityRangeError(f"Reynolds number must be positive, got {reynolds}")

    upper_edge, lower_edge = edge_distributions(solution, stations)
    surfaces = [
        _solve_surface(edge, reynolds, method, n_crit, separation_h, forced)
        for edge, forced in zip((upper_edge, lower_edge), forced_transition_x)
    ]

    result = BoundaryLayerSolution(
        upper=surfaces[0],
        lower=surfaces[1],
        reynolds=float(reynolds),
        alpha=float(solution.alpha),
    )
    return result.check(separation_limit_x) if validate else result
