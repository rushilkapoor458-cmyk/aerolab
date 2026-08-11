"""Exact self-similar laminar boundary layers, as a validation reference.

The integral methods in this package close their equations with curve fits.
A fit is only as good as the data it was fitted to, and a misremembered constant
in a fit produces a plausible number rather than an obvious failure. This module
exists so that the fits never have to be taken on trust: the Falkner-Skan family
has an exact solution, it spans the whole range of shape factors an integral
method will encounter, and everything the closure relations claim about
:math:`H^*`, :math:`c_f` and :math:`c_D` can be checked against it directly.

The equation
------------
For an edge velocity :math:`U_e \\propto x^m` the momentum equation reduces to
the ordinary differential equation

.. math:: f''' + f f'' + \\beta\\left(1 - f'^2\\right) = 0

with :math:`f(0) = f'(0) = 0` and :math:`f'(\\infty) = 1`, where
:math:`\\beta = 2m/(m+1)` is the Hartree pressure-gradient parameter and
:math:`f' = u/U_e`. Three values anchor everything else:

===============  ==========================  ==========
``beta``         flow                        ``H``
===============  ==========================  ==========
``1``            plane stagnation (Hiemenz)  2.216
``0``            flat plate (Blasius)        2.592
``-0.198838``    separation                  4.029
===============  ==========================  ==========

Below :math:`\\beta \\approx -0.198838` no attached solution exists. Between
that value and zero there are **two** solutions; the physical one is the branch
reached continuously from :math:`\\beta = 0`, which is why this module always
solves by continuation rather than by shooting at the target directly.

Non-dimensionalisation
----------------------
The similarity variable is

.. math:: \\eta = y \\sqrt{\\frac{(m+1)}{2}\\frac{U_e}{\\nu x}}

and the thickness integrals returned are in that variable:

.. math::
    \\delta_1 = \\int_0^\\infty (1 - f')\\,d\\eta, \\quad
    \\delta_2 = \\int_0^\\infty f'(1 - f')\\,d\\eta, \\quad
    \\delta_3 = \\int_0^\\infty f'(1 - f'^2)\\,d\\eta

Shape factors are ratios of these and so are independent of the scaling, which
is the point: :math:`H = \\delta_1/\\delta_2` and :math:`H^* = \\delta_3/\\delta_2`
are pure numbers, and the Reynolds-number-scaled friction and dissipation
:math:`Re_\\theta c_f/2 = \\delta_2 f''(0)` and
:math:`Re_\\theta c_D = \\delta_2 \\int_0^\\infty f''^2 d\\eta` are too. Every one
of those four identities is derived in the notes on the corresponding property
and asserted in ``tests/test_viscous_falkner_skan.py``.

References
----------
Falkner, V. M. and Skan, S. W., "Some approximate solutions of the boundary
layer equations", ARC R&M 1314, 1930.
Hartree, D. R., "On an equation occurring in Falkner and Skan's approximate
treatment of the equations of the boundary layer", Proc. Camb. Phil. Soc. 33,
1937.
White, F. M., *Viscous Fluid Flow*, 3rd ed., 2006, section 4-3.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_bvp

from aerolab.exceptions import ConvergenceError, ValidityRangeError

FloatArray = NDArray[np.float64]

__all__ = [
    "BETA_SEPARATION",
    "FalknerSkanSolution",
    "solve_falkner_skan",
    "falkner_skan_family",
]

#: Hartree parameter at laminar separation, where ``f''(0)`` reaches zero.
#:
#: Quoted in the literature as -0.19884 (Hartree 1937) and as -0.1988 or
#: -0.19883 elsewhere; the differences are in the fifth figure and are an
#: artefact of how far each author integrated in ``eta``. This module's own
#: bisection on ``f''(0) = 0`` is asserted against the quoted value in the tests.
BETA_SEPARATION = -0.198838

#: Outer limit of the similarity variable.
#:
#: The edge velocity is approached exponentially for ``beta > 0`` but only
#: algebraically as separation is neared, so a limit chosen for Blasius is far
#: too small at ``beta = -0.19``. 20 keeps ``1 - f'`` below 1e-10 at the outer
#: boundary across the whole family; the tests check that doubling it moves
#: ``H`` by less than 1e-6.
DEFAULT_ETA_MAX = 20.0

DEFAULT_NODES = 601
DEFAULT_TOLERANCE = 1e-10


@dataclass(frozen=True)
class FalknerSkanSolution:
    """One exact self-similar laminar boundary layer.

    Attributes
    ----------
    beta : float
        Hartree pressure-gradient parameter. Positive is favourable.
    eta : ndarray
        Similarity variable at the solution nodes, from 0 to ``eta_max``.
    f, f_prime, f_double_prime : ndarray
        The stream function and its first two derivatives. ``f_prime`` is
        ``u/Ue``.
    residual : float
        Largest residual of the differential equation, as reported by the
        solver. A converged solution has this below the requested tolerance.
    """

    beta: float
    eta: FloatArray
    f: FloatArray
    f_prime: FloatArray
    f_double_prime: FloatArray
    residual: float

    @property
    def shear(self) -> float:
        """Wall shear ``f''(0)``, zero at separation and negative beyond it."""
        return float(self.f_double_prime[0])

    @cached_property
    def delta_1(self) -> float:
        """Displacement integral ``int (1 - f') d(eta)``."""
        return float(np.trapezoid(1.0 - self.f_prime, self.eta))

    @cached_property
    def delta_2(self) -> float:
        """Momentum integral ``int f'(1 - f') d(eta)``."""
        return float(np.trapezoid(self.f_prime * (1.0 - self.f_prime), self.eta))

    @cached_property
    def delta_3(self) -> float:
        """Kinetic energy integral ``int f'(1 - f'^2) d(eta)``."""
        return float(
            np.trapezoid(self.f_prime * (1.0 - self.f_prime**2), self.eta)
        )

    @cached_property
    def dissipation_integral(self) -> float:
        """``int f''^2 d(eta)``, which sets the dissipation coefficient."""
        return float(np.trapezoid(self.f_double_prime**2, self.eta))

    @property
    def h(self) -> float:
        """Shape factor ``delta*/theta``, a pure number."""
        return self.delta_1 / self.delta_2

    @property
    def h_star(self) -> float:
        """Kinetic energy shape factor ``theta*/theta``, a pure number."""
        return self.delta_3 / self.delta_2

    @property
    def re_theta_cf_half(self) -> float:
        """``Re_theta * cf / 2``, a pure number.

        Notes
        -----
        With :math:`u = U_e f'(\\eta)` and
        :math:`\\eta = y\\sqrt{\\tfrac{m+1}{2}U_e/(\\nu x)}`, the wall shear is
        :math:`\\tau_w = \\mu U_e f''(0)\\sqrt{\\tfrac{m+1}{2}U_e/(\\nu x)}`, so

        .. math:: \\frac{c_f}{2} = \\frac{f''(0)}{\\sqrt{Re_x}}
                  \\sqrt{\\tfrac{m+1}{2}}

        while :math:`\\theta = \\delta_2 x /
        (\\sqrt{Re_x}\\sqrt{\\tfrac{m+1}{2}})` gives
        :math:`Re_\\theta = \\delta_2\\sqrt{Re_x}/\\sqrt{\\tfrac{m+1}{2}}`.
        The two square roots and the whole :math:`(m+1)/2` factor cancel in the
        product, leaving :math:`Re_\\theta c_f/2 = \\delta_2 f''(0)` — which is
        why this is a property of ``beta`` alone.
        """
        return self.delta_2 * self.shear

    @property
    def re_theta_cd(self) -> float:
        """``Re_theta * cD``, a pure number.

        Notes
        -----
        The dissipation coefficient is
        :math:`c_D = \\int \\tau (\\partial u/\\partial y)\\,dy / (\\rho U_e^3)`,
        which for a laminar layer is
        :math:`\\nu\\int(\\partial u/\\partial y)^2 dy / U_e^3`. Substituting the
        similarity form and cancelling exactly as above gives
        :math:`Re_\\theta c_D = \\delta_2 \\int_0^\\infty f''^2 d\\eta`.
        """
        return self.delta_2 * self.dissipation_integral

    def __repr__(self) -> str:
        return (
            f"<FalknerSkanSolution beta={self.beta:+.6f}, H={self.h:.4f}, "
            f"H*={self.h_star:.4f}, f''(0)={self.shear:.5f}>"
        )


def _solve_at(
    beta: float,
    guess_eta: FloatArray,
    guess_state: FloatArray,
    tolerance: float,
) -> tuple[FloatArray, FloatArray, float]:
    """One Falkner-Skan solve from a supplied initial guess."""

    def equations(eta: FloatArray, state: FloatArray) -> FloatArray:
        f, fp, fpp = state
        return np.vstack([fp, fpp, -f * fpp - beta * (1.0 - fp**2)])

    def boundary(left: FloatArray, right: FloatArray) -> FloatArray:
        return np.array([left[0], left[1], right[1] - 1.0])

    result = solve_bvp(
        equations,
        boundary,
        guess_eta,
        guess_state,
        tol=tolerance,
        max_nodes=200_000,
    )
    if not result.success:
        raise ConvergenceError(
            f"the Falkner-Skan equation did not converge at beta = {beta:.6f}: "
            f"{result.message}. Below beta = {BETA_SEPARATION:.6f} no attached "
            "solution exists.",
            iterations=int(result.status),
            residual=float(np.max(result.rms_residuals)),
            tolerance=tolerance,
        )
    return result.x, result.y, float(np.max(result.rms_residuals))


def _continuation_path(
    beta: float, step: float, start: float = 0.0
) -> list[float]:
    """Intermediate ``beta`` values to solve on the way from ``start`` to ``beta``.

    Uniform steps in ``beta`` are the wrong parameterisation on the adverse side.
    The Falkner-Skan family has a **fold** at :data:`BETA_SEPARATION`: the two
    branches meet there and the wall shear behaves as
    :math:`f''(0) \\sim \\sqrt{\\beta - \\beta_{sep}}`. Uniform steps in
    ``beta`` therefore become unboundedly large steps in the solution as the
    fold is approached, and the solver either fails to converge or jumps to the
    reversed-flow branch.

    Stepping uniformly in :math:`u = \\sqrt{\\beta - \\beta_{sep}}` instead makes
    the steps uniform in ``f''(0)``, which is what the solver actually has to
    track. On the favourable side there is no fold and plain uniform steps are
    used.
    """
    if beta == start:
        return []
    if beta >= 0.0:
        count = max(int(np.ceil(abs(beta - start) / step)), 1)
        return [float(v) for v in np.linspace(start, beta, count + 1)[1:]]

    u_start = np.sqrt(max(start - BETA_SEPARATION, 0.0))
    u_end = np.sqrt(max(beta - BETA_SEPARATION, 0.0))
    count = max(int(np.ceil(abs(u_end - u_start) / (0.5 * step))), 1)
    path = BETA_SEPARATION + np.linspace(u_start, u_end, count + 1)[1:] ** 2
    return [float(v) for v in path]


def solve_falkner_skan(
    beta: float,
    *,
    eta_max: float = DEFAULT_ETA_MAX,
    nodes: int = DEFAULT_NODES,
    tolerance: float = DEFAULT_TOLERANCE,
    continuation_step: float = 0.05,
) -> FalknerSkanSolution:
    """Solve the Falkner-Skan equation for one pressure-gradient parameter.

    Parameters
    ----------
    beta : float
        Hartree parameter, dimensionless. Positive is a favourable gradient.
        Must not be below :data:`BETA_SEPARATION`, where the attached solution
        ceases to exist.
    eta_max : float, optional
        Outer limit of the similarity variable.
    nodes : int, optional
        Nodes in the initial mesh; the solver refines adaptively from there.
    tolerance : float, optional
        Residual tolerance passed to the boundary-value solver.
    continuation_step : float, optional
        Largest step in ``beta`` taken while marching from the Blasius solution
        to the target.

    Returns
    -------
    FalknerSkanSolution

    Raises
    ------
    ValidityRangeError
        If ``beta`` is below the separation value, where the problem has no
        attached solution — this is a property of the equation, not a failure of
        the solver, so it is reported as an invalid request rather than as
        non-convergence.
    ConvergenceError
        If the boundary-value solver fails at some point along the continuation.

    Notes
    -----
    The solve always starts from :math:`\\beta = 0`, whose solution is generated
    from an analytic approximation, and steps towards the target. For
    :math:`\\beta > 0` this is merely convenient. For :math:`\\beta < 0` it is
    **necessary**: the problem has two solutions there, one attached and one
    with reversed flow near the wall, and a boundary-value solver started from a
    generic guess can land on either. Continuity from the flat plate is what
    selects the physical branch.
    """
    if beta < BETA_SEPARATION - 1e-9:
        raise ValidityRangeError(
            f"beta = {beta:.6f} is below the separation value "
            f"{BETA_SEPARATION:.6f}; the Falkner-Skan equation has no attached "
            "solution there. A separated similarity profile is not a boundary "
            "layer in the sense this module means."
        )
    if eta_max <= 0.0:
        raise ValidityRangeError(f"eta_max must be positive, got {eta_max}")

    eta = np.linspace(0.0, eta_max, nodes)
    # A tanh profile satisfies the wall and edge conditions and is close enough
    # to Blasius for the first solve to converge in a few iterations.
    f_prime = np.tanh(0.7 * eta)
    state = np.vstack(
        [
            np.log(np.cosh(0.7 * eta)) / 0.7,
            f_prime,
            0.7 / np.cosh(0.7 * eta) ** 2,
        ]
    )
    eta, state, residual = _solve_at(0.0, eta, state, tolerance)

    for target in _continuation_path(beta, continuation_step):
        eta, state, residual = _solve_at(target, eta, state, tolerance)

    return FalknerSkanSolution(
        beta=float(beta),
        eta=eta,
        f=state[0],
        f_prime=state[1],
        f_double_prime=state[2],
        residual=residual,
    )


def falkner_skan_family(
    betas: NDArray[np.float64] | list[float],
    *,
    eta_max: float = DEFAULT_ETA_MAX,
    nodes: int = DEFAULT_NODES,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[FalknerSkanSolution]:
    """Solve for a sequence of pressure-gradient parameters, reusing each solution.

    Parameters
    ----------
    betas : array_like
        Hartree parameters. They are solved in the order given and each solve
        starts from the previous solution, so a monotone sequence costs far less
        than the same values solved independently.
    eta_max, nodes, tolerance
        As for :func:`solve_falkner_skan`.

    Returns
    -------
    list of FalknerSkanSolution
        One per requested ``beta``, in the order given.

    Notes
    -----
    Ordering matters for more than speed. Marching down towards separation keeps
    every solve on the attached branch by construction; a sequence that jumps
    from a strongly favourable gradient straight to ``beta = -0.19`` may land on
    the reversed-flow branch even though each individual value is legal.
    """
    values = np.atleast_1d(np.asarray(betas, dtype=np.float64))
    if np.any(values < BETA_SEPARATION - 1e-9):
        raise ValidityRangeError(
            f"beta values must not fall below {BETA_SEPARATION:.6f}; got a "
            f"minimum of {float(np.min(values)):.6f}"
        )

    solutions: list[FalknerSkanSolution] = []
    eta = np.linspace(0.0, eta_max, nodes)
    f_prime = np.tanh(0.7 * eta)
    state = np.vstack(
        [
            np.log(np.cosh(0.7 * eta)) / 0.7,
            f_prime,
            0.7 / np.cosh(0.7 * eta) ** 2,
        ]
    )
    eta, state, residual = _solve_at(0.0, eta, state, tolerance)
    seed_eta, seed_state = eta.copy(), state.copy()
    seed_residual = residual

    previous = 0.0
    for beta in values:
        target = float(beta)
        for intermediate in _continuation_path(target, 0.05, start=previous):
            eta, state, residual = _solve_at(
                intermediate, eta, state, tolerance
            )
        solutions.append(
            FalknerSkanSolution(
                beta=target,
                eta=eta,
                f=state[0],
                f_prime=state[1],
                f_double_prime=state[2],
                residual=residual,
            )
        )
        previous = target
        if target > 0.5:
            # Strongly favourable solutions are a poor starting point for the
            # adverse end of the family; restart from the flat plate instead.
            eta, state, residual = seed_eta.copy(), seed_state.copy(), seed_residual
            previous = 0.0

    return solutions
