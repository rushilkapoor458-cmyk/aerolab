"""Hess-Smith panel method for incompressible, inviscid, two-dimensional flow.

Formulation
-----------
Each panel carries a **constant-strength source** sheet of its own, and a
**single constant-strength vortex** sheet of strength ``gamma`` runs over the
whole contour. That gives ``m + 1`` unknowns for ``m`` panels: the sources
supply thickness, the one vortex supplies circulation.

The equations are ``m`` flow-tangency conditions, one at each panel midpoint,
plus the Kutta condition — equal and opposite tangential velocity on the two
panels meeting at the trailing edge. Square system, solved directly.

Linearity in the freestream
---------------------------
The influence matrix depends only on geometry, and the right-hand side is linear
in the freestream vector. The system is therefore factorised **once** and solved
for a unit freestream along ``x`` and along ``z``; the solution at any angle of
attack is ``cos(alpha)`` times the first plus ``sin(alpha)`` times the second.
An angle-of-attack sweep costs one factorisation and no further solves, which is
what makes the panel-independence study and the Phase 5 polars cheap.

Trailing edge
-------------
A section with a finite trailing-edge gap is closed by a **base panel** across
it, so the body is always closed. Two reasons, in order of importance:

1. D'Alembert's paradox — zero drag in inviscid flow — is a theorem about
   *closed* bodies, and it is the strongest self-check this solver has. An open
   contour breaks it for reasons unrelated to any coding error, destroying the
   check precisely for the blunt sections where it is most wanted.
2. An unclosed source body has non-zero net source strength, which puts a
   spurious source in the far field. Mass would not be conserved.

The price is stated plainly in NOTES.md, L2.1: potential flow puts near-stagnant
high pressure on that base panel, whereas real flow separates off a blunt base
at *below* freestream pressure. Inviscid base pressure is therefore not
physical, and base drag must come from elsewhere.

Conventions
-----------
``alpha`` is in **radians**. Velocities are non-dimensionalised by ``V_inf`` and
lengths by the chord. ``Cp = 1 - (V/V_inf)**2``. ``Cm`` is positive **nose-up**
about the quarter-chord point on the chord line.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import lu_factor, lu_solve

from aerolab.exceptions import SingularSystemError, ValidityRangeError
from aerolab.geometry.airfoil import Airfoil
from aerolab.inviscid.influence import panel_frames, panel_influence, self_influence

FloatArray = NDArray[np.float64]

__all__ = ["HessSmithSystem", "PanelSolution", "solve_panel_method"]

#: Reject the linear system above this condition number rather than return a
#: solution dominated by round-off.
DEFAULT_CONDITION_LIMIT = 1e12

#: Default tolerance on the disagreement between the two lift calculations.
DEFAULT_LIFT_TOLERANCE = 5e-3

#: Trailing-edge gaps below this (in chords) are treated as sharp.
_SHARP_TE_TOLERANCE = 1e-10


@dataclass(frozen=True, eq=False)
class PanelSolution:
    """Converged inviscid solution at one angle of attack.

    Attributes
    ----------
    system : HessSmithSystem
        The system this came from; carries the panel geometry.
    alpha : float
        Angle of attack in **radians**.
    v_inf : float
        Freestream speed used, in the same units as the returned velocities.
    source_strengths : ndarray
        ``(m,)`` constant source strength per unit length on each panel.
    vortex_strength : float
        The single vortex sheet strength per unit length, ``gamma``.
    v_tangential : ndarray
        ``(m,)`` tangential velocity at each panel midpoint, signed along the
        panel tangent, which runs in the direction of the contour traversal.
    cp : ndarray
        ``(m,)`` pressure coefficient at each panel midpoint.
    """

    system: "HessSmithSystem"
    alpha: float
    v_inf: float
    source_strengths: FloatArray
    vortex_strength: float
    v_tangential: FloatArray
    cp: FloatArray

    # ------------------------------------------------------------- geometry

    @property
    def control_points(self) -> FloatArray:
        """``(m, 2)`` panel midpoints, in chords."""
        return self.system.control_points

    @property
    def n_panels(self) -> int:
        """Number of panels, including the base panel if one was added."""
        return self.system.n_panels

    # ---------------------------------------------------------------- lift

    @cached_property
    def circulation(self) -> float:
        """Total circulation, positive clockwise, in ``V_inf`` times chords.

        The vortex sheet has uniform strength, so the bound circulation is
        ``gamma`` times the total panel length. The sign convention follows the
        influence formulas, where positive ``gamma`` is a clockwise circulation
        and hence positive lift.
        """
        return float(self.vortex_strength * self.system.total_length)

    @cached_property
    def cl_kutta_joukowski(self) -> float:
        """Lift coefficient from the Kutta-Joukowski theorem.

        ``L = rho * V_inf * Gamma`` gives ``Cl = 2 * Gamma / (V_inf * c)``. This
        uses only the circulation, so it is genuinely independent of the surface
        pressure integration in :attr:`cl_pressure`.
        """
        return 2.0 * self.circulation / (self.v_inf * self.system.chord)

    @cached_property
    def _force_coefficients(self) -> FloatArray:
        """Force coefficient in wind axes as ``(Cd, Cl)``.

        Integrates ``-Cp * n`` over the panels, then rotates into wind axes.
        """
        forces = -(self.cp * self.system.lengths)[:, None] * self.system.normals
        total = np.sum(forces, axis=0) / self.system.chord
        cos_a, sin_a = np.cos(self.alpha), np.sin(self.alpha)
        drag = total[0] * cos_a + total[1] * sin_a
        lift = -total[0] * sin_a + total[1] * cos_a
        return np.array([drag, lift])

    @cached_property
    def cl_pressure(self) -> float:
        """Lift coefficient from integrating surface pressure."""
        return float(self._force_coefficients[1])

    @cached_property
    def cd_pressure(self) -> float:
        """Drag coefficient from integrating surface pressure.

        In inviscid incompressible flow over a closed body this is zero by
        D'Alembert's paradox. What is returned is therefore a **numerical error
        measure**, not a physical drag: it should be a few times 1e-5 or smaller
        at a few hundred panels. A value that grows with angle of attack or with
        panel count indicates a real problem in the solution, not viscosity.
        """
        return float(self._force_coefficients[0])

    @cached_property
    def cm_quarter_chord(self) -> float:
        """Pitching moment coefficient about the quarter chord, positive nose-up.

        Nose-up is a *clockwise* rotation in the (x aft, z up) plane, so it is
        the negative of the conventional counter-clockwise moment. Check the
        sign on a simple case: an upward force applied aft of the reference point
        pushes the tail up, which is nose-down, and gives a positive
        counter-clockwise moment.
        """
        lever = self.control_points - self.system.moment_reference
        forces = -(self.cp * self.system.lengths)[:, None] * self.system.normals
        moment_ccw = float(
            np.sum(lever[:, 0] * forces[:, 1] - lever[:, 1] * forces[:, 0])
        )
        return -moment_ccw / self.system.chord**2

    # ------------------------------------------------------- self-checking

    @cached_property
    def lift_disagreement(self) -> float:
        """Relative gap between the two independent lift calculations.

        Normalised by ``max(|Cl|, 0.1)`` rather than by ``|Cl|``, so that the
        measure stays meaningful near zero lift instead of dividing by nothing.
        """
        scale = max(abs(self.cl_pressure), 0.1)
        return abs(self.cl_kutta_joukowski - self.cl_pressure) / scale

    def check(self, lift_tolerance: float = DEFAULT_LIFT_TOLERANCE) -> "PanelSolution":
        """Raise if the two lift calculations disagree; otherwise return self.

        Kutta-Joukowski and pressure integration reach the lift by different
        routes — one from the circulation alone, one from the full surface
        pressure distribution. They agree only if the whole solution is right, so
        a gap between them is the most informative single number this solver
        produces.

        Parameters
        ----------
        lift_tolerance : float, optional
            Maximum acceptable :attr:`lift_disagreement`.

        Raises
        ------
        ValidityRangeError
            If the two disagree by more than ``lift_tolerance``.
        """
        if self.lift_disagreement > lift_tolerance:
            raise ValidityRangeError(
                f"the two lift calculations disagree by "
                f"{100 * self.lift_disagreement:.3f}% at alpha = "
                f"{np.rad2deg(self.alpha):.3f} deg: Kutta-Joukowski gives "
                f"{self.cl_kutta_joukowski:.6f}, pressure integration gives "
                f"{self.cl_pressure:.6f}. The solution is not trustworthy. "
                "Try more panels, or check the trailing-edge geometry."
            )
        return self

    # ---------------------------------------------------------- field query

    def velocity_at(self, points: ArrayLike) -> FloatArray:
        """Velocity at arbitrary field points.

        Parameters
        ----------
        points : array_like
            ``(p, 2)`` array of ``(x, z)`` positions, in chords.

        Returns
        -------
        ndarray
            ``(p, 2)`` velocity vectors, in the same units as :attr:`v_inf`.

        Notes
        -----
        The velocity field is **discontinuous across the airfoil surface** — that
        is what a vortex sheet is. Points on or extremely close to a panel return
        the interior-side limit, which is not the physical surface velocity. Use
        :attr:`v_tangential` for surface values; it is computed with the correct
        exterior limit.
        """
        query = np.atleast_2d(np.asarray(points, dtype=np.float64))
        if query.ndim != 2 or query.shape[1] != 2:
            raise ValidityRangeError(
                f"points must have shape (p, 2); got {query.shape}"
            )
        source, vortex = panel_influence(
            self.system.starts, self.system.ends, query
        )
        induced = np.einsum("pmk,m->pk", source, self.source_strengths)
        induced += self.vortex_strength * np.sum(vortex, axis=1)
        return self.system.freestream(self.alpha, self.v_inf)[None, :] + induced

    def __repr__(self) -> str:
        return (
            f"<PanelSolution alpha={np.rad2deg(self.alpha):.2f} deg, "
            f"{self.n_panels} panels, Cl={self.cl_pressure:+.5f}, "
            f"Cm(c/4)={self.cm_quarter_chord:+.5f}, "
            f"Cd_p={self.cd_pressure:+.2e}>"
        )


class HessSmithSystem:
    """Factorised panel system for one airfoil geometry.

    Building the system does all the geometry-dependent work: panel frames,
    influence coefficients, and the LU factorisation. Solving at an angle of
    attack is then a pair of vector combinations.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve. Need not be normalised; coefficients are
        non-dimensionalised by :attr:`~aerolab.geometry.airfoil.Airfoil.chord`
        and the moment reference sits at the quarter-chord point on the chord
        line.
    condition_limit : float, optional
        Reject the system above this condition number.

    Raises
    ------
    SingularSystemError
        If the assembled system is too ill-conditioned to solve meaningfully.
        Usually caused by a trailing edge whose two panels are nearly collinear,
        or by panels of wildly differing length.
    """

    def __init__(
        self, airfoil: Airfoil, *, condition_limit: float = DEFAULT_CONDITION_LIMIT
    ) -> None:
        self.airfoil = airfoil
        self.chord = airfoil.chord

        points = airfoil.points
        starts = points[:-1].copy()
        ends = points[1:].copy()
        self.has_base_panel = airfoil.te_gap > _SHARP_TE_TOLERANCE
        if self.has_base_panel:
            # Continue the counter-clockwise traversal from the lower trailing
            # edge back to the upper one, closing the body.
            starts = np.vstack([starts, points[-1]])
            ends = np.vstack([ends, points[0]])

        self.starts = starts
        self.ends = ends
        self.n_panels = int(starts.shape[0])

        lengths, tangents, local_normals = panel_frames(starts, ends)
        self.lengths = lengths
        self.tangents = tangents
        #: Outward normals of a counter-clockwise contour: the negative of the
        #: right-handed local normals used by the influence formulas.
        self.normals = -local_normals
        self.control_points = 0.5 * (starts + ends)
        self.total_length = float(np.sum(lengths))

        le, te = airfoil.le_point, airfoil.te_point
        self.moment_reference = le + 0.25 * (te - le)

        #: Index pair whose tangential velocities the Kutta condition equates.
        #: These are the two *surface* panels at the trailing edge; the base
        #: panel, when present, is not one of them.
        self.kutta_indices = (0, airfoil.n_points - 2)

        self._assemble(condition_limit)

    # ------------------------------------------------------------- assembly

    def _assemble(self, condition_limit: float) -> None:
        source, vortex = panel_influence(
            self.starts, self.ends, self.control_points
        )
        self_source, self_vortex = self_influence(self.tangents, -self.normals)
        diagonal = np.arange(self.n_panels)
        source[diagonal, diagonal, :] = self_source
        vortex[diagonal, diagonal, :] = self_vortex

        # Project onto each control point's own normal and tangent.
        source_normal = np.einsum("imk,ik->im", source, self.normals)
        source_tangent = np.einsum("imk,ik->im", source, self.tangents)
        vortex_normal = np.einsum("imk,ik->im", vortex, self.normals)
        vortex_tangent = np.einsum("imk,ik->im", vortex, self.tangents)

        self._source_tangent = source_tangent
        self._vortex_tangent = vortex_tangent.sum(axis=1)

        n = self.n_panels
        matrix = np.zeros((n + 1, n + 1))
        matrix[:n, :n] = source_normal
        matrix[:n, n] = vortex_normal.sum(axis=1)

        upper, lower = self.kutta_indices
        matrix[n, :n] = source_tangent[upper, :] + source_tangent[lower, :]
        matrix[n, n] = self._vortex_tangent[upper] + self._vortex_tangent[lower]

        condition = float(np.linalg.cond(matrix))
        if not np.isfinite(condition) or condition > condition_limit:
            raise SingularSystemError(
                f"the panel system is too ill-conditioned to solve: condition "
                f"number {condition:.3e} exceeds the limit {condition_limit:.1e}. "
                "This usually means the two trailing-edge panels are nearly "
                "collinear, or that panel lengths vary too steeply. Repanel with "
                "gentler clustering."
            )
        self.condition_number = condition
        self._lu = lu_factor(matrix)

        # Solve once for a unit freestream along x and along z. Every angle of
        # attack is a linear combination of these two.
        basis = []
        for direction in (np.array([1.0, 0.0]), np.array([0.0, 1.0])):
            rhs = np.zeros(n + 1)
            rhs[:n] = -self.normals @ direction
            rhs[n] = -(
                self.tangents[upper] @ direction + self.tangents[lower] @ direction
            )
            basis.append(lu_solve(self._lu, rhs))
        self._basis = np.array(basis)

    # -------------------------------------------------------------- solving

    @staticmethod
    def freestream(alpha: float, v_inf: float = 1.0) -> FloatArray:
        """Freestream velocity vector for angle of attack ``alpha`` in **radians**."""
        return v_inf * np.array([np.cos(alpha), np.sin(alpha)])

    def solve(
        self,
        alpha: float,
        *,
        v_inf: float = 1.0,
        validate: bool = True,
        lift_tolerance: float = DEFAULT_LIFT_TOLERANCE,
    ) -> PanelSolution:
        """Solve at one angle of attack.

        Parameters
        ----------
        alpha : float
            Angle of attack in **radians**.
        v_inf : float, optional
            Freestream speed. Coefficients are independent of it; it only sets
            the units of the returned velocities.
        validate : bool, optional
            If True (default), check that the two independent lift calculations
            agree and raise if they do not.
        lift_tolerance : float, optional
            Tolerance for that check.

        Returns
        -------
        PanelSolution

        Raises
        ------
        ValidityRangeError
            If ``validate`` is set and the two lift calculations disagree.
        """
        cos_a, sin_a = np.cos(alpha), np.sin(alpha)
        solution = v_inf * (cos_a * self._basis[0] + sin_a * self._basis[1])
        sources = solution[:-1]
        gamma = float(solution[-1])

        stream = self.freestream(alpha, v_inf)
        v_tangential = (
            self.tangents @ stream
            + self._source_tangent @ sources
            + gamma * self._vortex_tangent
        )
        cp = 1.0 - (v_tangential / v_inf) ** 2

        result = PanelSolution(
            system=self,
            alpha=float(alpha),
            v_inf=float(v_inf),
            source_strengths=sources,
            vortex_strength=gamma,
            v_tangential=v_tangential,
            cp=cp,
        )
        return result.check(lift_tolerance) if validate else result

    def solve_sweep(
        self, alphas: ArrayLike, *, v_inf: float = 1.0, validate: bool = True
    ) -> list[PanelSolution]:
        """Solve at several angles of attack.

        Costs no extra factorisations: the system is already factorised and the
        freestream enters linearly.

        Parameters
        ----------
        alphas : array_like
            Angles of attack in **radians**.
        v_inf : float, optional
            Freestream speed.
        validate : bool, optional
            Check lift consistency at every angle.

        Returns
        -------
        list of PanelSolution
        """
        return [
            self.solve(float(a), v_inf=v_inf, validate=validate)
            for a in np.atleast_1d(np.asarray(alphas, dtype=np.float64))
        ]

    def __repr__(self) -> str:
        base = " + base panel" if self.has_base_panel else ""
        return (
            f"<HessSmithSystem {self.airfoil.name!r}: {self.n_panels} panels{base}, "
            f"cond={self.condition_number:.2e}>"
        )


def solve_panel_method(
    airfoil: Airfoil,
    alpha: float,
    *,
    v_inf: float = 1.0,
    validate: bool = True,
) -> PanelSolution:
    """Solve an airfoil at one angle of attack.

    Convenience wrapper that builds a :class:`HessSmithSystem` and solves it. For
    more than one angle of attack, build the system once and call
    :meth:`HessSmithSystem.solve_sweep` instead — the factorisation is the
    expensive part and it does not depend on the angle.

    Parameters
    ----------
    airfoil : Airfoil
        Section to solve.
    alpha : float
        Angle of attack in **radians**.
    v_inf : float, optional
        Freestream speed.
    validate : bool, optional
        Check that the two lift calculations agree.

    Returns
    -------
    PanelSolution
    """
    return HessSmithSystem(airfoil).solve(alpha, v_inf=v_inf, validate=validate)
