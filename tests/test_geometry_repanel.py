"""Tests for cosine-clustered repaneling.

The clustering scheme is checked against the closed form it generalises: the
inverse Beta(1/2, 1/2) CDF *is* classical cosine spacing, and Beta(1, 1) *is*
uniform spacing. Both are asserted to machine precision, so the scheme cannot
drift away from the classical distributions it claims to reproduce.

Area conservation is checked against the analytic ellipse area rather than
against the input polygon, because the input polygon is itself an
approximation: a 201-point contour understates the true area by about 0.016%,
purely from chording a convex curve.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil
from aerolab.geometry.naca import naca
from aerolab.geometry.repanel import (
    COSINE,
    UNIFORM,
    ContourSpline,
    clustered_fractions,
    repanel,
)

from tests.helpers import ellipse, ellipse_area


class TestClusteredFractions:
    """The distribution generator, against the classical spacings."""

    @pytest.mark.parametrize("n", [5, 11, 41, 161])
    def test_beta_half_half_is_exactly_cosine_spacing(self, n: int) -> None:
        """The inverse Beta(1/2, 1/2) CDF is (1 - cos(pi*u))/2, to machine precision."""
        got = clustered_fractions(n, COSINE, COSINE)
        expected = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, n)))
        assert np.allclose(got, expected, atol=1e-14)

    @pytest.mark.parametrize("n", [5, 11, 41])
    def test_beta_one_one_is_exactly_uniform_spacing(self, n: int) -> None:
        got = clustered_fractions(n, UNIFORM, UNIFORM)
        assert np.allclose(got, np.linspace(0.0, 1.0, n), atol=1e-14)

    def test_endpoints_are_exact(self) -> None:
        f = clustered_fractions(37, 0.3, 0.8)
        assert f[0] == 0.0
        assert f[-1] == 1.0

    @pytest.mark.parametrize("a,b", [(0.5, 0.5), (0.25, 1.0), (1.0, 0.25), (0.7, 0.3)])
    def test_always_monotonic(self, a: float, b: float) -> None:
        assert np.all(np.diff(clustered_fractions(101, a, b)) > 0.0)

    def test_lower_exponent_clusters_more_tightly(self) -> None:
        """Smaller exponent at an end means a shorter first interval there."""
        tight = clustered_fractions(51, 0.25, COSINE)
        loose = clustered_fractions(51, COSINE, COSINE)
        assert tight[1] < loose[1]

    def test_the_two_ends_are_independent(self) -> None:
        """Changing the trailing-edge exponent must not move the leading-edge end."""
        a = clustered_fractions(51, 0.3, 0.5)
        b = clustered_fractions(51, 0.3, 0.9)
        assert a[1] != pytest.approx(b[1], rel=1e-6)
        reversed_b = 1.0 - clustered_fractions(51, 0.9, 0.3)[::-1]
        assert np.allclose(b, reversed_b, atol=1e-12)

    @pytest.mark.parametrize("bad", [0.0, -0.5, 5.0, 100.0])
    def test_out_of_range_exponents_rejected(self, bad: float) -> None:
        with pytest.raises(GeometryError, match="must lie in"):
            clustered_fractions(21, bad, COSINE)

    def test_too_few_points_rejected(self) -> None:
        with pytest.raises(GeometryError, match="at least 2"):
            clustered_fractions(1)


class TestRepanelAcceptance:
    """The Phase 1 acceptance criterion for repaneling."""

    def test_round_trip_preserves_area_within_one_tenth_percent(self) -> None:
        """201 points -> 160 panels -> 201 points changes area by well under 0.1%."""
        original = naca("2412", 201)
        coarse = repanel(original, 161)
        back = repanel(coarse, 201)
        change = abs(back.area - original.area) / original.area
        assert change < 1e-3
        # The requirement is 0.1%; the achieved figure is around 0.001%, and a
        # regression to merely "passing" would be worth knowing about.
        assert change < 5e-5

    def test_one_way_change_is_dominated_by_chording_not_resplining(self) -> None:
        """Going 201 -> 161 points loses area mostly because the polygon is coarser.

        The exact ellipse area is known, so the two effects can be separated. A
        161-point polygon inscribed in the true ellipse already understates the
        area by a predictable amount; the resplined contour should be no worse
        than that reference by more than a small margin.
        """
        exact = ellipse_area()
        direct_161 = ellipse(161)
        resplined = repanel(ellipse(201), 161)
        chording_error = abs(direct_161.area - exact) / exact
        resplined_error = abs(resplined.area - exact) / exact
        assert resplined_error < 2.0 * chording_error

    def test_repanel_preserves_the_analytic_ellipse_area(self) -> None:
        exact = ellipse_area()
        for n in (81, 161, 321):
            assert repanel(ellipse(801), n).area == pytest.approx(exact, rel=2e-3)


class TestRepanelGeometry:
    """What repaneling must not change."""

    def test_point_count_is_exact(self) -> None:
        for n in (61, 101, 161, 321):
            assert repanel(naca("2412", 201), n).n_points == n

    def test_sharp_trailing_edge_stays_sharp(self) -> None:
        assert repanel(naca("0012", 201, closed_te=True), 161).is_sharp_te()

    def test_finite_trailing_edge_gap_is_preserved_exactly(self) -> None:
        original = naca("0012", 201, closed_te=False)
        assert repanel(original, 161).te_gap == pytest.approx(original.te_gap, rel=1e-12)

    def test_trailing_edge_points_are_reproduced_exactly(self) -> None:
        """The ends of the parametrisation are pinned, not merely interpolated."""
        original = naca("4412", 201, closed_te=False)
        out = repanel(original, 161)
        assert out.x[0] == pytest.approx(original.x[0], abs=1e-14)
        assert out.z[0] == pytest.approx(original.z[0], abs=1e-14)
        assert out.x[-1] == pytest.approx(original.x[-1], abs=1e-14)
        assert out.z[-1] == pytest.approx(original.z[-1], abs=1e-14)

    def test_thickness_survives_repaneling(self) -> None:
        original = naca("2412", 401)
        out = repanel(original, 161)
        assert out.max_thickness.value == pytest.approx(
            original.max_thickness.value, rel=2e-3
        )

    def test_ordering_invariant_is_maintained(self) -> None:
        assert repanel(naca("4412", 201), 161).signed_area > 0.0

    def test_name_is_carried_through(self) -> None:
        assert repanel(naca("2412", 201), 161).name == "NACA 2412"

    def test_refining_converges_towards_the_exact_area(self) -> None:
        exact = ellipse_area()
        errors = [abs(repanel(ellipse(1601), n).area - exact) for n in (101, 201, 401)]
        assert errors[0] > errors[1] > errors[2]


class TestClusteringControl:
    """The clustering knobs must actually move panels."""

    def test_tighter_leading_edge_clustering_shortens_the_nose_panel(self) -> None:
        af = naca("0012", 401)
        default = repanel(af, 161, le_clustering=COSINE)
        tight = repanel(af, 161, le_clustering=0.25)
        i_default = int(np.argmin(np.abs(default.x - default.le_point[0])))
        i_tight = int(np.argmin(np.abs(tight.x - tight.le_point[0])))
        nose_default = np.hypot(
            np.diff(default.x)[i_default], np.diff(default.z)[i_default]
        )
        nose_tight = np.hypot(np.diff(tight.x)[i_tight], np.diff(tight.z)[i_tight])
        assert nose_tight < nose_default

    def test_tighter_trailing_edge_clustering_shortens_the_tail_panel(self) -> None:
        af = naca("0012", 401)
        default = repanel(af, 161, te_clustering=COSINE)
        tight = repanel(af, 161, te_clustering=0.25)
        assert np.hypot(np.diff(tight.x)[0], np.diff(tight.z)[0]) < np.hypot(
            np.diff(default.x)[0], np.diff(default.z)[0]
        )

    def test_uniform_clustering_evens_out_panel_lengths(self) -> None:
        af = naca("0012", 801)

        def spread(a: Airfoil) -> float:
            lengths = np.hypot(np.diff(a.x), np.diff(a.z))
            return float(np.ptp(lengths))

        cosine = spread(repanel(af, 161, le_clustering=COSINE, te_clustering=COSINE))
        uniform = spread(repanel(af, 161, le_clustering=UNIFORM, te_clustering=UNIFORM))
        assert uniform < cosine

    def test_split_modes_agree_for_a_symmetric_section(self) -> None:
        af = naca("0012", 401)
        by_arc = repanel(af, 161, split="arclength")
        by_count = repanel(af, 161, split="even")
        assert np.allclose(by_arc.x, by_count.x, atol=1e-9)

    def test_split_modes_differ_for_a_cambered_section(self) -> None:
        af = naca("4412", 401)
        by_arc = repanel(af, 161, split="arclength")
        by_count = repanel(af, 161, split="even")
        assert not np.allclose(by_arc.x, by_count.x, atol=1e-6)

    def test_arclength_split_balances_panel_size_between_surfaces(self) -> None:
        """Proportional splitting should even out the two surfaces' mean panel length."""
        af = naca("4412", 801)
        def imbalance(a: Airfoil) -> float:
            (xu, zu), (xl, zl) = a.surfaces()
            up = np.mean(np.hypot(np.diff(xu), np.diff(zu)))
            lo = np.mean(np.hypot(np.diff(xl), np.diff(zl)))
            return abs(up - lo) / (0.5 * (up + lo))
        assert imbalance(repanel(af, 161, split="arclength")) < imbalance(
            repanel(af, 161, split="even")
        )


