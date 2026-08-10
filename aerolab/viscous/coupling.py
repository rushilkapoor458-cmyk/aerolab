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
    transpiration : ndarray
        ``(n_panels,)`` converged normal velocity, positive outward.
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
    transpiration: FloatArray
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


def _extended_displacement(
    surface: SurfaceBoundaryLayer,
) -> tuple[FloatArray, FloatArray]:
    """Return ``(s, Ue * delta*)`` continued to the trailing edge.

    The boundary-layer march stops at separation, but the inviscid problem needs
    a displacement effect over the whole surface. Downstream of separation the
    layer is continued linearly at the growth rate it had reached, capped by
    :data:`SEPARATED_GROWTH_CAP`, with the edge velocity held at its last value.
    """
    s = surface.s
    flux = surface.ue * surface.delta_star

    if surface.reached_trailing_edge or s[-1] >= surface.s_total - 1e-12:
        return s, flux

    span = max(s[-1] - s[-2], 1e-12)
    growth = (surface.delta_star[-1] - surface.delta_star[-2]) / span
    growth = float(np.clip(growth, 0.0, SEPARATED_GROWTH_CAP))

    tail = np.linspace(s[-1], surface.s_total, 40)[1:]
    delta_tail = surface.delta_star[-1] + growth * (tail - s[-1])
    return (
        np.concatenate([s, tail]),
        np.concatenate([flux, surface.ue[-1] * delta_tail]),
    )


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
    system: HessSmithSystem | None = None,
    initial_transpiration: FloatArray | None = None,
    validate: bool = True,
) -> CoupledSolution:
    """Iterate the inviscid and boundary-layer solvers to convergence.

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
        Under-relaxation factor on the transpiration velocity, in (0, 1].
    tolerance : float, optional
        Convergence tolerance on the relative change in transpiration.
    max_iterations : int, optional
        Iteration limit.
    stations : int, optional
        Boundary-layer stations per surface.
    system : HessSmithSystem, optional
        A pre-factorised system for this airfoil. Pass one when sweeping angle
        of attack: the factorisation is the expensive part and does not depend
        on incidence.
    initial_transpiration : ndarray, optional
        Starting guess. Passing the converged value from a neighbouring angle
        (continuation) roughly halves the iteration count and is what gets the
        solver through the top of the lift curve.
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
        If the relaxation factor is outside (0, 1].

    Notes
    -----
    The residual is the change in transpiration velocity between successive
    iterations, relative to its own magnitude, measured **before** relaxation is
    applied — otherwise a small relaxation factor would make any iteration look
    converged.
    """
    if not 0.0 < relaxation <= 1.0:
        raise ValidityRangeError(
            f"relaxation must lie in (0, 1], got {relaxation}"
        )
    if reynolds <= 0.0:
        raise ValidityRangeError(f"Reynolds number must be positive, got {reynolds}")

    if system is None:
        system = HessSmithSystem(airfoil)

    blowing = (
        np.zeros(system.n_panels)
        if initial_transpiration is None
        else np.array(initial_transpiration, dtype=np.float64)
    )

    history: list[float] = []
    lift_history: list[float] = []
    panel: PanelSolution | None = None
    layer: BoundaryLayerSolution | None = None
    residual = np.inf

    for iteration in range(1, max_iterations + 1):
        panel = system.solve(alpha, transpiration=blowing, validate=False)
        layer = solve_boundary_layer(
            panel,
            reynolds,
            method=method,
            n_crit=n_crit,
            stations=stations,
            validate=False,
        )
        target = transpiration_velocity(layer, system)

        scale = max(float(np.max(np.abs(target))), 1e-12)
        residual = float(np.max(np.abs(target - blowing))) / scale
        history.append(residual)
        lift_history.append(panel.cl_pressure)

        if residual < tolerance:
            break
        blowing = blowing + relaxation * (target - blowing)

    assert panel is not None and layer is not None
    result = CoupledSolution(
        panel=panel,
        boundary_layer=layer,
        transpiration=blowing,
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
) -> list[CoupledSolution]:
    """Sweep angle of attack with continuation.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alphas : ndarray
        Angles of attack in **radians**, in the order they should be marched.
        Sweeping upward from a low angle is what allows the solver to reach the
        top of the lift curve.
    reynolds : float
        Reynolds number based on chord.
    method, n_crit, relaxation, tolerance, max_iterations, stations
        As for :func:`solve_coupled`.

    Returns
    -------
    list of CoupledSolution
        One per angle, in the order given. Unconverged points are returned
        rather than raising, with :attr:`CoupledSolution.converged` False, so
        that a sweep which fails at the top of the curve still yields everything
        below it. Callers that need a guarantee should call ``check()``.

    Notes
    -----
    The system is factorised once for the whole sweep, and each angle starts
    from the previous angle's converged transpiration. Both matter: the first
    makes the sweep cheap, the second makes the approach to stall possible at
    all, because a cold start at high incidence has no attached solution nearby
    to iterate from.
    """
    system = HessSmithSystem(airfoil)
    results: list[CoupledSolution] = []
    guess: FloatArray | None = None

    for alpha in np.atleast_1d(np.asarray(alphas, dtype=np.float64)):
        result = solve_coupled(
            airfoil,
            float(alpha),
            reynolds,
            method=method,
            n_crit=n_crit,
            relaxation=relaxation,
            tolerance=tolerance,
            max_iterations=max_iterations,
            stations=stations,
            system=system,
            initial_transpiration=guess,
            validate=False,
        )
        results.append(result)
        if result.converged:
            guess = result.transpiration

    return results
