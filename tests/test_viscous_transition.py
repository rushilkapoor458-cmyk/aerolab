"""Tests for transition prediction.

The e^N method is checked against the one case where the answer is well
established: a flat plate in a quiet stream transitions at Re_x of roughly
2.5e6 to 3e6 for N = 9. That is a genuine external reference, and it exercises
the neutral curve, the growth rate and the integration together.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.viscous import transition as tr

pytestmark = pytest.mark.validation

BLASIUS_SHAPE_FACTOR = 2.59


def blasius_surface(reynolds: float, n: int = 4000):
    """Flat-plate arrays for a given chord Reynolds number.

    ``theta = 0.664 sqrt(nu s / Ue)`` non-dimensionalised by chord becomes
    ``theta = 0.664 sqrt(s / Re)``, with H constant at the Blasius value.
    """
    s = np.linspace(1e-6, 1.0, n)
    ue = np.ones_like(s)
    theta = 0.664 * np.sqrt(s / reynolds)
    h = np.full_like(s, BLASIUS_SHAPE_FACTOR)
    return s, ue, theta, h


class TestMichel:
    def test_matches_the_published_form(self) -> None:
        re_s = np.array([1e6])
        expected = 1.174 * (1.0 + 22400.0 / 1e6) * 1e6**0.46
        assert float(tr.michel_criterion(re_s)[0]) == pytest.approx(expected, rel=1e-12)

    def test_correction_term_matters_only_at_low_reynolds_number(self) -> None:
        assert 1.0 + 22400.0 / 1e6 == pytest.approx(1.022, abs=1e-3)
        assert 1.0 + 22400.0 / 1e5 == pytest.approx(1.224, abs=1e-3)

    def test_threshold_rises_with_reynolds_number(self) -> None:
        re_s = np.logspace(5, 7, 40)
        assert np.all(np.diff(tr.michel_criterion(re_s)) > 0.0)

    def test_flat_plate_transition_is_in_the_accepted_range(self) -> None:
        """Michel on a flat plate should transition around Re_x of 2 to 3 million."""
        reynolds = 1e7
        s, ue, theta, h = blasius_surface(reynolds)
        result = tr.predict_transition(s, ue, theta, h, reynolds, method="michel")
        assert result.occurred
        re_x = reynolds * result.s
        assert 1.5e6 < re_x < 4.0e6

    def test_non_positive_argument_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="must be positive"):
            tr.michel_criterion(np.array([0.0]))


class TestStabilityCorrelations:
    def test_critical_reynolds_number_at_the_blasius_shape_factor(self) -> None:
        """The classical flat-plate neutral point is Re_theta of about 200."""
        critical = float(
            tr.critical_reynolds_theta(np.array([BLASIUS_SHAPE_FACTOR]))[0]
        )
        assert 190.0 < critical < 260.0

    def test_critical_reynolds_number_falls_as_the_layer_thickens(self) -> None:
        """An adverse gradient destabilises the layer, so higher H goes unstable sooner."""
        h = np.linspace(2.2, 3.5, 40)
        assert np.all(np.diff(tr.critical_reynolds_theta(h)) < 0.0)

    def test_growth_rate_at_the_blasius_shape_factor(self) -> None:
        rate = float(tr.amplification_rate(np.array([BLASIUS_SHAPE_FACTOR]))[0])
        assert rate == pytest.approx(0.0107, abs=1e-3)

    def test_growth_rate_rises_with_shape_factor(self) -> None:
        """Above H = 2.4 a thicker layer amplifies faster, as it must."""
        h = np.linspace(2.5, 4.0, 40)
        assert np.all(np.diff(tr.amplification_rate(h)) > 0.0)

    def test_growth_rate_has_a_minimum_near_h_of_2374(self) -> None:
        """Below that the fit turns back up, which is unphysical but harmless.

        The bracketed expression changes sign at H = 2.374 and the square root
        makes the rate rise again on either side. A favourable gradient should
        stabilise the layer, not destabilise it, so the low-H branch is wrong —
        but it never acts, because the neutral curve keeps Re_theta below
        critical there and no amplification is accumulated at all.
        """
        h = np.linspace(1.8, 4.0, 300)
        rate = tr.amplification_rate(h)
        assert h[int(np.argmin(rate))] == pytest.approx(2.374, abs=0.02)

    def test_growth_rate_is_never_zero(self) -> None:
        """The 0.25 under the root keeps the rate positive at every H."""
        assert np.all(tr.amplification_rate(np.linspace(1.5, 4.0, 60)) > 0.0)

    def test_singular_shape_factor_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="at or below 1"):
            tr.critical_reynolds_theta(np.array([1.0]))


class TestEnvelopeMethod:
    def test_flat_plate_transition_reynolds_number(self) -> None:
        """N = 9 on a flat plate gives Re_x between 2 and 3.5 million.

        This is the standard quiet-stream figure and is the single most
        informative check on the method: it exercises the neutral curve, the
        growth rate and the integration at once.
        """
        reynolds = 1e7
        s, ue, theta, h = blasius_surface(reynolds)
        result = tr.predict_transition(s, ue, theta, h, reynolds, n_crit=9.0)
        assert result.occurred
        re_x = reynolds * result.s
        assert 2.0e6 < re_x < 3.5e6

    def test_lower_n_transitions_earlier(self) -> None:
        """The whole point of the parameter: a noisier tunnel trips sooner."""
        reynolds = 1e7
        s, ue, theta, h = blasius_surface(reynolds)
        locations = [
            tr.predict_transition(s, ue, theta, h, reynolds, n_crit=n).s
            for n in (4.0, 6.0, 9.0, 12.0)
        ]
        assert all(a < b for a, b in zip(locations, locations[1:]))

    def test_amplification_factor_is_monotonic(self) -> None:
        """Disturbances that have grown do not un-grow."""
        reynolds = 1e7
        s, ue, theta, h = blasius_surface(reynolds)
        result = tr.predict_transition(s, ue, theta, h, reynolds, n_crit=9.0)
        assert np.all(np.diff(result.n_factor) >= -1e-15)

    def test_no_amplification_below_the_neutral_point(self) -> None:
        reynolds = 1e7
        s, ue, theta, h = blasius_surface(reynolds)
        result = tr.predict_transition(s, ue, theta, h, reynolds, n_crit=9.0)
        re_theta = reynolds * ue * theta
        critical = tr.critical_reynolds_theta(h)
        stable = re_theta < critical
        assert np.all(result.n_factor[stable] == 0.0)

    def test_stable_layer_reports_no_transition(self) -> None:
        reynolds = 1e4
        s, ue, theta, h = blasius_surface(reynolds)
        result = tr.predict_transition(s, ue, theta, h, reynolds, n_crit=9.0)
        assert not result.occurred
        assert result.s is None

    def test_unknown_method_is_refused(self) -> None:
        reynolds = 1e6
        s, ue, theta, h = blasius_surface(reynolds)
        with pytest.raises(ValidityRangeError, match="must be 'en' or 'michel'"):
            tr.predict_transition(s, ue, theta, h, reynolds, method="magic")

    def test_non_positive_n_crit_is_refused(self) -> None:
        reynolds = 1e6
        s, ue, theta, h = blasius_surface(reynolds)
        with pytest.raises(ValidityRangeError, match="n_crit must be positive"):
            tr.predict_transition(s, ue, theta, h, reynolds, n_crit=0.0)

    def test_mack_correlation_gives_sensible_turbulence_levels(self) -> None:
        """Sanity on the documented N-to-turbulence mapping, N = -8.43 - 2.4 ln(Tu)."""
        def n_from_tu(tu: float) -> float:
            return -8.43 - 2.4 * np.log(tu)

        assert n_from_tu(0.001) == pytest.approx(8.2, abs=0.2)
        assert n_from_tu(0.01) == pytest.approx(2.6, abs=0.2)
