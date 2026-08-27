"""Tests for the integral boundary-layer solver.

Thwaites' quadrature is checked against two exact laminar solutions — Blasius
for the flat plate and Howarth's linearly retarded flow for separation — before
any airfoil is involved. Those fix the laminar half independently of the panel
method, so an airfoil drag that comes out wrong can be attributed.

The acceptance drags are then checked against measured data, and the spread
between the two transition models is asserted explicitly, because that spread is
larger than the acceptance band and is the honest statement of how well profile
drag can be predicted at this level of modelling.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem
from aerolab.viscous import closure
from aerolab.viscous.boundary_layer import (
    _thwaites,
    edge_distributions,
    solve_boundary_layer,
)

pytestmark = pytest.mark.validation

BLASIUS_THETA_COEFF = 0.664


@pytest.fixture(scope="module")
def naca0012_zero():
    return HessSmithSystem(naca("0012", 401)).solve(0.0)


@pytest.fixture(scope="module")
def naca2412_four():
    return HessSmithSystem(naca("2412", 401)).solve(np.deg2rad(4.0))


class TestThwaitesAgainstExactSolutions:
    """The laminar half, before any airfoil is involved."""

    def test_flat_plate_momentum_thickness(self) -> None:
        """Thwaites gives theta = 0.6708 sqrt(s/Re) against Blasius 0.664 - 1.0% high.

        Asserted as a specific ratio rather than a loose tolerance, because this
        1% is a known property of the method and a change in it would mean the
        quadrature had changed.
        """
        reynolds = 1e6
        s = np.linspace(0.0, 1.0, 4000)
        ue = np.ones_like(s)
        theta, _ = _thwaites(s, ue, np.zeros_like(s), reynolds)

        exact = BLASIUS_THETA_COEFF * np.sqrt(s / reynolds)
        ratio = theta[1:] / exact[1:]
        assert np.allclose(ratio, np.sqrt(0.45) / BLASIUS_THETA_COEFF, rtol=1e-6)
        assert float(np.mean(ratio)) == pytest.approx(1.0103, abs=1e-3)

    def test_flat_plate_lambda_is_zero(self) -> None:
        reynolds = 1e6
        s = np.linspace(0.0, 1.0, 500)
        _, lambda_ = _thwaites(s, np.ones_like(s), np.zeros_like(s), reynolds)
        assert np.allclose(lambda_, 0.0)

    def test_stagnation_flow_gives_lambda_of_0075(self) -> None:
        """For Ue = k s the classical result is lambda = 0.075 everywhere."""
        reynolds = 1e6
        k = 3.0
        s = np.linspace(0.0, 0.2, 2000)
        ue = k * s
        theta, lambda_ = _thwaites(s, ue, np.full_like(s, k), reynolds)
        assert np.allclose(lambda_, 0.075, rtol=2e-3)
        assert theta[0] == pytest.approx(np.sqrt(0.075 / (reynolds * k)), rel=1e-12)

    def test_howarth_separation_station(self) -> None:
        """Ue = 1 - s separates at s = 0.1189, against the exact 0.1198."""
        reynolds = 1e6
        s = np.linspace(0.0, 0.15, 20000)
        ue = 1.0 - s
        _, lambda_ = _thwaites(s, ue, np.full_like(s, -1.0), reynolds)
        separated = np.nonzero(lambda_ <= closure.LAMBDA_SEPARATION)[0]
        assert separated.size > 0
        station = float(s[separated[0]])
        assert station == pytest.approx(0.1179, abs=1e-3)
        assert abs(station - 0.1198) / 0.1198 < 0.02

    def test_stagnation_start_without_acceleration_is_refused(self) -> None:
        """Zero edge velocity with no acceleration has no boundary layer to start."""
        s = np.linspace(0.0, 1.0, 100)
        with pytest.raises(ValidityRangeError, match="not accelerating"):
            _thwaites(s, np.zeros_like(s), np.zeros_like(s), 1e6)

    def test_a_decelerating_start_at_finite_velocity_is_allowed(self) -> None:
        """Howarth's flow starts at Ue = 1 with an adverse gradient; that is valid."""
        s = np.linspace(0.0, 0.1, 500)
        theta, _ = _thwaites(s, 1.0 - s, np.full_like(s, -1.0), 1e6)
        assert theta[0] == 0.0
        assert np.all(np.diff(theta) > 0.0)


