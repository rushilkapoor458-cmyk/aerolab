"""Viscous-inviscid coupling by transpiration.

The boundary layer displaces the outer flow. Rather than solving the outer flow
over a thickened body, the displacement is represented by blowing mass out
through the original surface at

.. math:: v_n = \\frac{d}{ds}\\left(U_e \\delta^*\\right)

which is added to the panel sources as a normal-velocity boundary condition.
The two solvers are then iterated: inviscid gives ``Ue``, the boundary layer
gives ``delta*``, the transpiration updates the inviscid problem, and round
again, under-relaxed.

Why this earns its place
------------------------
Uncoupled, the lift curve is a straight line for ever. Coupled, the growing
displacement thickness near the trailing edge progressively unloads the aft
section, the lift slope falls away, and the curve turns over — a stall
prediction rather than an extrapolation.

What it cannot do
-----------------
This is **direct** coupling: the boundary layer is solved for a prescribed edge
velocity. That formulation has a singularity at separation (Goldstein), so it
becomes stiff exactly where it is most interesting. Under-relaxation and
continuation in angle of attack get it through trailing-edge stall, but the
method cannot follow a lift curve past the peak into deep stall, and it does not
try. XFOIL avoids this by solving the two systems simultaneously with a Newton
method, which is a different and much larger piece of machinery. See NOTES.md,
L4.1.

Conventions
-----------
``alpha`` is in **radians**. ``v_n`` is non-dimensionalised by freestream speed
and is positive **outward**. Lengths are in chords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.airfoil import Airfoil
from aerolab.inviscid.hess_smith import HessSmithSystem, PanelSolution
from aerolab.viscous.boundary_layer import (
    DEFAULT_STATIONS,
    BoundaryLayerSolution,
    SurfaceBoundaryLayer,
    solve_boundary_layer,
)
from aerolab.viscous.transition import DEFAULT_N_CRIT, TransitionMethod
from aerolab.viscous.wake import (
    DEFAULT_WAKE_LENGTH,
    DEFAULT_WAKE_PANELS,
    Wake,
    WakeBoundaryLayer,
    build_wake,
    solve_wake_layer,
    wake_influence,
    wake_self_tangential,
    wake_source_strengths,
)

FloatArray = NDArray[np.float64]

__all__ = [
    "CoupledSolution",
    "solve_coupled",
    "coupled_polar",
    "transpiration_velocity",
]

#: Default under-relaxation factor.
#:
#: Direct coupling is only conditionally stable. 0.2 converges attached cases in
#: 10 to 20 iterations and survives trailing-edge stall; above about 0.4 the
#: iteration oscillates once separation appears.
DEFAULT_RELAXATION = 0.2

#: Convergence tolerance on the transpiration velocity, relative to its own norm.
DEFAULT_TOLERANCE = 1e-4

DEFAULT_MAX_ITERATIONS = 120

#: Cap on the displacement-thickness growth rate downstream of separation.
#:
#: Past separation the boundary-layer march has stopped and ``delta*`` must be
#: continued somehow. It is extended linearly at the growth rate it had reached,
#: which represents the separated shear layer spreading. The rate is capped
#: because the slope at separation is itself diverging, and an uncapped
#: extrapolation makes the displacement body grow without bound and the
#: iteration diverge. A free shear layer spreads at roughly 0.1 to 0.2; 0.15 is
#: the middle of that. See NOTES.md, A4.2.
SEPARATED_GROWTH_CAP = 0.15

@dataclass(frozen=True)
class CoupledSolution:
    """A converged viscous-inviscid solution at one angle of attack.

    Attributes
    ----------
    panel : PanelSolution
        The final inviscid solution, including the transpiration.
    boundary_layer : BoundaryLayerSolution
        The final boundary layer.
    wake : Wake
        The panelled wake.
    wake_layer : WakeBoundaryLayer
        Converged wake boundary layer.
    transpiration : ndarray
        ``(n_panels,)`` converged normal velocity, positive outward.
    wake_strengths : ndarray
        ``(n_wake_panels,)`` converged wake source strengths.
    iterations : int
        Iterations actually performed.
    residual : float
        Final relative change in the transpiration velocity.
    converged : bool
        Whether :attr:`residual` fell below the tolerance.
    history : ndarray
        Residual at every iteration, for diagnosing a failure to converge.
    lift_history : ndarray
        Lift coefficient at every iteration.
    """

    panel: PanelSolution
    boundary_layer: BoundaryLayerSolution
    wake: Wake
    wake_layer: WakeBoundaryLayer
    transpiration: FloatArray
    wake_strengths: FloatArray
    iterations: int
    residual: float
    converged: bool
    tolerance: float
    history: FloatArray = field(default_factory=lambda: np.empty(0))
    lift_history: FloatArray = field(default_factory=lambda: np.empty(0))

    @property
    def alpha(self) -> float:
        """Angle of attack in **radians**."""
        return self.panel.alpha

    @property
    def cl(self) -> float:
        """Lift coefficient, from surface-pressure integration."""
        return self.panel.cl_pressure

    @property
    def cm_quarter_chord(self) -> float:
        """Pitching moment about the quarter chord, positive nose-up."""
        return self.panel.cm_quarter_chord

    @cached_property
    def cd(self) -> float:
        """Profile drag coefficient, by Squire-Young on the coupled solution."""
        return self.boundary_layer.cd_profile

    @property
    def cd_form(self) -> float:
        """Pressure drag from integrating the coupled surface pressure.

        With transpiration the body is open, so this is no longer zero by
        D'Alembert and becomes a genuine form drag. It is reported as a
        diagnostic, not summed into :attr:`cd`: adding it to a Squire-Young
        value already containing the pressure defect would double-count.
        """
        return self.panel.cd_pressure

    def check(self) -> "CoupledSolution":
        """Raise unless the iteration converged.

        Raises
        ------
        ConvergenceError
            Carrying the iteration count, final residual and tolerance.
        """
        if not self.converged:
            raise ConvergenceError(
                f"viscous-inviscid coupling did not converge at alpha = "
                f"{np.rad2deg(self.alpha):.2f} deg",
                iterations=self.iterations,
                residual=self.residual,
                tolerance=self.tolerance,
            )
        return self

    def __repr__(self) -> str:
        state = "converged" if self.converged else "NOT CONVERGED"
        return (
            f"<CoupledSolution alpha={np.rad2deg(self.alpha):.2f} deg, "
            f"Cl={self.cl:.4f}, Cd={self.cd:.5f}, "
            f"{self.iterations} iterations, residual {self.residual:.2e}, {state}>"
        )


def _bounded_growth(s: FloatArray, delta_star: FloatArray) -> FloatArray:
    """Rebuild ``delta*`` with its growth rate limited to a physical spreading rate.

    A boundary or shear layer cannot thicken faster than a free shear layer
    spreads, which is roughly 0.1 to 0.2. The uncoupled solution violates this
    badly at the trailing edge — measured ``d(delta*)/ds = 1.75`` — because the
    inviscid edge velocity is heading for a stagnation point there.

    The limiter is a **startup safeguard, not a model**. The first coupling
    iteration necessarily runs on the uncoupled edge velocity, complete with
    that trailing-edge singularity, and without the bound it produces a blowing
    velocity of 0.6 freestream that wrecks the outer solution before the wake
    has any strength to relieve it. Once the wake is established the trailing
    edge is no longer singular and the limiter stops binding; the tests assert
    that it is inactive over the whole surface in a converged attached solution,
    so it cannot be quietly propping up a result.
    The saturation is **smooth**, not a hard clip. A clip makes the
    iteration map non-differentiable wherever it binds, and since it binds near
    the trailing edge on every iteration, the coupling settled into a limit
    cycle instead of converging — the residual bounced between 0.12 and 0.20
    indefinitely. ``cap * tanh(g / cap)`` has the same bound and the same
    behaviour for small ``g``, but is smooth everywhere.
    """
    spacing = np.diff(s)
    raw = np.diff(delta_star) / np.maximum(spacing, 1e-15)
    growth = SEPARATED_GROWTH_CAP * np.tanh(raw / SEPARATED_GROWTH_CAP)
    return delta_star[0] + np.concatenate([[0.0], np.cumsum(growth * spacing)])


def _extended_displacement(
    surface: SurfaceBoundaryLayer,
) -> tuple[FloatArray, FloatArray]:
    """Return ``(s, Ue * delta*)`` continued to the trailing edge.

    The boundary-layer march stops at separation, but the inviscid problem needs
    a displacement effect over the whole surface. Downstream of separation the
    layer is continued linearly at the growth rate it had reached, with the edge
    velocity held at its last value. Both the continued stretch and the marched
    one are passed through :func:`_bounded_growth`.
    """
    s = surface.s
    delta_star = surface.delta_star
    ue = surface.ue

    if not (surface.reached_trailing_edge or s[-1] >= surface.s_total - 1e-12):
        span = max(s[-1] - s[-2], 1e-12)
        growth = float(
            np.clip(
                (delta_star[-1] - delta_star[-2]) / span, 0.0, SEPARATED_GROWTH_CAP
            )
        )
        tail = np.linspace(s[-1], surface.s_total, 40)[1:]
        s = np.concatenate([s, tail])
        delta_star = np.concatenate(
            [delta_star, delta_star[-1] + growth * (tail - s[len(ue) - 1])]
        )
        ue = np.concatenate([ue, np.full(tail.size, ue[-1])])

    return s, ue * _bounded_growth(s, delta_star)


def transpiration_velocity(
    boundary_layer: BoundaryLayerSolution, system: HessSmithSystem
) -> FloatArray:
    """Normal velocity to blow through each panel, from the displacement effect.

    Parameters
    ----------
    boundary_layer : BoundaryLayerSolution
        Boundary layer computed on the current inviscid solution.
    system : HessSmithSystem
        The panel system, for the panel arc lengths.

    Returns
    -------
    ndarray
        ``(n_panels,)`` normal velocity, positive outward, non-dimensionalised
        by freestream speed. A base panel, if present, gets zero.

    Notes
    -----
    ``v_n = d(Ue delta*)/ds`` is differentiated from a spline of the product.
    No smoothing is applied: the raw derivative is clean, running from about
    0.0034 at the leading edge to 0.13 at the trailing edge, and thinning the
    stations was tried and discarded because it flattened the genuine
    trailing-edge peak by 20% while removing nothing.

    Mapping back onto panels uses the stagnation arc length recorded on the
    boundary-layer solution: panels forward of the stagnation index lie on the
    upper surface with ``s = s_stag - s_panel``, and the rest on the lower with
    ``s = s_panel - s_stag``.
    """
    airfoil = system.airfoil
    n_surface = airfoil.n_points - 1
    arc = airfoil.arc_length
    s_control = 0.5 * (arc[:-1] + arc[1:])[:n_surface]

    blowing = np.zeros(system.n_panels)
    stagnation_s = boundary_layer.upper.stagnation_s
    stagnation_index = boundary_layer.upper.stagnation_index

    for surface in boundary_layer.surfaces:
        s, flux = _extended_displacement(surface)
        keep = np.concatenate([[True], np.diff(s) > 1e-13])
        derivative = CubicSpline(s[keep], flux[keep]).derivative()

        if surface.surface == "upper":
            panels = np.arange(0, stagnation_index + 1)
            distance = stagnation_s - s_control[panels]
        else:
            panels = np.arange(stagnation_index + 1, n_surface)
            distance = s_control[panels] - stagnation_s

        blowing[panels] = derivative(np.clip(distance, s[0], s[-1]))

    return blowing


def _wake_edge_velocity(
    panel: PanelSolution,
    wake: Wake,
    strengths: FloatArray,
    floor: float,
) -> FloatArray:
    """Edge velocity along the wake, from every singularity in the problem.

    The airfoil and freestream contribution comes from
    :meth:`PanelSolution.velocity_at`, which does not know about the wake; the
    wake's own contribution is added separately with the self-terms dropped,
    since a source panel induces no tangential velocity at its own midpoint.

    The result is floored at the edge velocity leaving the trailing edge, which
    is what continuity of the outer flow requires: the wake begins where the
    surface layers end, so it inherits their edge velocity there. Without the
    floor the wake starts inside the inviscid trailing-edge stagnation point,
    where ``Ue -> 0`` makes the momentum integral

    .. math:: \\frac{d\\theta}{ds} = -(H+2)\\frac{\\theta}{U_e}\\frac{dU_e}{ds}

    diverge — measured wake source strengths of 12, then 1076, on successive
    iterations. Like the growth bound, the floor stops binding once the wake has
    strength and the stagnation point has moved off the body; the tests assert
    it is inactive in a converged solution. See NOTES.md, A4.5.
    """
    outer = panel.velocity_at(wake.control_points)
    tangential = np.sum(outer * wake.tangents, axis=1)
    tangential = tangential + wake_self_tangential(wake, strengths)
    return np.maximum(np.abs(tangential), floor)


def _trailing_edge_state(
    layer: BoundaryLayerSolution, te_gap: float
) -> tuple[float, float]:
    """Momentum and displacement thickness entering the wake.

    Momentum thickness adds across the two surfaces. Displacement thickness adds
    too, plus the trailing-edge gap itself, which is displaced area whether or
    not there is a boundary layer around it.
    """
    theta = sum(float(surface.theta[-1]) for surface in layer.surfaces)
    delta_star = sum(float(surface.delta_star[-1]) for surface in layer.surfaces)
    return theta, delta_star + te_gap


def solve_coupled(
    airfoil: Airfoil,
    alpha: float,
    reynolds: float,
    *,
    method: TransitionMethod = "en",
    n_crit: float = DEFAULT_N_CRIT,
    relaxation: float = DEFAULT_RELAXATION,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    stations: int = DEFAULT_STATIONS,
    wake_length: float = DEFAULT_WAKE_LENGTH,
    wake_panels: int = DEFAULT_WAKE_PANELS,
    system: HessSmithSystem | None = None,
    initial_transpiration: FloatArray | None = None,
    initial_wake_strengths: FloatArray | None = None,
    validate: bool = True,
) -> CoupledSolution:
    """Iterate the inviscid, boundary-layer and wake solvers to convergence.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alpha : float
        Angle of attack in **radians**.
    reynolds : float
        Reynolds number based on chord.
    method : {"en", "michel"}, optional
        Transition criterion.
    n_crit : float, optional
        Amplification factor at transition for the e^N method.
    relaxation : float, optional
        Under-relaxation factor, in (0, 1].
    tolerance : float, optional
        Convergence tolerance on the relative change in the coupling unknowns.
    max_iterations : int, optional
        Iteration limit.
    stations : int, optional
        Boundary-layer stations per surface.
    wake_length : float, optional
        Wake length in chords.
    wake_panels : int, optional
        Number of wake panels.
    system : HessSmithSystem, optional
        A pre-factorised system. Pass one when sweeping incidence.
    initial_transpiration, initial_wake_strengths : ndarray, optional
        Starting guesses, for continuation from a neighbouring angle.
    validate : bool, optional
        If True (default), raise when the iteration has not converged.

    Returns
    -------
    CoupledSolution

    Raises
    ------
    ConvergenceError
        If ``validate`` is set and the iteration did not converge.
    ValidityRangeError
        If the relaxation factor or Reynolds number is out of range.

    Notes
    -----
    One iteration is: solve the outer flow with the current transpiration and
    wake sources; run the surface boundary layers; carry their trailing-edge
    state into the wake and march that; form new transpiration and wake source
    strengths; under-relax both.

    The residual is the largest relative change across **both** sets of
    unknowns, measured before relaxation is applied — otherwise a small
    relaxation factor would make any iteration look converged.
    """
    if not 0.0 < relaxation <= 1.0:
        raise ValidityRangeError(f"relaxation must lie in (0, 1], got {relaxation}")
    if reynolds <= 0.0:
        raise ValidityRangeError(f"Reynolds number must be positive, got {reynolds}")

    if system is None:
        system = HessSmithSystem(airfoil)
    wake = build_wake(airfoil, alpha, length=wake_length, n_panels=wake_panels)

    blowing = (
        np.zeros(system.n_panels)
        if initial_transpiration is None
        else np.array(initial_transpiration, dtype=np.float64)
    )
    wake_strength = (
        np.zeros(wake.n_panels)
        if initial_wake_strengths is None
        else np.array(initial_wake_strengths, dtype=np.float64)
    )

    history: list[float] = []
    lift_history: list[float] = []
    panel: PanelSolution | None = None
    layer: BoundaryLayerSolution | None = None
    wake_layer: WakeBoundaryLayer | None = None
    residual = np.inf

    for _ in range(max_iterations):
        external = wake_influence(wake, wake_strength, system.control_points)
        panel = system.solve(
            alpha, transpiration=blowing, external_velocity=external, validate=False
        )
        layer = solve_boundary_layer(
            panel, reynolds, method=method, n_crit=n_crit,
            stations=stations, validate=False,
        )

        edge_floor = float(
            np.mean([surface.ue[-1] for surface in layer.surfaces])
        )
        ue_wake = _wake_edge_velocity(panel, wake, wake_strength, edge_floor)
        theta_te, delta_star_te = _trailing_edge_state(layer, airfoil.te_gap)
        wake_layer = solve_wake_layer(
            wake.s, ue_wake, theta_te, delta_star_te, reynolds
        )

        target_blowing = transpiration_velocity(layer, system)
        target_wake = wake_source_strengths(wake_layer)

        scale = max(
            float(np.max(np.abs(target_blowing))),
            float(np.max(np.abs(target_wake))),
            1e-12,
        )
        residual = max(
            float(np.max(np.abs(target_blowing - blowing))),
            float(np.max(np.abs(target_wake - wake_strength))),
        ) / scale
        history.append(residual)
        lift_history.append(panel.cl_pressure)

        if residual < tolerance:
            break
        blowing = blowing + relaxation * (target_blowing - blowing)
        wake_strength = wake_strength + relaxation * (target_wake - wake_strength)

    assert panel is not None and layer is not None and wake_layer is not None
    result = CoupledSolution(
        panel=panel,
        boundary_layer=layer,
        wake=wake,
        wake_layer=wake_layer,
        transpiration=blowing,
        wake_strengths=wake_strength,
        iterations=len(history),
        residual=residual,
        converged=residual < tolerance,
        tolerance=tolerance,
        history=np.array(history),
        lift_history=np.array(lift_history),
    )
    return result.check() if validate else result


def coupled_polar(
    airfoil: Airfoil,
    alphas: FloatArray,
    reynolds: float,
    *,
    method: TransitionMethod = "en",
    n_crit: float = DEFAULT_N_CRIT,
    relaxation: float = DEFAULT_RELAXATION,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    stations: int = DEFAULT_STATIONS,
    wake_length: float = DEFAULT_WAKE_LENGTH,
    wake_panels: int = DEFAULT_WAKE_PANELS,
) -> list[CoupledSolution]:
    """Sweep angle of attack with continuation.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alphas : ndarray
        Angles of attack in **radians**, in the order they should be marched.
        Sweeping upward from a low angle is what lets the solver reach the top
        of the lift curve.
    reynolds : float
        Reynolds number based on chord.
    method, n_crit, relaxation, tolerance, max_iterations, stations
        As for :func:`solve_coupled`.
    wake_length, wake_panels
        As for :func:`solve_coupled`.

    Returns
    -------
    list of CoupledSolution
        One per angle, in the order given. Unconverged points are returned
        rather than raising, so a sweep that fails at the top of the curve still
        yields everything below it; call ``check()`` for a guarantee.

    Notes
    -----
    The system is factorised once for the whole sweep, and each angle starts
    from the previous angle's converged transpiration and wake strengths. The
    first makes the sweep cheap; the second is what makes the approach to stall
    possible, since a cold start at high incidence has no nearby attached
    solution to iterate from.
    """
    system = HessSmithSystem(airfoil)
    results: list[CoupledSolution] = []
    guess_blowing: FloatArray | None = None
    guess_wake: FloatArray | None = None

    for alpha in np.atleast_1d(np.asarray(alphas, dtype=np.float64)):
        result = solve_coupled(
            airfoil, float(alpha), reynolds,
            method=method, n_crit=n_crit, relaxation=relaxation,
            tolerance=tolerance, max_iterations=max_iterations, stations=stations,
            wake_length=wake_length, wake_panels=wake_panels,
            system=system,
            initial_transpiration=guess_blowing,
            initial_wake_strengths=guess_wake,
            validate=False,
        )
        results.append(result)
        if result.converged:
            guess_blowing = result.transpiration
            guess_wake = result.wake_strengths

    return results
