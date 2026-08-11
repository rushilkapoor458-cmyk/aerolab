"""The simultaneous Newton solver: its parts, and what it reproduces.

Structured to isolate blame. The interaction operator is checked against a full
nonlinear panel solve; the boundary layer is checked on prescribed edge
velocities with exact answers; only then is the coupled solver checked. When a
coupled number is wrong, these say which half is at fault — which is how the
trailing-edge momentum defect was found.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry import naca
from aerolab.inviscid import HessSmithSystem
from aerolab.viscous import closure
from aerolab.viscous.falkner_skan import solve_falkner_skan
from aerolab.viscous.newton import (
    _head_h1,
    _jacobian,
    _laminar_cf_reth,
    _laminar_diss_reth,
    _laminar_h_star,
    _residuals,
    build_interaction,
    build_layout,
    newton_polar,
    solve_newton,
    solve_prescribed,
)
from aerolab.viscous.wake import build_wake, wake_influence

RE = 3.0e6


@pytest.fixture(scope="module")
def rig():
    airfoil = naca("2412", 121)
    alpha = np.deg2rad(5.0)
    system = HessSmithSystem(airfoil)
    wake = build_wake(airfoil, alpha, n_panels=25)
    inviscid = system.solve(alpha, validate=False)
    layout = build_layout(system, wake, inviscid)
    operator = build_interaction(system, wake, layout, alpha)
    return airfoil, alpha, system, wake, layout, operator


class TestSmoothClosure:
    """The unguarded copies must be the same formulas, not merely similar."""

    @pytest.mark.parametrize(
        "smooth, public, low, high",
        [
            (_laminar_h_star, closure.laminar_h_star, 1.3, 6.0),
            (_laminar_cf_reth, closure.laminar_cf_reynolds_theta, 1.3, 6.0),
            (_laminar_diss_reth, closure.laminar_dissipation_reynolds_theta, 1.3, 6.0),
        ],
    )
    def test_matches_the_public_relation(self, smooth, public, low, high):
        h = np.linspace(low, high, 200)
        assert np.allclose(smooth(h.astype(complex)).real, public(h), rtol=1e-12)

    def test_head_h1_matches_the_published_fit_away_from_its_jump(self):
        # Away from the soft floor at H = 1.13 and from the blended jump at 1.6.
        h = np.concatenate([np.linspace(1.35, 1.5, 60), np.linspace(1.75, 3.0, 60)])
        assert np.allclose(
            _head_h1(h.astype(complex)).real, closure.head_h1_from_h(h), rtol=3e-3
        )

    def test_head_h1_is_continuous_where_the_published_fit_is_not(self):
        # The published pair jumps by 0.023 at H = 1.6. Newton cannot converge
        # across a jump, so the smooth copy blends it; this asserts the jump is
        # really there in the published form and really gone in the smooth one.
        published = abs(
            float(closure.head_h1_from_h(1.6 - 1e-9))
            - float(closure.head_h1_from_h(1.6 + 1e-9))
        )
        assert published > 0.02
        smooth = abs(
            float(_head_h1(np.array([1.6 - 1e-9 + 0j])).real[0])
            - float(_head_h1(np.array([1.6 + 1e-9 + 0j])).real[0])
        )
        assert smooth < 1e-6

    def test_head_sensitivity_collapses_which_is_why_h_is_capped(self):
        def slope(h):
            return float(_head_h1(np.array([h + 1e-30j])).imag[0] / 1e-30)

        assert abs(slope(1.4)) > 10.0
        assert abs(slope(4.0)) < 0.05
        assert abs(slope(1.4)) / abs(slope(4.0)) > 100.0

    def test_closure_accepts_shape_factors_the_guarded_versions_refuse(self):
        # Intermediate Newton iterates stray outside the fitted range and must
        # not raise on the way to a good solution.
        extreme = np.array([1.05 + 0j, 12.0 + 0j])
        assert np.all(np.isfinite(_head_h1(extreme).real))
        assert np.all(np.isfinite(_laminar_h_star(extreme).real))


class TestInteractionOperator:
    def test_inviscid_edge_velocity_matches_the_panel_solution(self, rig):
        _, alpha, system, _, layout, operator = rig
        panel = system.solve(alpha, validate=False)
        surface = layout.side < 2
        direct = layout.sign[surface] * panel.v_tangential[layout.panel[surface]]
        assert np.allclose(operator.ue_inviscid[surface], direct, atol=1e-13)

    def test_response_is_exact_against_a_full_nonlinear_solve(self, rig):
        """The whole method rests on this matrix being right, not approximate."""
        _, alpha, system, wake, layout, operator = rig
        rng = np.random.default_rng(0)
        mass = 1e-3 * rng.normal(size=layout.n_stations) * np.exp(-layout.s)

        rates = operator.derivative @ mass
        surface = layout.side < 2
        transpiration = np.zeros(system.n_panels)
        transpiration[layout.panel[surface]] = rates[surface]
        strengths = np.zeros(wake.n_panels)
        strengths[layout.panel[~surface]] = rates[~surface]
        solved = system.solve(
            alpha,
            transpiration=transpiration,
            external_velocity=wake_influence(wake, strengths, system.control_points),
            validate=False,
        )

        predicted = operator.edge_velocity(mass)[surface]
        actual = layout.sign[surface] * solved.v_tangential[layout.panel[surface]]
        assert np.max(np.abs(predicted - actual)) < 1e-13

    def test_response_is_linear(self, rig):
        _, _, _, _, layout, operator = rig
        rng = np.random.default_rng(1)
        a = 1e-4 * rng.normal(size=layout.n_stations)
        b = 1e-4 * rng.normal(size=layout.n_stations)
        combined = operator.edge_velocity(2.0 * a + 3.0 * b) - operator.ue_inviscid
        parts = 2.0 * (operator.edge_velocity(a) - operator.ue_inviscid) + 3.0 * (
            operator.edge_velocity(b) - operator.ue_inviscid
        )
        assert np.allclose(combined, parts, atol=1e-15)

    def test_stagnation_point_moves_aft_on_the_lower_surface_with_incidence(self):
        airfoil = naca("0012", 121)
        system = HessSmithSystem(airfoil)
        found = []
        for degrees in (0.0, 4.0, 8.0):
            alpha = np.deg2rad(degrees)
            wake = build_wake(airfoil, alpha, n_panels=15)
            layout = build_layout(system, wake, system.solve(alpha, validate=False))
            found.append(layout.stagnation_s)
        assert found[0] < found[1] < found[2]


class TestJacobian:
    def test_matches_central_differences(self, rig):
        from aerolab.viscous.newton import (
            _build_problem,
            _initial_state,
            _turbulent_weights,
        )

        airfoil, _, _, _, layout, operator = rig
        n = layout.n_stations
        left = np.concatenate(
            [
                np.arange(layout.side_slice(i).start, layout.side_slice(i).stop - 1)
                for i in range(3)
            ]
        )
        problem = _build_problem(
            layout, operator, RE, airfoil.te_gap,
            _turbulent_weights(layout, left, left + 1, [0.3, 0.3]),
        )
        state = _initial_state(layout, operator.ue_inviscid, RE, airfoil.te_gap)

        analytic = _jacobian(state, problem)
        numeric = np.zeros_like(analytic)
        for column in range(3 * n):
            step = 1e-6 * max(abs(state[column]), 1e-8)
            up, down = state.copy(), state.copy()
            up[column] += step
            down[column] -= step
            numeric[:, column] = (
                _residuals(up.astype(complex), problem).real
                - _residuals(down.astype(complex), problem).real
            ) / (2.0 * step)

        scale = max(np.max(np.abs(numeric)), 1e-12)
        assert np.max(np.abs(analytic - numeric)) / scale < 1e-6


class TestPrescribedBoundaryLayer:
    """Exact answers, so the boundary layer can be blamed or cleared alone."""

    def test_blasius_momentum_thickness(self):
        reynolds = 1e6
        s = np.linspace(0.02, 1.0, 300)
        layer = solve_prescribed(
            s, np.ones_like(s), reynolds,
            theta_initial=0.664 * np.sqrt(0.02 / reynolds), shape_initial=2.59110,
        )
        exact = 0.664 * np.sqrt(s / reynolds)
        assert np.max(np.abs(layer.theta - exact) / exact) < 1e-3

    def test_blasius_shape_factor_is_held(self):
        reynolds = 1e6
        s = np.linspace(0.02, 1.0, 300)
        layer = solve_prescribed(
            s, np.ones_like(s), reynolds,
            theta_initial=0.664 * np.sqrt(0.02 / reynolds), shape_initial=2.59110,
        )
        assert np.max(np.abs(layer.shape_factor - 2.59110)) < 1e-3

    def test_blasius_skin_friction(self):
        reynolds = 1e6
        s = np.linspace(0.02, 1.0, 300)
        layer = solve_prescribed(
            s, np.ones_like(s), reynolds,
            theta_initial=0.664 * np.sqrt(0.02 / reynolds), shape_initial=2.59110,
        )
        exact = 0.664 / np.sqrt(reynolds * s)
        assert abs(layer.cf[-1] - exact[-1]) / exact[-1] < 1e-3

    @pytest.mark.parametrize("beta, tolerance", [(0.0, 1e-3), (-0.1, 2e-3), (-0.15, 8e-3)])
    def test_self_similar_flows_hold_their_exact_shape_factor(self, beta, tolerance):
        """A Falkner-Skan flow has constant H; the solver must not drift off it."""
        exact = solve_falkner_skan(beta)
        reynolds = 1e7
        m = beta / (2.0 - beta)
        x = np.linspace(0.05, 1.0, 300)
        theta = (
            exact.delta_2 * x ** ((1 - m) / 2)
            / (np.sqrt(reynolds) * np.sqrt((m + 1) / 2))
        )
        layer = solve_prescribed(
            x, x**m, reynolds,
            theta_initial=float(theta[0]), shape_initial=exact.h,
        )
        assert abs(layer.shape_factor[-1] - exact.h) / exact.h < tolerance
        assert abs(layer.theta[-1] - theta[-1]) / theta[-1] < 3e-3

    def test_howarth_reaches_separation_late_by_a_documented_amount(self):
        """Ue = U0(1 - x/L) separates at x/L = 0.1198 exactly."""
        reynolds = 1e8
        s = np.linspace(0.002, 0.128, 600)
        layer = solve_prescribed(
            s, 1.0 - s, reynolds,
            theta_initial=0.664 * np.sqrt(0.002 / reynolds), shape_initial=2.59110,
            validate=False, max_iterations=120,
        )
        where = float(np.interp(4.029, layer.shape_factor, s))
        assert 0.120 < where < 0.135, f"separation at x/L = {where:.4f}"

    def test_the_prescribed_problem_keeps_the_goldstein_singularity(self):
        """Failing at separation is correct here; the coupled solver must not."""
        reynolds = 1e8
        s = np.linspace(0.002, 0.128, 600)
        layer = solve_prescribed(
            s, 1.0 - s, reynolds,
            theta_initial=0.664 * np.sqrt(0.002 / reynolds), shape_initial=2.59110,
            validate=False, max_iterations=120,
        )
        assert not layer.converged
        with pytest.raises(ConvergenceError):
            solve_prescribed(
                s, 1.0 - s, reynolds,
                theta_initial=0.664 * np.sqrt(0.002 / reynolds),
                shape_initial=2.59110, max_iterations=120,
            )

    def test_rejects_a_zero_edge_velocity_rather_than_dividing_by_it(self):
        s = np.linspace(0.0, 1.0, 20)
        with pytest.raises(ValidityRangeError, match="positive"):
            solve_prescribed(s, np.zeros_like(s), 1e6)

    def test_rejects_a_non_monotone_grid(self):
        s = np.array([0.0, 0.2, 0.1, 0.3])
        with pytest.raises(ValidityRangeError, match="increasing"):
            solve_prescribed(s, np.ones(4), 1e6)


class TestCoupledSolver:
    def test_converges_where_the_sequential_method_could_not(self):
        result = solve_newton(naca("0012", 161), np.deg2rad(4.0), RE)
        assert result.converged
        assert result.residual < 1e-9
        assert result.iterations <= 15

    def test_convergence_is_quadratic(self):
        result = solve_newton(naca("0012", 161), np.deg2rad(4.0), RE)
        history = result.history[result.history > 1e-13]
        assert history.size >= 3
        # Each step should roughly square the previous error once close.
        assert history[-1] < history[-2] ** 1.5

    def test_a_symmetric_section_at_zero_incidence_has_no_lift(self):
        result = solve_newton(naca("0012", 161), 0.0, RE)
        assert abs(result.cl) < 1e-6

    def test_a_symmetric_section_at_zero_incidence_is_symmetric(self):
        result = solve_newton(naca("0012", 161), 0.0, RE)
        assert result.transition_s[0] == pytest.approx(result.transition_s[1], rel=1e-6)

    def test_profile_drag_matches_published_data(self):
        """NACA 0012, Re = 3e6: Abbott and von Doenhoff give Cd = 0.0060."""
        result = solve_newton(naca("0012", 161), 0.0, RE)
        assert result.cd == pytest.approx(0.0060, rel=0.12)

    def test_transition_lands_where_xfoil_puts_it(self):
        """NACA 0012 at zero incidence, Re = 3e6, N = 9: near x/c = 0.45-0.50."""
        result = solve_newton(naca("0012", 161), 0.0, RE)
        assert 0.40 < result.transition_s[0] < 0.55

    def test_transition_moves_forward_on_the_suction_side_with_incidence(self):
        forward = [
            solve_newton(naca("0012", 161), np.deg2rad(d), RE).transition_s[0]
            for d in (0.0, 2.0, 4.0)
        ]
        assert forward[0] > forward[1] > forward[2]

    def test_the_viscous_solution_carries_less_lift_than_the_inviscid_one(self):
        airfoil = naca("0012", 161)
        alpha = np.deg2rad(4.0)
        inviscid = HessSmithSystem(airfoil).solve(alpha).cl_pressure
        viscous = solve_newton(airfoil, alpha, RE).cl
        assert 0.75 * inviscid < viscous < inviscid

    def test_drag_is_insensitive_to_where_the_wake_is_truncated(self):
        short = solve_newton(naca("0012", 161), 0.0, RE, wake_length=3.0)
        long = solve_newton(naca("0012", 161), 0.0, RE, wake_length=8.0)
        assert short.cd == pytest.approx(long.cd, rel=0.02)
        assert long.wake_convergence < 1e-3

    def test_drag_falls_with_reynolds_number(self):
        drags = [
            solve_newton(naca("0012", 161), 0.0, re).cd for re in (1e6, 3e6, 6e6)
        ]
        assert drags[0] > drags[1] > drags[2]

    def test_a_cambered_section_lifts_at_zero_incidence(self):
        result = solve_newton(naca("2412", 161), 0.0, RE)
        assert 0.15 < result.cl < 0.30

    def test_result_is_independent_of_panel_count(self):
        # 161 and 201 agree; 121 does not, giving Cd = 0.0087 against 0.0065.
        # The boundary layer needs the trailing-edge panels resolved, so the
        # panel count that suffices for an inviscid solve does not suffice here.
        coarse = solve_newton(naca("0012", 161), np.deg2rad(4.0), RE)
        fine = solve_newton(naca("0012", 201), np.deg2rad(4.0), RE)
        assert coarse.cl == pytest.approx(fine.cl, rel=0.01)
        assert coarse.cd == pytest.approx(fine.cd, rel=0.03)

    def test_a_lower_amplification_threshold_moves_transition_forward(self):
        early = solve_newton(naca("0012", 161), 0.0, RE, n_crit=5.0)
        late = solve_newton(naca("0012", 161), 0.0, RE, n_crit=11.0)
        assert early.transition_s[0] < late.transition_s[0]
        assert early.cd > late.cd

    def test_non_convergence_raises_rather_than_returning_a_number(self):
        with pytest.raises(ConvergenceError):
            solve_newton(naca("0012", 161), np.deg2rad(4.0), RE, max_outer=1,
                         max_iterations=1)

    def test_a_bad_reynolds_number_is_refused(self):
        with pytest.raises(ValidityRangeError, match="Reynolds"):
            solve_newton(naca("0012", 121), 0.0, -1.0)

    def test_the_closure_range_is_reported_not_hidden(self):
        result = solve_newton(naca("0012", 161), np.deg2rad(4.0), RE)
        assert result.max_shape_factor > 3.0
        assert not result.closure_in_range
        assert "closure extrapolated" in repr(result)


class TestSweep:
    def test_continuation_produces_a_monotone_lift_curve(self):
        alphas = np.deg2rad(np.arange(0.0, 5.1, 1.0))
        results = newton_polar(naca("0012", 161), alphas, RE)
        assert all(r.converged for r in results)
        lift = np.array([r.cl for r in results])
        assert np.all(np.diff(lift) > 0.0)

    def test_the_lift_slope_is_close_to_thin_aerofoil_theory(self):
        alphas = np.deg2rad(np.arange(0.0, 5.1, 1.0))
        results = newton_polar(naca("0012", 161), alphas, RE)
        slope = np.polyfit(alphas, [r.cl for r in results], 1)[0]
        # Viscous decambering puts it below the inviscid 6.91/rad.
        assert 5.4 < slope < 6.6

    def test_drag_has_a_minimum_near_zero_incidence_for_a_symmetric_section(self):
        alphas = np.deg2rad(np.array([-4.0, -2.0, 0.0, 2.0, 4.0]))
        results = newton_polar(naca("0012", 161), alphas, RE)
        drags = np.array([r.cd for r in results])
        assert int(np.argmin(drags)) == 2