class TestEdgeDistributions:
    """Splitting the panel solution into two surfaces."""

    def test_stagnation_point_is_at_the_nose_at_zero_incidence(
        self, naca0012_zero
    ) -> None:
        upper, lower = edge_distributions(naca0012_zero)
        assert upper.x[0] == pytest.approx(0.0, abs=2e-3)
        assert lower.x[0] == pytest.approx(0.0, abs=2e-3)

    def test_symmetric_section_at_zero_incidence_has_identical_surfaces(
        self, naca0012_zero
    ) -> None:
        upper, lower = edge_distributions(naca0012_zero)
        assert np.allclose(upper.ue, lower.ue, atol=1e-9)

    def test_edge_velocity_starts_at_zero_and_is_non_negative(
        self, naca2412_four
    ) -> None:
        for edge in edge_distributions(naca2412_four):
            assert edge.ue[0] == pytest.approx(0.0, abs=1e-12)
            assert np.all(edge.ue >= 0.0)

    def test_arc_length_increases_downstream(self, naca2412_four) -> None:
        for edge in edge_distributions(naca2412_four):
            assert np.all(np.diff(edge.s) > 0.0)

    def test_stagnation_moves_to_the_lower_surface_with_incidence(self) -> None:
        """At positive incidence the stagnation point moves aft along the underside."""
        system = HessSmithSystem(naca("0012", 401))
        stations = []
        for alpha_deg in (0.0, 4.0, 8.0):
            solution = system.solve(np.deg2rad(alpha_deg), validate=False)
            lower, _ = edge_distributions(solution)
            stations.append(float(lower.x[0]))
        assert all(a <= b + 1e-6 for a, b in zip(stations, stations[1:]))


class TestAcceptanceDrag:
    """The Phase 3 acceptance cases, against measured data."""

    def test_naca0012_drag_with_michel(self, naca0012_zero) -> None:
        """Michel's criterion lands inside the 0.0058-0.0065 band."""
        result = solve_boundary_layer(
            naca0012_zero, 3e6, method="michel", validate=False
        )
        assert 0.0058 <= result.cd_profile <= 0.0065

    def test_naca0012_drag_with_en_falls_just_below_the_band(
        self, naca0012_zero
    ) -> None:
        """N = 9 gives 0.00569, about 2% under the stated lower bound.

        This is pinned rather than tuned. The measured value is 0.0060, so the
        prediction is 5.2% low, and the reason is known: the calculation is
        uncoupled, so the boundary layer sees the undisplaced inviscid edge
        velocity and comes out too thin. Phase 4 should raise it. See NOTES.md,
        L3.2.
        """
        result = solve_boundary_layer(naca0012_zero, 3e6, method="en", validate=False)
        assert result.cd_profile == pytest.approx(0.00569, rel=0.03)
        assert result.cd_profile < 0.0058

    def test_naca2412_drag_is_within_fifteen_percent_of_measurement(
        self, naca2412_four
    ) -> None:
        """Abbott and von Doenhoff give about 0.0068 at this condition."""
        measured = 0.0068
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        assert abs(result.cd_profile - measured) / measured < 0.15

    def test_transition_model_spread_exceeds_the_acceptance_band(
        self, naca0012_zero
    ) -> None:
        """The honest headline: transition modelling dominates the uncertainty.

        The two criteria differ by about 11% on the same section at the same
        Reynolds number, which is wider than the acceptance band itself. No
        amount of care in the boundary-layer integration narrows that.
        """
        en = solve_boundary_layer(naca0012_zero, 3e6, method="en", validate=False)
        michel = solve_boundary_layer(
            naca0012_zero, 3e6, method="michel", validate=False
        )
        spread = abs(michel.cd_profile - en.cd_profile) / en.cd_profile
        assert spread == pytest.approx(0.11, abs=0.03)
        band_width = (0.0065 - 0.0058) / 0.00615
        assert spread > band_width


