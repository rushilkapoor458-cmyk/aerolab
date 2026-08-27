"""Tests for the boundary-layer closure relations.

These are curve fits, so the meaningful checks are against the exact solutions
they approximate — Blasius for the flat plate, Falkner-Skan at stagnation — and
against the internal consistency of the fits themselves, where a mismatch would
put a step into the middle of an integration.

The size of each fit's error is asserted, not just its presence. Thwaites is
1.0% high on flat-plate momentum thickness and 0.8% high on the shape factor;
pinning those means a future change that improves *or* degrades them shows up
here rather than silently shifting every drag prediction.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import brentq

from aerolab.exceptions import ValidityRangeError
from aerolab.viscous import closure

pytestmark = pytest.mark.validation

#: Exact Blasius flat-plate results.
BLASIUS_SHAPE_FACTOR = 2.59
BLASIUS_THETA_COEFF = 0.664       # theta = 0.664 sqrt(nu x / Ue)
BLASIUS_CF_COEFF = 0.4409         # cf = 0.4409 / Re_theta


class TestThwaitesCorrelations:
    """Thwaites' fits against exact laminar solutions."""

    def test_flat_plate_shape_factor(self) -> None:
        """At zero pressure gradient the fit gives 2.61 against Blasius 2.59."""
        h = float(closure.thwaites_shape_factor(np.array([0.0]))[0])
        assert h == pytest.approx(2.61, abs=1e-9)
        assert abs(h - BLASIUS_SHAPE_FACTOR) / BLASIUS_SHAPE_FACTOR == pytest.approx(
            0.0077, abs=5e-4
        )

    def test_flat_plate_skin_friction(self) -> None:
        """l(0) = 0.22 gives cf = 0.44/Re_theta against Blasius 0.4409/Re_theta.

        The shear correlation is an order of magnitude more accurate than the
        shape-factor one, which is why Thwaites predicts skin friction well even
        where it predicts thickness only moderately.
        """
        shear = float(closure.thwaites_shear(np.array([0.0]))[0])
        assert shear == pytest.approx(0.22, abs=1e-9)
        cf_coefficient = 2.0 * shear
        assert cf_coefficient == pytest.approx(BLASIUS_CF_COEFF, rel=2.1e-3)

    def test_both_branches_agree_at_zero(self) -> None:
        """The step at lambda = 0 is 1.4e-4 in H and exactly zero in l.

        The small mismatch is in the published fit, not in this implementation:
        the negative branch gives 2.088 + 0.0731/0.14 = 2.610143 while the
        positive branch gives 2.61 exactly. It is three orders of magnitude
        below the fit's own 0.8% error against Blasius, so it is pinned rather
        than patched — smoothing it would misrepresent the correlation.
        """
        eps = 1e-12
        below = float(closure.thwaites_shape_factor(np.array([-eps]))[0])
        above = float(closure.thwaites_shape_factor(np.array([eps]))[0])
        assert below - above == pytest.approx(1.429e-4, rel=0.01)

        below = float(closure.thwaites_shear(np.array([-eps]))[0])
        above = float(closure.thwaites_shear(np.array([eps]))[0])
        assert below == pytest.approx(above, abs=1e-11)

    def test_shape_factor_rises_towards_separation(self) -> None:
        lam = np.linspace(-0.09, 0.09, 50)
        h = closure.thwaites_shape_factor(lam)
        assert np.all(np.diff(h) < 0.0)      # H falls as lambda rises

    def test_stagnation_value(self) -> None:
        """At the stagnation value lambda = 0.075 the fit gives H = 2.358.

        The exact Hiemenz stagnation-flow value is 2.216, so Thwaites is 6.4%
        high here — its worst region, and the reason predicted transition is
        slightly sensitive to the leading-edge treatment.
        """
        h = float(closure.thwaites_shape_factor(np.array([0.075]))[0])
        assert h == pytest.approx(2.3585, abs=1e-3)
        assert (h - 2.216) / 2.216 == pytest.approx(0.064, abs=5e-3)

    def test_shear_vanishes_near_the_separation_threshold(self) -> None:
        """The correlation's own zero-shear point is lambda = -0.0898."""
        root = brentq(
            lambda lam: float(closure.thwaites_shear(np.array([lam]))[0]),
            -0.0999,
            -0.05,
        )
        assert root == pytest.approx(-0.0898, abs=5e-4)

    def test_separation_threshold_is_the_more_accurate_of_the_two(self) -> None:
        """On Howarth's flow, -0.0842 beats the correlation's own -0.0898.

        For ``Ue = U0(1 - x/L)`` Thwaites gives in closed form
        ``lambda = -0.075 [1 - (1-xi)^6] / (1-xi)^6``. The exact separation of
        this flow is at xi = 0.1198. Solving for each threshold:

            -0.0898 -> xi = 0.1230  (+2.7%)
            -0.0842 -> xi = 0.1179  (-1.6%)

        which is why the package uses -0.0842 even though it is not where the
        shear correlation vanishes. See NOTES.md, A3.2.
        """

        def howarth_xi(threshold: float) -> float:
            def residual(xi: float) -> float:
                u = (1.0 - xi) ** 6
                return -0.075 * (1.0 - u) / u - threshold

            return brentq(residual, 1e-6, 0.5)

        exact = 0.1198
        loose = howarth_xi(-0.0898)
        tight = howarth_xi(closure.LAMBDA_SEPARATION)
        assert loose == pytest.approx(0.1230, abs=5e-4)
        assert tight == pytest.approx(0.1179, abs=5e-4)
        assert abs(tight - exact) < abs(loose - exact)

    @pytest.mark.parametrize("bad", [-0.2, 0.3])
    def test_outside_the_fitted_range_is_refused(self, bad: float) -> None:
        with pytest.raises(ValidityRangeError, match="outside the range"):
            closure.thwaites_shape_factor(np.array([bad]))
        with pytest.raises(ValidityRangeError, match="outside the range"):
            closure.thwaites_shear(np.array([bad]))


