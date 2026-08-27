"""Exact self-similar solutions, and the closure relations checked against them.

The point of this module is that no laminar closure constant in this package is
taken on trust. Falkner-Skan has an exact solution across the whole range of
shape factors an integral method encounters, so every fit can be measured
against it rather than against its own author.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.viscous.closure import (
    H_SEPARATION_LAMINAR,
    laminar_cf_reynolds_theta,
    laminar_dissipation_reynolds_theta,
    laminar_h_star,
)
from aerolab.viscous.falkner_skan import (
    BETA_SEPARATION,
    falkner_skan_family,
    solve_falkner_skan,
)

# Published values. Hartree (1937), White "Viscous Fluid Flow" table 4-1.
BLASIUS_SHEAR = 0.469600
BLASIUS_H = 2.59110
BLASIUS_H_STAR = 1.57259
BLASIUS_RE_THETA_CF = 0.220530
HIEMENZ_SHEAR = 1.232588
HIEMENZ_H = 2.2162


@pytest.fixture(scope="module")
def blasius():
    return solve_falkner_skan(0.0)


class TestExactSolutions:
    def test_blasius_wall_shear(self, blasius):
        assert blasius.shear == pytest.approx(BLASIUS_SHEAR, rel=1e-5)

    def test_blasius_shape_factor(self, blasius):
        assert blasius.h == pytest.approx(BLASIUS_H, rel=1e-5)

    def test_blasius_kinetic_energy_shape_factor(self, blasius):
        assert blasius.h_star == pytest.approx(BLASIUS_H_STAR, rel=1e-5)

    def test_blasius_skin_friction_group(self, blasius):
        # Re_theta * cf/2 = delta_2 * f''(0) is derived in the docstring; this
        # checks the derivation as well as the solve.
        assert blasius.re_theta_cf_half == pytest.approx(BLASIUS_RE_THETA_CF, rel=1e-4)
        assert blasius.re_theta_cf_half == pytest.approx(
            blasius.delta_2 * blasius.shear, rel=1e-12
        )

    def test_stagnation_point(self):
        solution = solve_falkner_skan(1.0)
        assert solution.shear == pytest.approx(HIEMENZ_SHEAR, rel=1e-5)
        assert solution.h == pytest.approx(HIEMENZ_H, rel=1e-4)

    def test_stagnation_thwaites_parameter(self):
        # theta^2 K / nu = delta_2^2 for beta = 1; this is the leading-edge
        # starting condition the Newton solver uses.
        from aerolab.viscous.newton import LAMBDA_STAGNATION

        solution = solve_falkner_skan(1.0)
        assert solution.delta_2**2 == pytest.approx(LAMBDA_STAGNATION, rel=1e-4)

    def test_shape_factor_rises_monotonically_as_gradient_worsens(self):
        betas = [1.0, 0.5, 0.0, -0.1, -0.15, -0.19]
        shape = [s.h for s in falkner_skan_family(betas)]
        assert np.all(np.diff(shape) > 0.0)

    def test_wall_shear_falls_to_zero_at_separation(self):
        shears = [s.shear for s in falkner_skan_family([0.0, -0.1, -0.18, -0.19])]
        assert np.all(np.diff(shears) < 0.0)
        assert shears[-1] < 0.09

    def test_separation_shape_factor_extrapolates_to_the_published_value(self):
        # The family has a square-root fold at BETA_SEPARATION, so the solver
        # cannot sit exactly on it; H is smooth in u = sqrt(beta - beta_sep) and
        # extrapolates cleanly to the accepted 4.029.
        u = np.array([0.06, 0.05, 0.04, 0.03, 0.02, 0.015, 0.01])
        betas = BETA_SEPARATION + u**2
        shape = np.array([solve_falkner_skan(float(b), tolerance=1e-8).h for b in betas])
        assert np.polyval(np.polyfit(u, shape, 2), 0.0) == pytest.approx(4.029, rel=2e-3)

    def test_domain_is_wide_enough(self, blasius):
        wide = solve_falkner_skan(0.0, eta_max=40.0)
        assert wide.h == pytest.approx(blasius.h, rel=1e-6)

    def test_below_separation_is_refused_not_guessed(self):
        with pytest.raises(ValidityRangeError, match="no attached solution"):
            solve_falkner_skan(BETA_SEPARATION - 0.01)

    def test_velocity_profile_satisfies_its_boundary_conditions(self, blasius):
        assert blasius.f_prime[0] == pytest.approx(0.0, abs=1e-9)
        assert blasius.f[0] == pytest.approx(0.0, abs=1e-9)
        assert blasius.f_prime[-1] == pytest.approx(1.0, abs=1e-9)


class TestLaminarClosureAgainstExactSolutions:
    """Each fit measured against Falkner-Skan, with the error asserted."""

    @pytest.fixture(scope="class")
    def family(self):
        return falkner_skan_family([1.0, 0.5, 0.3, 0.0, -0.1, -0.15, -0.19])

    def test_h_star_fit(self, family):
        error = max(
            abs(float(laminar_h_star(s.h)) - s.h_star) / s.h_star for s in family
        )
        assert error < 1.1e-3, f"H* fit is {100 * error:.2f}% off the exact solution"

    def test_h_star_fit_at_blasius(self, blasius):
        assert float(laminar_h_star(blasius.h)) == pytest.approx(
            blasius.h_star, rel=6e-4
        )

    def test_dissipation_fit(self, family):
        error = 0.0
        for s in family:
            fit = float(laminar_dissipation_reynolds_theta(s.h)) * s.h_star / 2.0
            error = max(error, abs(fit - s.re_theta_cd) / s.re_theta_cd)
        assert error < 6e-3, f"cD fit is {100 * error:.2f}% off the exact solution"

    def test_skin_friction_fit_where_it_is_accurate(self, blasius):
        assert float(laminar_cf_reynolds_theta(blasius.h)) == pytest.approx(
            blasius.re_theta_cf_half, rel=1e-3
        )

    def test_skin_friction_fit_absolute_error_stays_small_near_separation(self, family):
        # The relative error reaches 12% at beta = -0.19, but on a quantity
        # heading for zero; the absolute error is what matters downstream.
        error = max(
            abs(float(laminar_cf_reynolds_theta(s.h)) - s.re_theta_cf_half)
            for s in family
        )
        assert error < 0.01

    def test_separation_shape_factor_of_the_fit_is_what_is_documented(self):
        # The fit puts cf = 0 at H = 4.137 where the exact value is 4.029. This
        # is a known 2.7% error, published in H_SEPARATION_LAMINAR so that every
        # separation prediction downstream inherits a stated accuracy.
        assert float(laminar_cf_reynolds_theta(H_SEPARATION_LAMINAR)) == pytest.approx(
            0.0, abs=1e-3
        )
        assert float(laminar_cf_reynolds_theta(4.029)) > 0.0

    def test_fits_are_continuous_across_their_branch_switches(self):
        for function, switch in (
            (laminar_h_star, 4.0),
            (laminar_cf_reynolds_theta, 7.4),
            (laminar_dissipation_reynolds_theta, 4.0),
        ):
            below = float(function(switch - 1e-7))
            above = float(function(switch + 1e-7))
            assert below == pytest.approx(above, abs=1e-6), (
                f"{function.__name__} jumps at H = {switch}"
            )