class TestPhysicalTrends:
    """Behaviour that must hold whatever the absolute accuracy."""

    def test_drag_falls_with_reynolds_number(self, naca0012_zero) -> None:
        drags = [
            solve_boundary_layer(naca0012_zero, re, validate=False).cd_profile
            for re in (3e5, 1e6, 3e6, 9e6)
        ]
        assert all(a > b for a, b in zip(drags, drags[1:]))

    def test_transition_moves_forward_with_reynolds_number(
        self, naca0012_zero
    ) -> None:
        stations = [
            solve_boundary_layer(naca0012_zero, re, validate=False).upper.transition_x
            for re in (1e6, 3e6, 9e6)
        ]
        assert all(a > b for a, b in zip(stations, stations[1:]))

    def test_lower_n_crit_moves_transition_forward_and_raises_drag(
        self, naca0012_zero
    ) -> None:
        """A noisier tunnel trips earlier and costs more drag."""
        results = [
            solve_boundary_layer(naca0012_zero, 3e6, n_crit=n, validate=False)
            for n in (4.0, 6.0, 9.0, 11.0)
        ]
        stations = [r.upper.transition_x for r in results]
        drags = [r.cd_profile for r in results]
        assert all(a < b for a, b in zip(stations, stations[1:]))
        assert all(a > b for a, b in zip(drags, drags[1:]))

    def test_drag_rises_with_incidence(self) -> None:
        system = HessSmithSystem(naca("0012", 401))
        drags = []
        for alpha_deg in (0.0, 4.0, 8.0):
            solution = system.solve(np.deg2rad(alpha_deg), validate=False)
            drags.append(
                solve_boundary_layer(solution, 3e6, validate=False).cd_profile
            )
        assert all(a < b for a, b in zip(drags, drags[1:]))

    def test_separation_moves_forward_with_incidence(self) -> None:
        system = HessSmithSystem(naca("0012", 401))
        stations = []
        for alpha_deg in (0.0, 6.0, 12.0):
            solution = system.solve(np.deg2rad(alpha_deg), validate=False)
            result = solve_boundary_layer(solution, 3e6, validate=False)
            stations.append(result.upper.turbulent_separation_x)
        assert all(a > b for a, b in zip(stations, stations[1:]))

    def test_momentum_thickness_grows_downstream(self, naca2412_four) -> None:
        """Away from the stagnation region theta only grows.

        The first couple of percent of surface is excluded deliberately. There
        ``Ue`` is proportional to ``s``, which makes theta *constant* rather than
        growing, so the sequence wanders by about 1e-7 on a value of 2e-5 —
        round-off around a flat function, not a physical decrease.
        """
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        for surface in result.surfaces:
            downstream = surface.s > 0.02 * surface.s[-1]
            assert np.all(np.diff(surface.theta[downstream]) > -1e-12)

    def test_momentum_thickness_is_almost_constant_near_stagnation(
        self, naca2412_four
    ) -> None:
        """Ue proportional to s gives theta = sqrt(0.075/(Re k)), independent of s.

        It drifts by a few percent rather than staying exactly flat, because a
        real nose is only approximately a stagnation flow and dUe/ds is itself
        changing. That is why the monotonicity test excludes this region rather
        than tightening its tolerance.
        """
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        near = result.upper.theta[:20]
        assert np.ptp(near) / np.mean(near) < 0.05

    def test_shape_factor_drops_at_transition(self, naca0012_zero) -> None:
        """Laminar H is around 2.5; turbulent starts at 1.4."""
        result = solve_boundary_layer(naca0012_zero, 3e6, validate=False)
        surface = result.upper
        index = surface.transition.index
        assert surface.shape_factor[index - 1] > 2.0
        assert surface.shape_factor[index + 2] < 1.7


class TestNumericalRobustness:
    def test_drag_is_insensitive_to_station_count(self, naca0012_zero) -> None:
        """From 500 stations upward the drag is converged to 0.5%.

        250 stations is genuinely too coarse and comes out 1.4% high, so the
        sweep starts at 500. The default of 1000 sits comfortably inside the
        converged range.
        """
        drags = [
            solve_boundary_layer(naca0012_zero, 3e6, stations=n, validate=False).cd_profile
            for n in (500, 1000, 2000, 3000)
        ]
        assert (max(drags) - min(drags)) / np.mean(drags) < 0.005

    def test_a_coarse_station_count_is_visibly_worse(self, naca0012_zero) -> None:
        """Pinned so the lower bound on usable resolution stays documented."""
        coarse = solve_boundary_layer(
            naca0012_zero, 3e6, stations=250, validate=False
        ).cd_profile
        fine = solve_boundary_layer(
            naca0012_zero, 3e6, stations=2000, validate=False
        ).cd_profile
        assert (coarse - fine) / fine == pytest.approx(0.014, abs=0.006)

    def test_drag_is_insensitive_to_the_assumed_start_shape_factor(
        self, naca0012_zero, monkeypatch
    ) -> None:
        """Varying the post-transition H from 1.3 to 1.5 moves the drag by 4%.

        Not negligible: it is comparable to the width of the whole acceptance
        band, and it is one reason an uncoupled calculation cannot be pushed
        much below 5% accuracy. Pinned so the sensitivity stays visible.
        """
        import aerolab.viscous.boundary_layer as module

        drags = []
        for start_h in (1.3, 1.4, 1.5):
            monkeypatch.setattr(module, "TURBULENT_START_H", start_h)
            drags.append(
                solve_boundary_layer(naca0012_zero, 3e6, validate=False).cd_profile
            )
        assert (max(drags) - min(drags)) / np.mean(drags) < 0.06

    def test_drag_is_insensitive_to_panel_count(self) -> None:
        drags = []
        for n in (241, 401, 641):
            solution = HessSmithSystem(naca("0012", n)).solve(0.0)
            drags.append(
                solve_boundary_layer(solution, 3e6, validate=False).cd_profile
            )
        assert (max(drags) - min(drags)) / np.mean(drags) < 0.03