class TestHeadCorrelations:
    """Head's entrainment relations and their mutual consistency."""

    @pytest.mark.parametrize("h", [1.2, 1.4, 1.6, 1.8, 2.2, 2.6, 2.9])
    def test_h1_and_its_inverse_round_trip(self, h: float) -> None:
        """The forward and inverse fits must invert each other to 0.1%.

        This is the test that caught the branches being paired the wrong way
        round. With them swapped the round trip is still accurate at H = 1.4,
        where a turbulent run starts, but returns 3.999 for 2.6 — so the error
        grows through the adverse gradient and surfaced as premature trailing-
        edge separation rather than as an obviously wrong number.
        """
        h1 = closure.head_h1_from_h(np.array([h]))
        recovered = float(closure.head_h_from_h1(h1)[0])
        assert recovered == pytest.approx(h, rel=1e-3)

    def test_the_branch_switches_line_up(self) -> None:
        """Both relations change branch at the same place, H = 1.6 / H1 = 5.3.

        A mismatch here would put a small step into the middle of every
        turbulent integration, in the shape-factor range airfoils spend most of
        their time in.
        """
        h1_at_switch = float(closure.head_h1_from_h(np.array([1.6]))[0])
        assert h1_at_switch == pytest.approx(5.3, rel=0.02)

        eps = 1e-9
        below = float(closure.head_h_from_h1(np.array([5.3 - eps]))[0])
        above = float(closure.head_h_from_h1(np.array([5.3 + eps]))[0])
        assert below == pytest.approx(above, rel=3e-3)
        assert below == pytest.approx(1.60, rel=0.01)

    def test_h1_falls_as_h_rises(self) -> None:
        h = np.linspace(1.15, 2.9, 60)
        assert np.all(np.diff(closure.head_h1_from_h(h)) < 0.0)

    def test_h_is_unbounded_as_h1_approaches_its_floor(self) -> None:
        """H1 tends to 3.3 as H grows, which is how separation shows up."""
        large = closure.head_h1_from_h(np.array([2.9]))
        assert float(large[0]) < 3.6
        assert float(closure.head_h_from_h1(np.array([3.3001]))[0]) > 5.0

    def test_h1_at_or_below_its_floor_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="at or below 3.3"):
            closure.head_h_from_h1(np.array([3.3]))

    def test_entrainment_is_finite_at_the_shape_factor_floor(self) -> None:
        """F uses an offset of 3.0 while the inverse uses 3.3; F stays bounded."""
        assert float(closure.head_entrainment(np.array([3.3]))[0]) == pytest.approx(
            0.0643, rel=0.01
        )

    def test_entrainment_falls_as_h1_rises(self) -> None:
        h1 = np.linspace(3.4, 12.0, 50)
        assert np.all(np.diff(closure.head_entrainment(h1)) < 0.0)

    def test_entrainment_singularity_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="at or below 3.0"):
            closure.head_entrainment(np.array([3.0]))


class TestLudwiegTillmann:
    """Turbulent skin friction."""

    def test_matches_the_published_form(self) -> None:
        h, re_theta = 1.4, 5000.0
        expected = 0.246 * 10.0 ** (-0.678 * h) * re_theta**-0.268
        assert float(
            closure.ludwieg_tillmann_cf(np.array([h]), np.array([re_theta]))[0]
        ) == pytest.approx(expected, rel=1e-12)

    def test_typical_flat_plate_value(self) -> None:
        """At H = 1.4 and Re_theta = 5000, cf is about 0.0027."""
        cf = float(closure.ludwieg_tillmann_cf(np.array([1.4]), np.array([5000.0]))[0])
        assert 0.0020 < cf < 0.0035

    def test_falls_with_shape_factor_and_reynolds_number(self) -> None:
        base = closure.ludwieg_tillmann_cf(np.array([1.4]), np.array([5000.0]))
        higher_h = closure.ludwieg_tillmann_cf(np.array([2.0]), np.array([5000.0]))
        higher_re = closure.ludwieg_tillmann_cf(np.array([1.4]), np.array([20000.0]))
        assert higher_h < base
        assert higher_re < base

    def test_stays_positive_near_separation(self) -> None:
        """It does not vanish at separation, which is why it cannot detect it."""
        cf = float(closure.ludwieg_tillmann_cf(np.array([2.8]), np.array([5000.0]))[0])
        assert cf > 0.0

    def test_laminar_reynolds_number_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="below 100"):
            closure.ludwieg_tillmann_cf(np.array([1.4]), np.array([50.0]))

    def test_out_of_range_shape_factor_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="outside the range"):
            closure.ludwieg_tillmann_cf(np.array([4.0]), np.array([5000.0]))
