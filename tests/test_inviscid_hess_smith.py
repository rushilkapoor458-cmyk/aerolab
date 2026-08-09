"""Tests for the Hess-Smith panel solver.

Three exact references do the work, in increasing order of difficulty:

**Circular cylinder**
    ``Cp = 1 - 4 sin^2(theta)``. No camber, no Kutta condition — this tests the
    influence machinery and the source solve alone. It is reproduced to machine
    precision, which is a property of a uniformly panelled circle rather than
    general behaviour.

**Joukowski airfoil**
    Thick, cambered, exact. The only reference in the suite that is all three at
    once, and the one that establishes the method converges to the *right*
    answer rather than merely to a stable one.

**D'Alembert's paradox**
    Zero drag on a closed body in inviscid flow. Holds for every section at
    every angle, so the residual pressure drag is a free error measure on every
    single solve.

Convergence
-----------
The method is **first order**: the error halves when the panel count doubles.
Acceptance targets are therefore checked against Richardson-extrapolated values,
``f_inf = f_fine - (f_fine - f_coarse) / (1 - N_fine/N_coarse)``, which is the
converged number rather than whatever a particular panel count happens to give.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem, solve_panel_method
from aerolab.inviscid.influence import panel_frames, panel_influence, self_influence

from tests.helpers import Joukowski

pytestmark = pytest.mark.validation


def richardson(coarse: float, fine: float, n_coarse: float, n_fine: float) -> float:
    """First-order extrapolation to infinite panel count."""
    return fine - (fine - coarse) / (1.0 - n_fine / n_coarse)


def cylinder_cp(n_panels: int) -> tuple[np.ndarray, np.ndarray]:
    """Solve a unit cylinder with source panels only; return (Cp, exact Cp)."""
    theta = np.linspace(0.0, 2.0 * np.pi, n_panels + 1)
    points = np.column_stack([np.cos(theta), np.sin(theta)])
    starts, ends = points[:-1], points[1:]
    _, tangents, local_normals = panel_frames(starts, ends)
    outward = -local_normals
    control = 0.5 * (starts + ends)

    source, _ = panel_influence(starts, ends, control)
    self_source, _ = self_influence(tangents, local_normals)
    diagonal = np.arange(n_panels)
    source[diagonal, diagonal, :] = self_source

    normal = np.einsum("imk,ik->im", source, outward)
    tangential = np.einsum("imk,ik->im", source, tangents)
    stream = np.array([1.0, 0.0])
    strengths = np.linalg.solve(normal, -(outward @ stream))
    speed = tangents @ stream + tangential @ strengths

    angle = np.arctan2(control[:, 1], control[:, 0])
    return 1.0 - speed**2, 1.0 - 4.0 * np.sin(angle) ** 2


class TestCylinder:
    """Exact reference with no circulation."""

    @pytest.mark.parametrize("n", [40, 80, 160])
    def test_pressure_distribution_is_exact(self, n: int) -> None:
        got, exact = cylinder_cp(n)
        assert np.max(np.abs(got - exact)) < 1e-13

    def test_stagnation_and_peak_suction(self, n: int = 200) -> None:
        got, _ = cylinder_cp(n)
        assert np.max(got) == pytest.approx(1.0, abs=1e-3)
        assert np.min(got) == pytest.approx(-3.0, abs=1e-3)


class TestJoukowski:
    """Exact reference with thickness, camber and circulation."""

    @pytest.fixture(scope="module")
    def mapping(self) -> Joukowski:
        return Joukowski(x_offset=0.10, z_offset=0.08)

    @pytest.mark.parametrize("alpha_deg", [0.0, 5.0])
    def test_lift_converges_to_the_exact_value(
        self, mapping: Joukowski, alpha_deg: float
    ) -> None:
        """Extrapolated lift must match the closed-form value closely.

        Individual panel counts run 1-8% low: the method is first order, and
        this section's cusped trailing edge drags the observed order down to
        about 0.81. Extrapolating as if it were exactly first order therefore
        *under*-corrects, leaving about 0.35% — which is why the tolerance here
        is 0.5% rather than the 0.02% a proper order-0.81 extrapolation achieves.
        The point of the test is that the method converges to the exact answer,
        not that a two-grid shortcut is sharp. See NOTES.md, L2.2.
        """
        alpha = np.deg2rad(alpha_deg)
        results = {}
        for n in (641, 1281):
            airfoil = mapping.airfoil(n)
            system = HessSmithSystem(airfoil)
            results[system.n_panels] = (
                system.solve(alpha, validate=False).cl_pressure,
                mapping.cl(alpha, airfoil.chord),
            )
        counts = sorted(results)
        limit = richardson(
            results[counts[0]][0], results[counts[1]][0], counts[0], counts[1]
        )
        exact = results[counts[1]][1]
        assert limit == pytest.approx(exact, rel=5e-3)
        # The uncorrected value must be worse than the extrapolated one, which
        # is what shows the extrapolation is doing something real.
        assert abs(limit - exact) < abs(results[counts[1]][0] - exact)

    def test_far_field_velocity_matches_the_exact_solution(
        self, mapping: Joukowski
    ) -> None:
        """Away from the body the two flow fields must coincide.

        Checked off the surface deliberately: on the surface the inverse of the
        Joukowski map is ambiguous, and a naive branch test silently returns
        interior values. That trap cost real debugging time; see NOTES.md, V2.3.
        """
        alpha = np.deg2rad(5.0)
        airfoil = mapping.airfoil(1281)
        solution = HessSmithSystem(airfoil).solve(alpha, validate=False)

        theta = np.linspace(0.0, 2.0 * np.pi, 400)
        probe = np.column_stack([6.0 * np.cos(theta), 6.0 * np.sin(theta)])
        got = solution.velocity_at(probe)
        exact = mapping.velocity(probe, alpha)
        assert np.max(np.linalg.norm(got - exact, axis=1)) < 2e-3

    def test_circulation_matches(self, mapping: Joukowski) -> None:
        alpha = np.deg2rad(5.0)
        airfoil = mapping.airfoil(1281)
        solution = HessSmithSystem(airfoil).solve(alpha, validate=False)
        assert solution.circulation == pytest.approx(
            mapping.circulation(alpha), rel=2e-2
        )


class TestAcceptanceTargets:
    """The Phase 2 acceptance table, judged at converged values."""

    COUNTS = (481, 961)

    def _extrapolate(self, values: dict[int, float]) -> float:
        counts = sorted(values)
        return richardson(values[counts[0]], values[counts[1]], counts[0], counts[1])

    def test_naca0012_lift_slope(self) -> None:
        """dCl/dalpha = 6.93 +/- 0.02 per radian."""
        alphas = np.deg2rad(np.array([-4.0, -2.0, 0.0, 2.0, 4.0]))
        slopes = {}
        for n in self.COUNTS:
            system = HessSmithSystem(naca("0012", n))
            lift = [s.cl_pressure for s in system.solve_sweep(alphas, validate=False)]
            slopes[system.n_panels] = float(np.polyfit(alphas, lift, 1)[0])
        assert self._extrapolate(slopes) == pytest.approx(6.93, abs=0.02)

    def test_naca2412_zero_lift_angle(self) -> None:
        """alpha_L0 = -2.15 +/- 0.05 degrees."""
        alphas = np.deg2rad(np.linspace(-6.0, 6.0, 13))
        angles = {}
        for n in self.COUNTS:
            system = HessSmithSystem(naca("2412", n))
            lift = [s.cl_pressure for s in system.solve_sweep(alphas, validate=False)]
            fit = np.polyfit(alphas, lift, 1)
            angles[system.n_panels] = float(np.rad2deg(-fit[1] / fit[0]))
        assert self._extrapolate(angles) == pytest.approx(-2.15, abs=0.05)

    def test_naca4412_quarter_chord_moment(self) -> None:
        """Cm about c/4 at alpha = 4 degrees is -0.115 +/- 0.005."""
        moments = {}
        for n in self.COUNTS:
            system = HessSmithSystem(naca("4412", n))
            moments[system.n_panels] = system.solve(
                np.deg2rad(4.0), validate=False
            ).cm_quarter_chord
        assert self._extrapolate(moments) == pytest.approx(-0.115, abs=0.005)

    def test_naca0012_at_zero_incidence_produces_nothing(self) -> None:
        """A symmetric section at zero incidence: no lift, no moment, no drag."""
        solution = solve_panel_method(naca("0012", 241), 0.0)
        assert solution.cl_pressure == pytest.approx(0.0, abs=1e-9)
        assert solution.cl_kutta_joukowski == pytest.approx(0.0, abs=1e-9)
        assert solution.cm_quarter_chord == pytest.approx(0.0, abs=1e-9)
        assert abs(solution.cd_pressure) < 5e-4


class TestDAlembert:
    """Zero drag on a closed body. True at every angle for every section."""

    @pytest.mark.parametrize("code", ["0012", "2412", "4412", "23012"])
    @pytest.mark.parametrize("alpha_deg", [-4.0, 0.0, 6.0, 12.0])
    def test_pressure_drag_is_negligible(self, code: str, alpha_deg: float) -> None:
        solution = HessSmithSystem(naca(code, 321)).solve(
            np.deg2rad(alpha_deg), validate=False
        )
        assert abs(solution.cd_pressure) < 3e-3

    def test_residual_falls_with_panel_count(self) -> None:
        """It is a discretisation error, so refining must reduce it."""
        drags = [
            abs(
                HessSmithSystem(naca("4412", n))
                .solve(np.deg2rad(5.0), validate=False)
                .cd_pressure
            )
            for n in (81, 161, 321, 641)
        ]
        assert all(a > b for a, b in zip(drags, drags[1:]))

    def test_blunt_trailing_edge_still_obeys_dalembert(self) -> None:
        """The base panel is what preserves this; without it the body is open."""
        system = HessSmithSystem(naca("0012", 321, closed_te=False))
        assert system.has_base_panel
        solution = system.solve(np.deg2rad(5.0), validate=False)
        assert abs(solution.cd_pressure) < 3e-3


class TestLiftConsistency:
    """The two lift routes must agree, and disagreement must be reported."""

    @pytest.mark.parametrize("code", ["0012", "2412", "23012"])
    def test_agreement_at_a_realistic_panel_count(self, code: str) -> None:
        solution = HessSmithSystem(naca(code, 401)).solve(np.deg2rad(5.0))
        assert solution.lift_disagreement < 5e-3

    def test_disagreement_shrinks_with_panel_count(self) -> None:
        gaps = [
            HessSmithSystem(naca("4412", n))
            .solve(np.deg2rad(5.0), validate=False)
            .lift_disagreement
            for n in (81, 161, 321, 641)
        ]
        assert all(a > b for a, b in zip(gaps, gaps[1:]))

    def test_a_coarse_cambered_section_is_refused_not_returned(self) -> None:
        """The whole point of the check: no plausible-looking wrong number."""
        system = HessSmithSystem(naca("4412", 61))
        with pytest.raises(ValidityRangeError, match="disagree"):
            system.solve(np.deg2rad(-4.0))

    def test_the_refusal_can_be_bypassed_deliberately(self) -> None:
        """Opting out must be explicit, which is why validate defaults to True."""
        system = HessSmithSystem(naca("4412", 61))
        solution = system.solve(np.deg2rad(-4.0), validate=False)
        assert solution.lift_disagreement > 5e-3

    def test_check_returns_self_when_it_passes(self) -> None:
        solution = HessSmithSystem(naca("0012", 241)).solve(np.deg2rad(3.0))
        assert solution.check() is solution


class TestSymmetryAndLinearity:
    """Structural properties that follow from the formulation."""

    def test_symmetric_section_has_antisymmetric_lift(self) -> None:
        system = HessSmithSystem(naca("0012", 241))
        for alpha_deg in (2.0, 5.0, 9.0):
            positive = system.solve(np.deg2rad(alpha_deg), validate=False)
            negative = system.solve(np.deg2rad(-alpha_deg), validate=False)
            assert positive.cl_pressure == pytest.approx(
                -negative.cl_pressure, rel=1e-10
            )
            assert positive.cd_pressure == pytest.approx(
                negative.cd_pressure, rel=1e-8
            )

    def test_solution_is_linear_in_the_freestream_direction(self) -> None:
        """cos and sin superposition is what makes a sweep free; verify it holds."""
        system = HessSmithSystem(naca("2412", 161))
        at_zero = system.solve(0.0, validate=False)
        at_ninety = system.solve(np.pi / 2.0, validate=False)
        alpha = np.deg2rad(7.0)
        combined = np.cos(alpha) * at_zero.source_strengths + np.sin(
            alpha
        ) * at_ninety.source_strengths
        direct = system.solve(alpha, validate=False)
        assert np.allclose(direct.source_strengths, combined, rtol=1e-10)

    def test_coefficients_do_not_depend_on_freestream_speed(self) -> None:
        system = HessSmithSystem(naca("2412", 161))
        slow = system.solve(np.deg2rad(4.0), v_inf=1.0, validate=False)
        fast = system.solve(np.deg2rad(4.0), v_inf=42.0, validate=False)
        assert fast.cl_pressure == pytest.approx(slow.cl_pressure, rel=1e-12)
        assert fast.cm_quarter_chord == pytest.approx(
            slow.cm_quarter_chord, rel=1e-12
        )

    def test_sweep_matches_individual_solves(self) -> None:
        system = HessSmithSystem(naca("4412", 161))
        alphas = np.deg2rad(np.array([-2.0, 0.0, 3.0]))
        swept = system.solve_sweep(alphas, validate=False)
        for alpha, solution in zip(alphas, swept):
            direct = system.solve(float(alpha), validate=False)
            assert solution.cl_pressure == pytest.approx(direct.cl_pressure, rel=1e-14)


class TestSurfaceAndField:
    """Surface quantities and the velocity-field query."""

    def test_stagnation_pressure_is_reached_near_the_nose(self) -> None:
        solution = solve_panel_method(naca("0012", 321), np.deg2rad(4.0))
        peak = int(np.argmax(solution.cp))
        assert solution.cp[peak] == pytest.approx(1.0, abs=5e-3)
        assert solution.control_points[peak, 0] < 0.03

    def test_upper_surface_is_the_suction_side_at_positive_incidence(self) -> None:
        solution = solve_panel_method(naca("0012", 321), np.deg2rad(6.0))
        upper = solution.control_points[:, 1] > 0.02
        lower = solution.control_points[:, 1] < -0.02
        assert solution.cp[upper].mean() < solution.cp[lower].mean()

    def test_velocity_far_away_tends_to_the_freestream(self) -> None:
        alpha = np.deg2rad(6.0)
        solution = solve_panel_method(naca("2412", 241), alpha)
        probe = np.array([[-400.0, 0.0], [400.0, 0.0], [0.0, 400.0], [0.0, -400.0]])
        velocity = solution.velocity_at(probe)
        expected = np.array([np.cos(alpha), np.sin(alpha)])
        assert np.allclose(velocity, expected, atol=2e-3)

    def test_velocity_scales_with_freestream_speed(self) -> None:
        system = HessSmithSystem(naca("0012", 161))
        probe = np.array([[2.0, 0.5]])
        slow = system.solve(np.deg2rad(3.0), v_inf=1.0, validate=False)
        fast = system.solve(np.deg2rad(3.0), v_inf=10.0, validate=False)
        assert np.allclose(
            fast.velocity_at(probe), 10.0 * slow.velocity_at(probe), rtol=1e-12
        )

    def test_malformed_query_points_are_rejected(self) -> None:
        solution = solve_panel_method(naca("0012", 161), 0.0)
        with pytest.raises(ValidityRangeError, match=r"shape \(p, 2\)"):
            solution.velocity_at(np.zeros((4, 3)))

    def test_cp_and_panel_arrays_are_consistent_in_length(self) -> None:
        system = HessSmithSystem(naca("2412", 161))
        solution = system.solve(0.0, validate=False)
        assert solution.cp.shape == (system.n_panels,)
        assert solution.v_tangential.shape == (system.n_panels,)
        assert solution.source_strengths.shape == (system.n_panels,)


class TestBasePanel:
    """Closing a finite trailing edge."""

    def test_sharp_section_gets_no_base_panel(self) -> None:
        system = HessSmithSystem(naca("0012", 201, closed_te=True))
        assert not system.has_base_panel
        assert system.n_panels == 200

    def test_blunt_section_gains_exactly_one_panel(self) -> None:
        system = HessSmithSystem(naca("0012", 201, closed_te=False))
        assert system.has_base_panel
        assert system.n_panels == 201

    def test_base_panel_closes_the_contour(self) -> None:
        system = HessSmithSystem(naca("0012", 201, closed_te=False))
        assert np.allclose(system.ends[-1], system.starts[0])

    def test_base_panel_normal_points_aft(self) -> None:
        system = HessSmithSystem(naca("0012", 201, closed_te=False))
        assert system.normals[-1, 0] > 0.99

    def test_kutta_pair_excludes_the_base_panel(self) -> None:
        system = HessSmithSystem(naca("0012", 201, closed_te=False))
        upper, lower = system.kutta_indices
        assert upper == 0
        assert lower == system.n_panels - 2

    def test_net_source_strength_is_essentially_zero(self) -> None:
        """A closed body cannot create mass; the sources must cancel."""
        for closed in (True, False):
            system = HessSmithSystem(naca("0012", 321, closed_te=closed))
            solution = system.solve(np.deg2rad(5.0), validate=False)
            net = float(np.sum(solution.source_strengths * system.lengths))
            assert abs(net) < 2e-3

    def test_blunt_and_sharp_sections_give_similar_lift(self) -> None:
        """A 0.25% chord base should not move the lift much."""
        sharp = HessSmithSystem(naca("0012", 321, closed_te=True)).solve(
            np.deg2rad(5.0), validate=False
        )
        blunt = HessSmithSystem(naca("0012", 321, closed_te=False)).solve(
            np.deg2rad(5.0), validate=False
        )
        assert blunt.cl_pressure == pytest.approx(sharp.cl_pressure, rel=0.02)