class TestNoSilentFailures:
    """Every questionable result must announce itself."""

    def test_trailing_edge_separation_does_not_raise(self, naca0012_zero) -> None:
        """It happens on essentially every case and is an artefact, not a failure."""
        result = solve_boundary_layer(naca0012_zero, 3e6)
        assert not result.attached
        assert not result.separation_is_significant()
        assert result.upper.turbulent_separation_x > 0.98

    def test_upstream_separation_raises(self) -> None:
        solution = HessSmithSystem(naca("0012", 401)).solve(
            np.deg2rad(14.0), validate=False
        )
        with pytest.raises(ValidityRangeError, match="forward of the limit"):
            solve_boundary_layer(solution, 3e6)

    def test_the_refusal_can_be_bypassed_deliberately(self) -> None:
        solution = HessSmithSystem(naca("0012", 401)).solve(
            np.deg2rad(14.0), validate=False
        )
        result = solve_boundary_layer(solution, 3e6, validate=False)
        assert result.separation_is_significant()

    def test_negative_reynolds_number_is_refused(self, naca0012_zero) -> None:
        with pytest.raises(ValidityRangeError, match="must be positive"):
            solve_boundary_layer(naca0012_zero, -1.0)


class TestReporting:
    """What the result object exposes."""

    def test_laminar_separation_is_reported_as_a_station(self, naca2412_four) -> None:
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        station = result.upper.laminar_separation_x
        assert station is None or 0.0 < station < 1.0

    def test_transition_method_is_recorded(self, naca0012_zero) -> None:
        result = solve_boundary_layer(naca0012_zero, 3e6, validate=False)
        assert result.upper.transition.method == "en"

    def test_forced_transition_overrides_the_criterion(self, naca0012_zero) -> None:
        """Modelling a trip strip."""
        result = solve_boundary_layer(
            naca0012_zero, 3e6, forced_transition_x=(0.05, 0.05), validate=False
        )
        assert result.upper.transition.method == "forced"
        assert result.upper.transition_x == pytest.approx(0.05, abs=0.01)
        free = solve_boundary_layer(naca0012_zero, 3e6, validate=False)
        assert result.cd_profile > free.cd_profile

    def test_displacement_thickness_is_h_times_theta(self, naca0012_zero) -> None:
        result = solve_boundary_layer(naca0012_zero, 3e6, validate=False)
        for surface in result.surfaces:
            assert np.allclose(
                surface.delta_star, surface.shape_factor * surface.theta
            )

    def test_squire_young_contributions_sum_to_the_total(self, naca2412_four) -> None:
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        total = sum(s.squire_young_drag for s in result.surfaces)
        assert result.cd_profile == pytest.approx(total, rel=1e-12)

    def test_squire_young_matches_its_formula(self, naca0012_zero) -> None:
        result = solve_boundary_layer(naca0012_zero, 3e6, validate=False)
        surface = result.upper
        expected = (
            2.0
            * surface.theta[-1]
            * surface.ue[-1] ** ((surface.shape_factor[-1] + 5.0) / 2.0)
        )
        assert surface.squire_young_drag == pytest.approx(expected, rel=1e-12)

    def test_reynolds_and_alpha_are_carried_through(self, naca2412_four) -> None:
        result = solve_boundary_layer(naca2412_four, 3e6, validate=False)
        assert result.reynolds == 3e6
        assert result.alpha == pytest.approx(np.deg2rad(4.0))
