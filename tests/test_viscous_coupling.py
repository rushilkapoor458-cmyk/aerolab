"""Tests for viscous-inviscid coupling.

Phase 4 is **incomplete**. The transpiration machinery and the wake are built
and verified; the fixed-point iteration built on them still does not converge,
for a reason that is structural rather than a coding error and is recorded in
NOTES.md as L4.3. These tests therefore split three ways:

- applying a transpiration velocity, and the wake's own physics, are asserted
  normally;
- what the wake demonstrably fixed is measured, so the gain is not just claimed;
- the remaining failure is asserted only to **fail honestly** — to report its
  residual and to refuse to return an unconverged answer.

The last group is deliberate. A test that pinned a converged drag would have to
be deleted when the simultaneous solve lands; a test that pins "this limit
cycles in the last 1% of chord, and says so" documents the current state and
will fail loudly, in the right place, once it is fixed.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem
from aerolab.viscous.boundary_layer import solve_boundary_layer
from aerolab.viscous.coupling import solve_coupled, transpiration_velocity
from aerolab.viscous.wake import (
    build_wake,
    solve_wake_layer,
    wake_influence,
    wake_source_strengths,
)

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def system():
    return HessSmithSystem(naca("0012", 301))


@pytest.fixture(scope="module")
def layer(system):
    return solve_boundary_layer(system.solve(0.0, validate=False), 3e6, validate=False)


class TestTranspirationInThePanelSolver:
    """Applying a prescribed normal velocity through the surface."""

    def test_zero_transpiration_reproduces_the_solid_wall_solution(self, system) -> None:
        blown = system.solve(0.0, transpiration=np.zeros(system.n_panels), validate=False)
        plain = system.solve(0.0, validate=False)
        assert np.allclose(blown.cp, plain.cp)
        assert blown.cl_pressure == pytest.approx(plain.cl_pressure, abs=1e-14)

    def test_transpiration_enters_linearly(self, system) -> None:
        """Superposition must hold: the matrix is unchanged, only the right side."""
        rng = np.random.default_rng(0)
        a = 1e-3 * rng.standard_normal(system.n_panels)
        b = 1e-3 * rng.standard_normal(system.n_panels)
        base = system.solve(0.0, validate=False).source_strengths
        only_a = system.solve(0.0, transpiration=a, validate=False).source_strengths
        only_b = system.solve(0.0, transpiration=b, validate=False).source_strengths
        both = system.solve(0.0, transpiration=a + b, validate=False).source_strengths
        assert np.allclose(both, only_a + only_b - base, atol=1e-12)

    def test_the_boundary_condition_is_actually_enforced(self, system) -> None:
        """V . n must equal the requested normal velocity at every control point."""
        rng = np.random.default_rng(1)
        blowing = 1e-3 * rng.standard_normal(system.n_panels)
        solution = system.solve(0.0, transpiration=blowing, validate=False)

        from aerolab.inviscid.influence import panel_influence, self_influence

        source, vortex = panel_influence(
            system.starts, system.ends, system.control_points
        )
        self_source, self_vortex = self_influence(system.tangents, -system.normals)
        diagonal = np.arange(system.n_panels)
        source[diagonal, diagonal, :] = self_source
        vortex[diagonal, diagonal, :] = self_vortex

        induced = np.einsum("imk,m->ik", source, solution.source_strengths)
        induced += solution.vortex_strength * np.sum(vortex, axis=1)
        total = induced + system.freestream(0.0, 1.0)[None, :]
        normal_velocity = np.sum(total * system.normals, axis=1)
        assert np.allclose(normal_velocity, blowing, atol=1e-10)

    def test_wrong_length_is_refused(self, system) -> None:
        with pytest.raises(ValidityRangeError, match="transpiration must have shape"):
            system.solve(0.0, transpiration=np.zeros(3), validate=False)

    def test_blowing_near_the_trailing_edge_unloads_the_section(self, system) -> None:
        """This is the mechanism by which coupling produces stall.

        A thickening boundary layer blows hardest near the trailing edge. That
        displacement decambers the section, reduces the aft loading and so
        reduces lift — which is what bends the coupled lift curve over. Asserted
        on the aft 20% only, because uniform blowing over the whole surface adds
        a *net* source instead, which accelerates the flow and slightly lowers
        Cp everywhere; that is a different effect and not the one at issue.
        """
        alpha = np.deg2rad(4.0)
        plain = system.solve(alpha, validate=False)
        aft = system.control_points[:, 0] > 0.8
        blowing = np.where(aft, 5e-3, 0.0)
        blown = system.solve(alpha, transpiration=blowing, validate=False)
        assert blown.cl_pressure < plain.cl_pressure

    def test_uniform_blowing_adds_a_net_source(self, system) -> None:
        """Sanity on the sign convention: outward means outward."""
        blowing = np.full(system.n_panels, 5e-3)
        flux = float(np.sum(blowing * system.lengths))
        assert flux > 0.0
        solution = system.solve(0.0, transpiration=blowing, validate=False)
        # Far downstream the added mass shows up as an outward radial velocity.
        probe = np.array([[60.0, 0.0]])
        radial = float(solution.velocity_at(probe)[0, 0]) - 1.0
        assert radial > 0.0


class TestTranspirationVelocity:
    """Turning a boundary layer into a normal velocity."""

    def test_symmetric_section_gives_a_symmetric_transpiration(
        self, system, layer
    ) -> None:
        """The sharpest available check on the station-to-panel mapping.

        A symmetric section at zero incidence must produce no lift no matter how
        it is blown, because the blowing is itself symmetric. An earlier version
        dropped the stagnation location when rebuilding a truncated edge
        distribution, mapped every panel to the wrong station, and returned
        Cl = 0.42 here. See NOTES.md, D4.1.
        """
        blowing = transpiration_velocity(layer, system)
        result = system.solve(0.0, transpiration=blowing, validate=False)
        assert abs(result.cl_pressure) < 1e-6

    def test_blowing_is_outward_over_most_of_the_surface(self, system, layer) -> None:
        """The displacement flux grows downstream, so v_n is positive."""
        blowing = transpiration_velocity(layer, system)
        assert float(np.mean(blowing > 0.0)) > 0.8

    def test_magnitude_is_small_away_from_the_trailing_edge(
        self, system, layer
    ) -> None:
        """Forward of 90% chord the blowing is a fraction of a percent of freestream.

        This is the physically expected size. The trailing edge is excluded
        because that is exactly where the method breaks; see
        ``TestTheTrailingEdgeBlocker``.
        """
        blowing = transpiration_velocity(layer, system)
        forward = system.control_points[:, 0] < 0.9
        assert float(np.max(np.abs(blowing[forward]))) < 0.02

    def test_a_base_panel_is_not_blown(self) -> None:
        system = HessSmithSystem(naca("0012", 301, closed_te=False))
        layer = solve_boundary_layer(
            system.solve(0.0, validate=False), 3e6, validate=False
        )
        assert system.has_base_panel
        assert transpiration_velocity(layer, system)[-1] == 0.0

    def test_higher_reynolds_number_gives_less_blowing(self, system) -> None:
        """A thinner boundary layer displaces less."""
        magnitudes = []
        for reynolds in (1e6, 3e6, 1e7):
            layer = solve_boundary_layer(
                system.solve(0.0, validate=False), reynolds, validate=False
            )
            blowing = transpiration_velocity(layer, system)
            forward = system.control_points[:, 0] < 0.9
            magnitudes.append(float(np.mean(np.abs(blowing[forward]))))
        assert all(a > b for a, b in zip(magnitudes, magnitudes[1:]))


class TestWake:
    """Wake geometry, boundary layer, and sources."""

    @pytest.fixture
    def wake(self):
        return build_wake(naca("0012", 301), 0.0)

    def test_leaves_from_the_trailing_edge(self, wake) -> None:
        airfoil = naca("0012", 301)
        assert np.allclose(wake.starts[0], airfoil.te_point, atol=1e-12)

    def test_runs_along_the_freestream(self, wake) -> None:
        assert np.allclose(wake.tangents, np.array([1.0, 0.0]), atol=1e-12)

    def test_direction_follows_incidence(self) -> None:
        alpha = np.deg2rad(8.0)
        tilted = build_wake(naca("0012", 301), alpha)
        assert np.allclose(
            tilted.tangents[0], [np.cos(alpha), np.sin(alpha)], atol=1e-12
        )

    def test_length_and_panel_count(self, wake) -> None:
        assert wake.n_panels == 40
        assert wake.total_length == pytest.approx(1.0, rel=1e-12)

    def test_spacing_is_uniform_by_default(self, wake) -> None:
        """Clustering at the trailing edge was tried and is wrong here; see A4.7."""
        assert np.ptp(wake.lengths) < 1e-12

    @pytest.mark.parametrize("bad", [{"length": 0.0}, {"n_panels": 2}, {"growth": 0.5}])
    def test_bad_geometry_is_refused(self, bad) -> None:
        with pytest.raises(ValidityRangeError):
            build_wake(naca("0012", 301), 0.0, **bad)

    def test_momentum_thickness_is_conserved_at_constant_pressure(self) -> None:
        """A wake in a uniform stream neither gains nor loses momentum.

        This is the sharpest available check on the wake momentum integral: with
        dUe/ds = 0 and no wall shear, dtheta/ds must be exactly zero.
        """
        s = np.linspace(0.0, 1.0, 60)
        layer = solve_wake_layer(s, np.ones_like(s), 0.006, 0.012, 3e6)
        assert np.allclose(layer.theta, 0.006, rtol=1e-6)

    def test_shape_factor_relaxes_towards_one(self) -> None:
        """Entrainment thins the wake profile; H falls monotonically."""
        s = np.linspace(0.0, 2.0, 80)
        layer = solve_wake_layer(s, np.ones_like(s), 0.006, 0.015, 3e6)
        assert np.all(np.diff(layer.shape_factor) < 0.0)
        assert layer.shape_factor[0] == pytest.approx(2.5, rel=0.02)
        assert layer.shape_factor[-1] < 1.6

    def test_displacement_thickness_falls_along_the_wake(self) -> None:
        s = np.linspace(0.0, 2.0, 80)
        layer = solve_wake_layer(s, np.ones_like(s), 0.006, 0.015, 3e6)
        assert layer.delta_star[-1] < layer.delta_star[0]

    def test_an_adverse_gradient_thickens_the_wake(self) -> None:
        s = np.linspace(0.0, 1.0, 60)
        slowing = solve_wake_layer(s, 1.0 - 0.2 * s, 0.006, 0.012, 3e6)
        assert slowing.theta[-1] > 0.006

    def test_zero_momentum_thickness_is_refused(self) -> None:
        s = np.linspace(0.0, 1.0, 20)
        with pytest.raises(ValidityRangeError, match="must be positive"):
            solve_wake_layer(s, np.ones_like(s), 0.0, 0.01, 3e6)

    def test_sources_are_negative_where_the_wake_thins(self) -> None:
        s = np.linspace(0.0, 1.0, 60)
        layer = solve_wake_layer(s, np.ones_like(s), 0.006, 0.015, 3e6)
        assert float(np.mean(wake_source_strengths(layer))) < 0.0

    def test_wake_influence_decays_with_distance(self, wake) -> None:
        strengths = np.full(wake.n_panels, 0.05)
        near = wake_influence(wake, strengths, np.array([[1.5, 0.3]]))
        far = wake_influence(wake, strengths, np.array([[1.5, 3.0]]))
        assert np.linalg.norm(near) > np.linalg.norm(far)


class TestWhatTheWakeFixed:
    """The wake exists to relieve the trailing edge. Measure that it does."""

    def test_it_relieves_the_trailing_edge_stagnation(self) -> None:
        """Ue at the last surface panel rises from 0.67 to about 0.83."""
        airfoil = naca("0012", 301)
        system = HessSmithSystem(airfoil)
        uncoupled = abs(system.solve(0.0, validate=False).v_tangential[0])
        coupled = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=60, validate=False
        )
        assert uncoupled == pytest.approx(0.674, abs=0.02)
        assert abs(coupled.panel.v_tangential[0]) > 0.78

    def test_the_blowing_velocity_is_now_bounded(self) -> None:
        """Without the wake this reached 0.61 of freestream; now it stays under 0.5."""
        airfoil = naca("0012", 301)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=60, validate=False
        )
        assert float(np.max(np.abs(result.transpiration))) < 0.5

    def test_it_no_longer_destroys_the_outer_solution(self) -> None:
        """Before the wake, the edge velocity hit zero and Thwaites refused."""
        airfoil = naca("0012", 301)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=60, validate=False
        )
        n_surface = airfoil.n_points - 1
        assert float(np.min(np.abs(result.panel.v_tangential[:n_surface]))) > 1e-3

    def test_symmetry_still_holds_with_the_wake(self) -> None:
        airfoil = naca("0012", 301)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=40, validate=False
        )
        assert abs(result.cl) < 1e-5


class TestTheRemainingBlocker:
    """It still does not converge. Pinned so the next fix is detectable.

    These describe a **defect**, not a desired property. When the surface and
    wake layers are solved simultaneously with the outer flow they should start
    failing, which is the point.
    """

    def test_the_iteration_limit_cycles(self) -> None:
        """The residual stalls near 1 and does not fall with relaxation.

        A step that is merely too large gets better as the step shrinks. This
        does not: measured residuals at relaxation 0.20 / 0.10 / 0.05 / 0.02 are
        1.03 / 0.64 / 0.95 / 1.97 after 250 iterations. That is a fixed point
        which is not attracting.
        """
        airfoil = naca("0012", 301)
        residuals = [
            solve_coupled(
                airfoil, 0.0, 3e6, relaxation=w, max_iterations=70, validate=False
            ).residual
            for w in (0.2, 0.05)
        ]
        assert all(r > 0.05 for r in residuals)

    def test_the_residual_lives_in_the_last_one_percent_of_chord(self) -> None:
        """74% of it comes from 20 panels aft of x/c = 0.99.

        Everywhere else the coupling has effectively converged. What remains is
        the surface layer being marched to a control point 3e-5 chords from the
        trailing edge, which a sequential scheme cannot resolve.
        """
        airfoil = naca("0012", 301)
        system = HessSmithSystem(airfoil)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=80, validate=False
        )
        layer = solve_boundary_layer(result.panel, 3e6, validate=False)
        error = np.abs(transpiration_velocity(layer, system) - result.transpiration)
        aft = system.control_points[:, 0] > 0.99
        assert error[aft].sum() / error.sum() > 0.5
        assert error[aft].max() > 3.0 * error[~aft].max()

    def test_the_drag_is_nonetheless_stable_across_the_cycle(self) -> None:
        """It oscillates by a few percent about 0.0062, not wildly.

        Reported for information. An oscillating value is still not a converged
        one and the solver continues to refuse to return it.
        """
        airfoil = naca("0012", 301)
        drags = [
            solve_coupled(
                airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=n, validate=False
            ).cd
            for n in (60, 70, 80)
        ]
        assert (max(drags) - min(drags)) / np.mean(drags) < 0.06
        assert 0.0055 < np.mean(drags) < 0.0070

    def test_it_still_refuses_to_return_an_unconverged_answer(self) -> None:
        with pytest.raises(ConvergenceError, match="did not converge"):
            solve_coupled(naca("0012", 301), 0.0, 3e6, max_iterations=20)

    def test_the_failure_reports_its_diagnostics(self) -> None:
        try:
            solve_coupled(naca("0012", 301), 0.0, 3e6, max_iterations=20)
        except ConvergenceError as error:
            assert error.iterations == 20
            assert np.isfinite(error.residual)
            assert error.tolerance > 0.0
        else:
            pytest.fail("expected a ConvergenceError")


class TestValidation:
    def test_bad_relaxation_is_refused(self) -> None:
        for bad in (0.0, -0.1, 1.5):
            with pytest.raises(ValidityRangeError, match="relaxation must lie"):
                solve_coupled(naca("0012", 121), 0.0, 3e6, relaxation=bad)

    def test_bad_reynolds_number_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="must be positive"):
            solve_coupled(naca("0012", 121), 0.0, -1.0)
