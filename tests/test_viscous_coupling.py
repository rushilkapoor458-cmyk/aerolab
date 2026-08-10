"""Tests for viscous-inviscid coupling.

Phase 4 is **incomplete**. The transpiration machinery below is verified and
correct; the fixed-point iteration built on it does not converge, for a reason
that is structural rather than a coding error and is recorded in NOTES.md as
L4.1. These tests therefore split cleanly in two:

- everything about *applying* a transpiration velocity is asserted normally;
- the iteration is asserted only to **fail honestly** — to report its residual
  and to refuse to return an unconverged answer.

The second group is deliberate. A test that pinned a converged drag would have
to be deleted when the wake model lands; a test that pins "this does not
converge, and says so" documents the current state and will fail loudly, in the
right place, once it does.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ConvergenceError, ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem
from aerolab.viscous.boundary_layer import solve_boundary_layer
from aerolab.viscous.coupling import (
    solve_coupled,
    transpiration_velocity,
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


class TestTheTrailingEdgeBlocker:
    """Why the iteration does not converge. Pinned so the fix is detectable.

    These assertions describe a **defect**, not a desired property. When a wake
    model lands they should start failing, and that is the point: the failure
    will land here rather than showing up as a quietly wrong lift curve.
    """

    def test_displacement_growth_at_the_trailing_edge_is_unphysical(
        self, layer
    ) -> None:
        """d(delta*)/ds reaches 1.75 where a free shear layer spreads at 0.1 to 0.2."""
        upper = layer.upper
        growth = (upper.delta_star[-1] - upper.delta_star[-2]) / (
            upper.s[-1] - upper.s[-2]
        )
        assert growth > 1.0

    def test_that_growth_produces_an_enormous_blowing_velocity(
        self, system, layer
    ) -> None:
        """max |v_n| is 0.61 of freestream, all of it in the last 2% of chord."""
        blowing = transpiration_velocity(layer, system)
        peak = int(np.argmax(np.abs(blowing)))
        assert abs(blowing[peak]) > 0.4
        assert system.control_points[peak, 0] > 0.98

    def test_the_iteration_does_not_converge(self) -> None:
        """Pinned as the current state of Phase 4. See NOTES.md, L4.1."""
        airfoil = naca("0012", 301, closed_te=False)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=60, validate=False
        )
        assert not result.converged
        assert result.residual > result.tolerance

    def test_it_refuses_to_return_an_unconverged_answer(self) -> None:
        """The no-silent-failure contract, which does hold."""
        airfoil = naca("0012", 301, closed_te=False)
        with pytest.raises(ConvergenceError, match="did not converge"):
            solve_coupled(airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=20)

    def test_the_failure_reports_its_diagnostics(self) -> None:
        airfoil = naca("0012", 301, closed_te=False)
        try:
            solve_coupled(airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=20)
        except ConvergenceError as error:
            assert error.iterations == 20
            assert np.isfinite(error.residual)
            assert error.tolerance > 0.0
        else:
            pytest.fail("expected a ConvergenceError")

    def test_history_is_recorded_for_diagnosis(self) -> None:
        airfoil = naca("0012", 301, closed_te=False)
        result = solve_coupled(
            airfoil, 0.0, 3e6, relaxation=0.1, max_iterations=25, validate=False
        )
        assert result.history.size == result.iterations
        assert result.lift_history.size == result.iterations
        assert np.all(np.isfinite(result.history))


class TestValidation:
    def test_bad_relaxation_is_refused(self) -> None:
        for bad in (0.0, -0.1, 1.5):
            with pytest.raises(ValidityRangeError, match="relaxation must lie"):
                solve_coupled(naca("0012", 121), 0.0, 3e6, relaxation=bad)

    def test_bad_reynolds_number_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="must be positive"):
            solve_coupled(naca("0012", 121), 0.0, -1.0)
