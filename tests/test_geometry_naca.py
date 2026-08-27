"""Tests for the analytic NACA generators.

Every physical assertion here is against a closed-form result or against values
published in Abbott & von Doenhoff — never against a previously recorded output
of this package.

Three closed-form targets do most of the work:

``t_max``
    The thickness polynomial peaks at ``x/c = 0.29983``, where it reaches
    ``1.000288`` times the nominal thickness — not exactly the nominal value.
    Both figures follow from the polynomial itself.
``r_LE = 1.1019 t^2``
    As ``x -> 0`` the thickness tends to ``5*t*a0*sqrt(x)``, a parabola whose
    vertex radius is ``(5*t*a0)^2 / 2 = 1.1019 t^2``.
``area = 2 * integral(y_t) dx``
    Evaluated in closed form from the polynomial coefficients, and compared
    against the shoelace area of the discrete contour.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import GeometryError
from aerolab.geometry.naca import (
    _A0,
    _A1,
    _A2,
    _A3,
    _A4_CLOSED,
    _A4_OPEN,
    _cosine_fourier_coefficients,
    _five_digit_slope,
    camber_line_4digit,
    camber_line_5digit,
    naca,
    naca4,
    naca5,
    solve_five_digit_camber,
    thickness_distribution,
)

pytestmark = pytest.mark.validation

#: Leading-edge radius coefficient: (5*a0)^2 / 2.
LE_RADIUS_COEFF = (5.0 * _A0) ** 2 / 2.0


def analytic_area(thickness: float, closed_te: bool) -> float:
    """Closed-form enclosed area of a symmetric NACA section, in chords squared.

    ``area = 2 * integral_0^1 y_t dx``, and each term of the thickness
    polynomial integrates exactly.
    """
    a4 = _A4_CLOSED if closed_te else _A4_OPEN
    integral = (
        _A0 * (2.0 / 3.0) + _A1 / 2.0 + _A2 / 3.0 + _A3 / 4.0 + a4 / 5.0
    )
    return 10.0 * thickness * integral


def ideal_cl_and_cm(camber) -> tuple[float, float]:
    """Thin-airfoil-theory ``Cl_i`` and ``Cm_c/4`` of a solved 5-digit mean line."""
    slope = _five_digit_slope(
        camber.m, camber.k1, camber.k2_over_k1, camber.reflexed
    )
    a1, a2 = _cosine_fourier_coefficients(slope, camber.m)
    return np.pi * a1, (np.pi / 4.0) * (a2 - a1)


class TestThicknessPolynomial:
    """The thickness form, checked against its own defining properties."""

    def test_closed_coefficients_sum_to_zero(self) -> None:
        """A closed trailing edge means y_t(1) = 0, i.e. the coefficients cancel."""
        total = _A0 + _A1 + _A2 + _A3 + _A4_CLOSED
        assert total == pytest.approx(0.0, abs=1e-12)

    def test_open_coefficients_leave_the_documented_gap(self) -> None:
        """The original polynomial leaves a half-gap of 0.0105*t at the trailing edge."""
        total = _A0 + _A1 + _A2 + _A3 + _A4_OPEN
        assert total == pytest.approx(0.0021, abs=1e-9)
        half_gap = thickness_distribution(np.array([1.0]), 0.12, closed_te=False)[0]
        assert half_gap == pytest.approx(0.0105 * 0.12, rel=1e-9)

    def test_leading_edge_is_parabolic(self) -> None:
        """y_t / sqrt(x) tends to 5*t*a0 as x -> 0, which fixes the nose radius."""
        x = np.array([1e-10, 1e-12, 1e-14])
        ratio = thickness_distribution(x, 0.12) / np.sqrt(x)
        assert np.allclose(ratio, 5.0 * 0.12 * _A0, rtol=1e-5)

    @pytest.mark.parametrize("thickness", [0.06, 0.12, 0.18, 0.24])
    def test_maximum_slightly_exceeds_nominal_thickness(self, thickness: float) -> None:
        """max(2*y_t) is 1.00029 times the nominal thickness, at x/c = 0.2994.

        The overshoot is a property of the NACA polynomial, not of this code: the
        five coefficients were chosen in 1932 to fit a family of measured
        sections, and the resulting quartic peaks at 1.000288 times its nominal
        value. A "12%" section is therefore 12.0035% thick. The ratio is
        identical for every thickness because the polynomial scales linearly.
        Asserted as a fixed ratio rather than a loose tolerance so that a real
        change in the coefficients would fail here. See NOTES.md, A1.2.
        """
        x = np.linspace(0.0, 1.0, 2_000_001)
        full = 2.0 * thickness_distribution(x, thickness, closed_te=False)
        i = int(np.argmax(full))
        assert full[i] / thickness == pytest.approx(1.000288, rel=1e-5)
        assert x[i] == pytest.approx(0.29983, abs=1e-4)

    def test_closing_the_trailing_edge_barely_moves_the_maximum(self) -> None:
        """The closed variant peaks at 1.000119 t, at x/c = 0.29953."""
        x = np.linspace(0.0, 1.0, 2_000_001)
        closed = 2.0 * thickness_distribution(x, 0.12, closed_te=True)
        i = int(np.argmax(closed))
        assert closed[i] / 0.12 == pytest.approx(1.000119, rel=1e-5)
        assert x[i] == pytest.approx(0.29953, abs=1e-4)

    def test_stations_outside_the_chord_are_rejected(self) -> None:
        with pytest.raises(GeometryError, match=r"must lie in \[0, 1\]"):
            thickness_distribution(np.array([-0.1, 0.5]), 0.12)

    def test_non_positive_thickness_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="thickness must be positive"):
            thickness_distribution(np.array([0.5]), 0.0)


class TestNaca0012Acceptance:
    """The Phase 1 acceptance criteria for NACA 0012."""

    @pytest.fixture
    def af(self):
        return naca("0012", 201)

    def test_max_thickness_value(self, af) -> None:
        """Maximum thickness is 0.12c.

        The closed-trailing-edge variant reaches 0.120013c rather than exactly
        0.120000c: closing the trailing edge changes the quartic coefficient
        from -0.1015 to -0.1036, which perturbs the whole polynomial slightly.
        See NOTES.md, A1.1.
        """
        assert af.max_thickness.value == pytest.approx(0.12, abs=5e-5)

    def test_max_thickness_location(self, af) -> None:
        assert af.max_thickness.x == pytest.approx(0.30, abs=0.01)

    def test_trailing_edge_is_closed(self, af) -> None:
        assert af.te_gap < 1e-12
        assert af.is_sharp_te()

    def test_open_trailing_edge_gap_is_analytic(self) -> None:
        """The original polynomial gives a base height of 2 * 0.0105 * t."""
        af = naca("0012", 201, closed_te=False)
        assert af.te_gap == pytest.approx(2.0 * 0.0105 * 0.12, rel=1e-6)

    def test_is_symmetric(self, af) -> None:
        assert af.max_camber.value == pytest.approx(0.0, abs=1e-9)

    def test_leading_edge_radius(self, af) -> None:
        """Nose radius equals the closed-form 1.1019 t^2."""
        assert af.le_radius == pytest.approx(LE_RADIUS_COEFF * 0.12**2, rel=2e-3)

    def test_trailing_edge_included_angle(self, af) -> None:
        """Wedge angle from the analytic surface slope at the trailing edge."""
        a4 = _A4_CLOSED
        slope = 5.0 * 0.12 * (0.5 * _A0 + _A1 + 2 * _A2 + 3 * _A3 + 4 * a4)
        expected = 2.0 * np.arctan(abs(slope))
        assert af.te_included_angle == pytest.approx(expected, rel=5e-3)


class TestGeometricProperties:
    """Areas and nose radii against closed-form values."""

    @pytest.mark.parametrize("code,thickness", [("0006", 0.06), ("0012", 0.12), ("0018", 0.18)])
    def test_area_matches_the_analytic_integral(self, code: str, thickness: float) -> None:
        """Shoelace area converges to the exact integral at second order.

        At 801 points the discrete polygon is within 0.002% of the closed-form
        area; the residual is the polygon cutting the corners of a convex curve,
        which halves fourfold with each doubling of the point count.
        """
        af = naca(code, 801)
        assert af.area == pytest.approx(analytic_area(thickness, True), rel=1e-4)

    def test_area_converges_at_second_order(self) -> None:
        exact = analytic_area(0.12, True)
        errors = [abs(naca("0012", n).area - exact) for n in (201, 401, 801)]
        assert errors[0] / errors[1] == pytest.approx(4.0, rel=0.1)
        assert errors[1] / errors[2] == pytest.approx(4.0, rel=0.1)

    @pytest.mark.parametrize("code,thickness", [("0006", 0.06), ("0012", 0.12), ("0018", 0.18)])
    def test_symmetric_nose_radius(self, code: str, thickness: float) -> None:
        af = naca(code, 201)
        assert af.le_radius == pytest.approx(LE_RADIUS_COEFF * thickness**2, rel=2e-3)

    @pytest.mark.parametrize("code", ["2412", "4412", "23012", "23112"])
    def test_cambered_nose_radius_is_close_to_the_symmetric_value(self, code: str) -> None:
        """A cambered nose stays within about 1% of 1.1019 t^2, in either direction.

        The tolerance is deliberately loose and the direction deliberately
        unasserted. Measured departures run from -0.6% (23012) to +0.7% (4412),
        while the estimator itself wanders by up to 0.8% with point count — the
        scatter is the same size as the effect, so a directional claim would not
        be supportable. See NOTES.md, L1.3.
        """
        af = naca(code, 401)
        assert af.le_radius == pytest.approx(LE_RADIUS_COEFF * 0.12**2, rel=1.5e-2)

    def test_symmetric_nose_radius_is_insensitive_to_point_count(self) -> None:
        """The symmetric case has no such limitation and must stay rock steady."""
        radii = [naca("0012", n).le_radius for n in (201, 801, 3201)]
        assert np.ptp(radii) / np.mean(radii) < 1e-4


class TestFourDigitCamber:
    """The 4-digit mean line against its defining properties."""

    def test_symmetric_sections_have_no_camber(self) -> None:
        y, dy = camber_line_4digit(np.linspace(0, 1, 51), 0.0, 0.0)
        assert np.allclose(y, 0.0)
        assert np.allclose(dy, 0.0)

    @pytest.mark.parametrize("m,p", [(0.02, 0.4), (0.04, 0.4), (0.06, 0.3), (0.02, 0.5)])
    def test_maximum_camber_value_and_location(self, m: float, p: float) -> None:
        """The mean line peaks at exactly m, at exactly x = p."""
        x = np.linspace(0.0, 1.0, 1_000_001)
        y, _ = camber_line_4digit(x, m, p)
        i = int(np.argmax(y))
        assert y[i] == pytest.approx(m, rel=1e-9)
        assert x[i] == pytest.approx(p, abs=1e-5)

    @pytest.mark.parametrize("m,p", [(0.02, 0.4), (0.04, 0.4), (0.06, 0.3)])
    def test_slope_is_continuous_at_the_junction(self, m: float, p: float) -> None:
        """Both arcs must meet with the same height and slope at x = p."""
        eps = 1e-9
        y, dy = camber_line_4digit(np.array([p - eps, p + eps]), m, p)
        assert y[0] == pytest.approx(y[1], abs=1e-12)
        assert dy[0] == pytest.approx(dy[1], abs=1e-8)
        assert dy[0] == pytest.approx(0.0, abs=1e-8)

    @pytest.mark.parametrize("m,p", [(0.02, 0.4), (0.04, 0.4)])
    def test_slope_is_the_derivative_of_the_camber_line(self, m: float, p: float) -> None:
        """Guards against the two branches drifting apart independently."""
        x = np.linspace(0.01, 0.99, 400)
        h = 1e-7
        y_plus, _ = camber_line_4digit(x + h, m, p)
        y_minus, _ = camber_line_4digit(x - h, m, p)
        _, analytic = camber_line_4digit(x, m, p)
        assert np.allclose((y_plus - y_minus) / (2 * h), analytic, atol=1e-6)

    def test_ends_are_on_the_chord_line(self) -> None:
        y, _ = camber_line_4digit(np.array([0.0, 1.0]), 0.04, 0.4)
        assert np.allclose(y, 0.0, atol=1e-15)

    def test_camber_with_zero_position_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="0 < p < 1"):
            camber_line_4digit(np.array([0.5]), 0.04, 0.0)


class TestFourDigitSections:
    """Whole sections generated from 4-digit designations."""

    @pytest.mark.parametrize("code,camber,position", [("2412", 0.02, 0.4), ("4412", 0.04, 0.4)])
    def test_max_camber_of_the_section(self, code: str, camber: float, position: float) -> None:
        """Vertical-cut camber recovers the mean line's peak value.

        The *location* is checked only loosely. Near its maximum the 4-digit
        mean line is a flat parabola, so the argmax is ill-conditioned: a
        perturbation of order 1e-6 in the camber shifts it by several
        thousandths of a chord. The peak value is not ill-conditioned and is
        checked tightly.
        """
        af = naca(code, 401)
        assert af.max_camber.value == pytest.approx(camber, rel=1e-3)
        assert af.max_camber.x == pytest.approx(position, abs=0.015)

    def test_contour_passes_through_the_origin(self) -> None:
        """The mean line starts at the origin, so the surface has a point there."""
        af = naca("2412", 201)
        distances = np.hypot(af.x, af.z)
        assert float(np.min(distances)) < 1e-12

    def test_leading_edge_point_is_near_but_not_at_the_origin(self) -> None:
        """For a cambered section the furthest-from-the-trailing-edge point is not (0, 0).

        Thickness is laid off perpendicular to an inclined mean line, which
        pushes the first upper-surface points to slightly negative x. One of
        those, rather than the origin, is furthest from the trailing edge. The
        offset is a few thousandths of a chord and is genuine geometry, so the
        leading-edge point is asserted to be *close to* the origin without being
        it.
        """
        af = naca("2412", 201)
        assert 0.0 < float(np.linalg.norm(af.le_point)) < 5e-3
        assert af.le_point[0] < 0.0
        assert af.le_point[1] > 0.0

    def test_trailing_edge_is_on_the_chord_line(self) -> None:
        af = naca("4412", 201)
        assert af.te_point[0] == pytest.approx(1.0, abs=1e-12)
        assert af.te_point[1] == pytest.approx(0.0, abs=1e-12)

    def test_upper_surface_is_above_the_lower_surface(self) -> None:
        af = naca("4412", 201)
        x = np.linspace(*af.x_range, 200)[1:-1]
        assert np.all(af.thickness_at(x) > 0.0)

    def test_thickness_is_nearly_independent_of_camber(self) -> None:
        """0012, 2412 and 4412 share a thickness form, so t_max barely moves.

        It moves a little because vertical cuts through a cambered section are
        not perpendicular to its mean line; see NOTES.md, A1.4.
        """
        values = [naca(c, 401).max_thickness.value for c in ("0012", "2412", "4412")]
        assert np.allclose(values, 0.12, atol=3e-4)


class TestFiveDigitCamberConstants:
    """The 5-digit mean-line constants: internal consistency, then the tables.

    The internal-consistency checks come first because they are the stronger
    statement. ``m`` and ``k1`` are *defined* by the conditions asserted here;
    the published tables are a 1930s hand computation of the same quantities,
    rounded to four decimal places, and are used as a cross-check.
    """

    # Abbott & von Doenhoff, Theory of Wing Sections: mean-line constants at
    # the design lift coefficient of 0.3.
    STANDARD = {  # x_f: (m, k1)
        0.05: (0.0580, 361.4),
        0.10: (0.1260, 51.640),
        0.15: (0.2025, 15.957),
        0.20: (0.2900, 6.643),
        0.25: (0.3910, 3.230),
    }
    REFLEX = {  # x_f: (m, k1, k2/k1)
        0.10: (0.1300, 51.990, 0.000764),
        0.15: (0.2170, 15.793, 0.006770),
        0.20: (0.3180, 6.520, 0.030300),
        0.25: (0.4410, 3.191, 0.135500),
    }

    @pytest.mark.parametrize("x_f", sorted(STANDARD))
    def test_standard_line_reaches_its_design_lift(self, x_f: float) -> None:
        """k1 is defined by Cl_i = Cl_design, so this must hold to solver precision."""
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=False)
        cl, _ = ideal_cl_and_cm(camber)
        assert cl == pytest.approx(0.3, rel=1e-9)

    @pytest.mark.parametrize("x_f", sorted(STANDARD))
    def test_standard_line_peaks_at_the_requested_station(self, x_f: float) -> None:
        """m is defined by x_f = m(1 - sqrt(m/3)); check the mean line really peaks there."""
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=False)
        x = np.linspace(0.0, 1.0, 1_000_001)
        y, _ = camber_line_5digit(x, camber)
        assert x[int(np.argmax(y))] == pytest.approx(x_f, abs=2e-5)

    @pytest.mark.parametrize("x_f", sorted(REFLEX))
    def test_reflexed_line_has_zero_quarter_chord_moment(self, x_f: float) -> None:
        """Zero Cm_c/4 is the defining property of the reflexed series."""
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=True)
        _, cm = ideal_cl_and_cm(camber)
        assert cm == pytest.approx(0.0, abs=1e-12)

    @pytest.mark.parametrize("x_f", sorted(REFLEX))
    def test_reflexed_line_reaches_its_design_lift(self, x_f: float) -> None:
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=True)
        cl, _ = ideal_cl_and_cm(camber)
        assert cl == pytest.approx(0.3, rel=1e-9)

    def test_standard_line_has_no_reflex(self) -> None:
        camber = solve_five_digit_camber(0.15, 0.3, reflexed=False)
        assert camber.k2_over_k1 == 0.0

    def test_k1_scales_linearly_with_design_lift(self) -> None:
        a = solve_five_digit_camber(0.15, 0.3)
        b = solve_five_digit_camber(0.15, 0.6)
        assert b.k1 == pytest.approx(2.0 * a.k1, rel=1e-9)
        assert b.m == pytest.approx(a.m, rel=1e-12)

    @pytest.mark.parametrize("x_f", sorted(STANDARD))
    def test_standard_m_matches_the_published_table(self, x_f: float) -> None:
        m_published, _ = self.STANDARD[x_f]
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=False)
        assert camber.m == pytest.approx(m_published, rel=3e-3)

    @pytest.mark.parametrize("x_f", [0.10, 0.15, 0.20, 0.25])
    def test_standard_k1_matches_the_published_table(self, x_f: float) -> None:
        """Agreement to 0.5%, which is the rounding in the published m.

        x_f = 0.05 is deliberately absent; see
        ``test_published_k1_for_the_210_mean_line_is_internally_inconsistent``.
        """
        _, k1_published = self.STANDARD[x_f]
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=False)
        assert camber.k1 == pytest.approx(k1_published, rel=5e-3)

    def test_published_k1_for_the_210_mean_line_is_internally_inconsistent(self) -> None:
        """The published (m, k1) pair for x_f = 0.05 does not give Cl_i = 0.3.

        Feeding the published m = 0.0580 and k1 = 361.4 into thin airfoil theory
        gives Cl_i = 0.3084, 2.8% above the 0.3 that defines the series. The
        sensitivity of k1 to m is only about -2.5, and the published m is 0.13%
        from the true root, so rounding accounts for barely a tenth of the
        discrepancy. This test pins the discrepancy as a property of the
        *table*, so that a future change to the solver cannot quietly be blamed
        on it. See NOTES.md, L1.1.
        """
        from aerolab.geometry.naca import FiveDigitCamber

        published = FiveDigitCamber(
            m=0.0580, k1=361.4, k2_over_k1=0.0, x_f=0.05,
            cl_design=0.3, reflexed=False,
        )
        cl_published, _ = ideal_cl_and_cm(published)
        assert cl_published == pytest.approx(0.3084, abs=5e-4)

        derived = solve_five_digit_camber(0.05, 0.3, reflexed=False)
        cl_derived, _ = ideal_cl_and_cm(derived)
        assert cl_derived == pytest.approx(0.3, rel=1e-9)

    @pytest.mark.parametrize("x_f", sorted(REFLEX))
    def test_reflexed_m_matches_the_published_table(self, x_f: float) -> None:
        m_published, _, _ = self.REFLEX[x_f]
        camber = solve_five_digit_camber(x_f, 0.3, reflexed=True)
        assert camber.m == pytest.approx(m_published, rel=7e-3)

    @pytest.mark.parametrize("x_f", sorted(REFLEX))
    def test_reflex_ratio_formula_reproduces_the_table_exactly(self, x_f: float) -> None:
        """Fed the published m, the reflex-ratio formula returns the published ratio.

        This separates the formula from its conditioning. The derived k2/k1
        differs from the table by up to 20% at x_f = 0.10, but that is
        amplification, not error: d(ln r)/d(ln m) reaches 34 there, because
        ``3(m - x_f)^2`` and ``m^3`` very nearly cancel. Evaluating the same
        formula at the table's own m reproduces the table to five significant
        figures, which shows the formula is right and the sensitivity is real.
        See NOTES.md, A1.3.
        """
        m_published, _, ratio_published = self.REFLEX[x_f]
        ratio = (3.0 * (m_published - x_f) ** 2 - m_published**3) / (1.0 - m_published) ** 3
        assert ratio == pytest.approx(ratio_published, rel=2e-3)

    def test_reflex_ratio_is_ill_conditioned_in_m(self) -> None:
        """Document the amplification with a number rather than a comment."""
        x_f, m = 0.10, 0.1300
        def ratio(mm: float) -> float:
            return (3.0 * (mm - x_f) ** 2 - mm**3) / (1.0 - mm) ** 3
        h = 1e-6
        sensitivity = (
            (np.log(ratio(m + h)) - np.log(ratio(m - h)))
            / (np.log(m + h) - np.log(m - h))
        )
        assert sensitivity > 30.0

    def test_impossible_camber_position_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="0 < x_f < 0.5"):
            solve_five_digit_camber(0.6, 0.3)


class TestFiveDigitSections:
    """Whole sections generated from 5-digit designations."""

    def test_23012_max_camber_value(self) -> None:
        """The 230 mean line peaks at 0.0184c.

        Location is not asserted against x_f = 0.15 here: the vertical-cut
        camber of the assembled section peaks at x/c = 0.1436, a real
        consequence of laying thickness off perpendicular to a mean line whose
        curvature is high near the nose. That offset is stable to five decimals
        from 201 to 3201 points, so it is geometry, not discretisation. See
        NOTES.md, A1.4.
        """
        af = naca("23012", 401)
        assert af.max_camber.value == pytest.approx(0.0184, rel=5e-3)

    def test_vertical_camber_offset_is_geometric_not_numerical(self) -> None:
        """The 23012 camber peak location must not move with point count."""
        locations = [naca("23012", n).max_camber.x for n in (401, 801, 1601)]
        assert np.ptp(locations) < 1e-3
        assert locations[0] == pytest.approx(0.1436, abs=2e-3)

    def test_reflexed_section_differs_from_the_standard_one(self) -> None:
        standard = naca("23012", 201)
        reflexed = naca("23112", 201)
        assert not np.allclose(standard.z, reflexed.z, atol=1e-4)

    def test_reflex_relieves_the_aft_downwash_rather_than_reversing_it(self) -> None:
        """What "reflex" does to the 5-digit mean line, stated precisely.

        The aft slope does *not* become positive anywhere, and it is not
        uniformly shallower either. Aft of ``m`` the standard mean line is
        straight, at the constant slope ``-k1*m^3/6``. The reflexed one is a
        cubic: steeper than the standard line at mid-chord, then relaxing
        steadily so that near the trailing edge it is only about a quarter as
        steep. Redistributing the aft loading that way is what cancels the
        quarter-chord pitching moment.

        Checking for a positive slope would be wrong, and so would checking that
        the reflexed slope is everywhere shallower — both would have passed
        somewhere and hidden what reflex actually does.
        """
        standard = solve_five_digit_camber(0.15, 0.3, reflexed=False)
        reflexed = solve_five_digit_camber(0.15, 0.3, reflexed=True)
        x = np.array([0.5, 0.9, 0.99])
        _, slope_standard = camber_line_5digit(x, standard)
        _, slope_reflexed = camber_line_5digit(x, reflexed)

        assert np.all(slope_standard < 0.0)
        assert np.all(slope_reflexed < 0.0)
        # Standard is straight aft of m; reflexed relaxes monotonically.
        assert np.ptp(slope_standard) == pytest.approx(0.0, abs=1e-12)
        assert np.all(np.diff(slope_reflexed) > 0.0)
        # Steeper at mid-chord, markedly shallower at the tail.
        assert slope_reflexed[0] < slope_standard[0]
        assert slope_reflexed[2] > slope_standard[2]
        assert abs(slope_reflexed[2]) < 0.4 * abs(slope_standard[2])

    def test_thickness_is_set_by_the_last_two_digits(self) -> None:
        for code, expected in (("23012", 0.12), ("23015", 0.15), ("23018", 0.18)):
            assert naca(code, 401).max_thickness.value == pytest.approx(expected, abs=5e-4)

    def test_invalid_reflex_digit_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="must be 0 .* or 1"):
            naca5("23212")


class TestDesignationParsing:
    """Input handling at the designation boundary."""

    @pytest.mark.parametrize(
        "code", ["0012", "naca0012", "NACA 0012", " naca-0012 ", "NACA0012"]
    )
    def test_prefixes_and_spacing_are_accepted(self, code: str) -> None:
        assert naca(code, 61).n_points == 61

    def test_dispatch_by_digit_count(self) -> None:
        assert naca("2412", 61).n_points == 61
        assert naca("23012", 61).n_points == 61

    @pytest.mark.parametrize("code", ["12", "123", "123456", "abcd", "24a2"])
    def test_malformed_designations_are_rejected(self, code: str) -> None:
        with pytest.raises(GeometryError):
            naca(code)

    def test_six_series_is_refused_rather_than_approximated(self) -> None:
        with pytest.raises(GeometryError, match="conformal mapping"):
            naca("632615")

    def test_zero_thickness_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="zero thickness"):
            naca4("2400")

    def test_even_point_count_is_rejected_with_a_usable_message(self) -> None:
        with pytest.raises(GeometryError, match="must be odd"):
            naca("0012", 200)

    def test_tiny_point_count_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="at least 21"):
            naca("0012", 11)

    def test_point_count_is_honoured(self) -> None:
        for n in (21, 101, 201, 401):
            assert naca("2412", n).n_points == n

    def test_name_defaults_to_the_designation(self) -> None:
        assert naca("2412", 61).name == "NACA 2412"
        assert naca("naca23012", 61).name == "NACA 23012"

    def test_explicit_name_overrides(self) -> None:
        assert naca("2412", 61, name="test section").name == "test section"