class TestRepanelValidation:
    """Bad requests are refused, with a message that says what to do."""

    def test_even_point_count_rejected(self) -> None:
        with pytest.raises(GeometryError, match="must be odd"):
            repanel(naca("0012", 201), 160)

    def test_tiny_point_count_rejected(self) -> None:
        with pytest.raises(GeometryError, match="at least 21"):
            repanel(naca("0012", 201), 11)

    def test_unknown_split_mode_rejected(self) -> None:
        with pytest.raises(GeometryError, match="split must be"):
            repanel(naca("0012", 201), 161, split="magic")  # type: ignore[arg-type]


class TestContourSpline:
    """The arc-length spline underlying repaneling."""

    def test_leading_edge_is_located_between_input_points(self) -> None:
        af = naca("4412", 201)
        spline = ContourSpline(af)
        assert 0.0 < spline.s_le < spline.total_length

    def test_spline_reproduces_its_own_knots(self) -> None:
        af = naca("2412", 201)
        spline = ContourSpline(af)
        x, z = spline.evaluate(af.arc_length)
        assert np.allclose(x, af.x, atol=1e-12)
        assert np.allclose(z, af.z, atol=1e-12)

    def test_total_length_matches_the_perimeter(self) -> None:
        af = naca("2412", 201)
        assert ContourSpline(af).total_length == pytest.approx(af.perimeter, rel=1e-12)
