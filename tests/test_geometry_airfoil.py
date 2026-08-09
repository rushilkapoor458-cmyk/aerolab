"""Tests for the Airfoil container and its geometric properties.

An ellipse does most of the work here. It is a valid airfoil shape whose area,
thickness distribution, camber and nose radius are all known in closed form, so
every property can be checked against an exact answer rather than against a
NACA section (whose own generator is what ``test_geometry_naca.py`` is for).

For a semi-axis pair ``(a, b)`` centred at ``(a, 0)``:

- area          ``pi * a * b``
- thickness     ``2b * sqrt(1 - ((x - a)/a)**2)``
- camber        zero everywhere
- nose radius   ``b**2 / a``
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil, _signed_area
from aerolab.geometry.naca import naca

from tests.helpers import A_SEMI, B_SEMI, ellipse, ellipse_area, ellipse_perimeter


class TestOrientationConvention:
    """Selig order is counter-clockwise; everything downstream depends on it."""

    def test_selig_order_has_positive_signed_area(self) -> None:
        """Walk a diamond in Selig order and confirm the sign by hand.

        Trailing edge (1, 0), up over the top to (0.5, 0.06), leading edge
        (0, 0), back under via (0.5, -0.06). Traversing the upper surface right
        to left across positive z is the positive sense of rotation.
        """
        x = np.array([1.0, 0.5, 0.0, 0.5])
        z = np.array([0.0, 0.06, 0.0, -0.06])
        assert _signed_area(x, z) > 0.0

    def test_generated_sections_are_counter_clockwise(self) -> None:
        for code in ("0012", "2412", "4412", "23012"):
            assert naca(code, 61).signed_area > 0.0

    def test_clockwise_input_is_rejected_by_the_constructor(self) -> None:
        af = naca("2412", 61)
        with pytest.raises(GeometryError, match="clockwise"):
            Airfoil(af.x[::-1].copy(), af.z[::-1].copy())

    def test_from_points_repairs_clockwise_input(self) -> None:
        af = naca("2412", 61)
        repaired = Airfoil.from_points(af.x[::-1], af.z[::-1])
        assert repaired.signed_area > 0.0
        assert np.allclose(repaired.x, af.x)
        assert np.allclose(repaired.z, af.z)

    def test_reversing_twice_is_the_identity(self) -> None:
        af = naca("4412", 61)
        assert np.allclose(af.reversed().reversed().x, af.x)


class TestConstructorValidation:
    """The constructor is the single place the ordering invariant is established."""

    def test_mismatched_lengths(self) -> None:
        with pytest.raises(GeometryError, match="differ in length"):
            Airfoil(np.zeros(10), np.zeros(9))

    def test_too_few_points(self) -> None:
        with pytest.raises(GeometryError, match="at least 7 points"):
            Airfoil(np.array([1.0, 0.5, 0.0, 0.5]), np.array([0.0, 0.1, 0.0, -0.1]))

    def test_non_finite_values(self) -> None:
        af = ellipse(61)
        x = af.x.copy()
        x[3] = np.nan
        with pytest.raises(GeometryError, match="non-finite"):
            Airfoil(x, af.z)

    def test_two_dimensional_input(self) -> None:
        with pytest.raises(GeometryError, match="one-dimensional"):
            Airfoil(np.zeros((5, 2)), np.zeros((5, 2)))

    def test_duplicate_consecutive_points(self) -> None:
        af = ellipse(61)
        x = np.insert(af.x, 5, af.x[5])
        z = np.insert(af.z, 5, af.z[5])
        with pytest.raises(GeometryError, match="zero-length segment"):
            Airfoil(x, z)

    def test_from_points_drops_duplicates(self) -> None:
        af = ellipse(61)
        x = np.insert(af.x, 5, af.x[5])
        z = np.insert(af.z, 5, af.z[5])
        assert Airfoil.from_points(x, z).n_points == af.n_points

    def test_contour_not_starting_at_the_trailing_edge(self) -> None:
        """An open-trailing-edge section is used so rolling creates no duplicate point."""
        af = naca("0012", 61, closed_te=False)
        with pytest.raises(GeometryError, match="not in Selig order"):
            Airfoil(np.roll(af.x, 15), np.roll(af.z, 15))

    def test_coordinates_are_read_only(self) -> None:
        """Cached properties would go stale if the arrays could be mutated."""
        af = ellipse(61)
        with pytest.raises(ValueError):
            af.x[0] = 99.0


class TestEllipseProperties:
    """Geometric properties against the closed-form ellipse."""

    @pytest.fixture
    def af(self) -> Airfoil:
        return ellipse(801)

    def test_area(self, af: Airfoil) -> None:
        assert af.area == pytest.approx(ellipse_area(), rel=1e-4)

    def test_max_thickness(self, af: Airfoil) -> None:
        assert af.max_thickness.value == pytest.approx(2 * B_SEMI, rel=1e-6)
        assert af.max_thickness.x == pytest.approx(A_SEMI, abs=1e-3)

    def test_thickness_distribution(self, af: Airfoil) -> None:
        x = np.linspace(0.05, 0.95, 60)
        expected = 2 * B_SEMI * np.sqrt(1.0 - ((x - A_SEMI) / A_SEMI) ** 2)
        assert np.allclose(af.thickness_at(x), expected, rtol=1e-5)

    def test_camber_is_zero(self, af: Airfoil) -> None:
        x = np.linspace(0.05, 0.95, 60)
        assert np.allclose(af.camber_at(x), 0.0, atol=1e-9)
        assert af.max_camber.value == pytest.approx(0.0, abs=1e-9)

    def test_nose_radius(self, af: Airfoil) -> None:
        assert af.le_radius == pytest.approx(B_SEMI**2 / A_SEMI, rel=2e-3)

    @pytest.mark.parametrize("b", [0.05, 0.1, 0.2])
    def test_nose_radius_scales_correctly(self, b: float) -> None:
        af = ellipse(801, b=b)
        assert af.le_radius == pytest.approx(b**2 / A_SEMI, rel=3e-3)

    def test_perimeter(self, af: Airfoil) -> None:
        assert af.perimeter == pytest.approx(ellipse_perimeter(), rel=1e-4)

    def test_landmarks(self, af: Airfoil) -> None:
        assert np.allclose(af.le_point, [0.0, 0.0], atol=1e-9)
        assert np.allclose(af.te_point, [2 * A_SEMI, 0.0], atol=1e-12)
        assert af.chord == pytest.approx(1.0, rel=1e-12)
        assert af.te_gap == pytest.approx(0.0, abs=1e-12)


class TestThicknessAndCamberDomain:
    """Cuts are never extrapolated outside the section."""

    def test_out_of_range_raises(self) -> None:
        af = naca("2412", 201)
        with pytest.raises(GeometryError, match="outside the airfoil"):
            af.thickness_at(np.array([1.5]))
        with pytest.raises(GeometryError, match="outside the airfoil"):
            af.camber_at(np.array([-0.5]))

    def test_range_spans_essentially_the_whole_chord(self) -> None:
        lo, hi = naca("2412", 201).x_range
        assert lo <= 0.0
        assert hi == pytest.approx(1.0, abs=1e-6)

    def test_distribution_helpers_stay_inside_the_range(self) -> None:
        af = naca("4412", 201)
        x, t = af.thickness_distribution(101)
        lo, hi = af.x_range
        assert x[0] >= lo - 1e-12 and x[-1] <= hi + 1e-12
        assert t.shape == x.shape
        # Thickness vanishes at a closed trailing edge, so allow rounding noise
        # there rather than demanding a strictly non-negative value.
        assert np.all(t >= -1e-12)

    def test_too_few_stations_rejected(self) -> None:
        with pytest.raises(GeometryError, match="at least 3 stations"):
            naca("0012", 61).thickness_distribution(2)


class TestNormalize:
    """Normalisation to unit chord with the leading edge at the origin."""

    def test_normalization_undoes_an_arbitrary_similarity_transform(self) -> None:
        """Translate, rotate and scale a section; normalising must recover it.

        The comparison is against ``af.normalize()``, not against ``af``. For a
        cambered section the leading-edge *point* is a few thousandths of a chord
        off the origin, so normalising a NACA 2412 shifts it very slightly; that
        is correct behaviour, and the invariant being tested is that
        normalisation is unaffected by a prior similarity transform.
        """
        af = naca("2412", 201)
        angle = np.deg2rad(7.0)
        scale = 2.35
        c, s = np.cos(angle), np.sin(angle)
        moved = Airfoil(
            scale * (af.x * c - af.z * s) + 3.0,
            scale * (af.x * s + af.z * c) - 1.5,
            name="rotated",
        )
        restored = moved.normalize()
        reference = af.normalize()

        assert restored.chord == pytest.approx(1.0, rel=1e-12)
        assert np.allclose(restored.le_point, [0.0, 0.0], atol=1e-12)
        assert np.allclose(restored.te_point, [1.0, 0.0], atol=1e-12)
        assert np.allclose(restored.x, reference.x, atol=1e-9)
        assert np.allclose(restored.z, reference.z, atol=1e-9)

    def test_normalizing_a_symmetric_unit_section_changes_nothing(self) -> None:
        """A symmetric section already has its leading-edge point at the origin."""
        af = naca("0012", 201)
        assert np.allclose(af.normalize().x, af.x, atol=1e-12)
        assert np.allclose(af.normalize().z, af.z, atol=1e-12)

    def test_normalization_is_idempotent(self) -> None:
        once = naca("2412", 201).normalize()
        assert np.allclose(once.normalize().points, once.points, atol=1e-12)

    def test_area_scales_with_the_square_of_the_scale_factor(self) -> None:
        af = naca("2412", 401)
        big = Airfoil(af.x * 3.0, af.z * 3.0)
        assert big.area == pytest.approx(9.0 * af.area, rel=1e-12)
        assert big.normalize().area == pytest.approx(af.normalize().area, rel=1e-9)


class TestTrailingEdge:
    """Sharp and finite-thickness trailing edges."""

    def test_sharp_is_detected(self) -> None:
        assert naca("0012", 201, closed_te=True).is_sharp_te()

    def test_finite_gap_is_detected(self) -> None:
        af = naca("0012", 201, closed_te=False)
        assert not af.is_sharp_te()
        assert af.te_gap > 1e-4

    def test_open_section_area_exceeds_closed(self) -> None:
        """A finite base adds area; a solver that lost it would be wrong."""
        closed = naca("0012", 401, closed_te=True)
        opened = naca("0012", 401, closed_te=False)
        assert opened.area > closed.area

    def test_cusped_trailing_edge_has_small_included_angle(self) -> None:
        """An ellipse is blunt at the tail, so its included angle is large."""
        assert ellipse(401).te_included_angle > np.deg2rad(150.0)


class TestLeadingEdgeRadiusFailure:
    """No silent failure when the nose is too coarsely resolved."""

    def test_sparse_nose_raises_rather_than_guessing(self) -> None:
        """A coarse polygon has no resolved nose, and must say so rather than fit one."""
        x = np.array([1.0, 0.6, 0.2, 0.0, 0.2, 0.6, 1.0])
        z = np.array([0.0, 0.05, 0.05, 0.0, -0.05, -0.05, 0.0])
        with pytest.raises(GeometryError, match="at least 5 are needed"):
            _ = Airfoil(x, z).le_radius


class TestSurfaceSplitting:
    """Splitting the contour into surfaces."""

    def test_surfaces_share_the_leading_edge_point(self) -> None:
        af = naca("2412", 201)
        (xu, zu), (xl, zl) = af.surfaces()
        assert xu.size + xl.size == af.n_points + 1
        assert xu[0] == pytest.approx(xl[0])
        assert zu[0] == pytest.approx(zl[0])

    def test_surfaces_run_from_the_leading_edge_aft(self) -> None:
        af = naca("2412", 201)
        (xu, _), (xl, _) = af.surfaces()
        assert xu[0] < xu[-1]
        assert xl[0] < xl[-1]
        assert xu[-1] == pytest.approx(1.0, abs=1e-9)

    def test_upper_surface_is_the_one_on_top(self) -> None:
        af = naca("4412", 201)
        (_, zu), (_, zl) = af.surfaces()
        assert zu.mean() > zl.mean()

    def test_arc_length_is_monotonic_and_matches_the_perimeter(self) -> None:
        af = naca("2412", 201)
        s = af.arc_length
        assert np.all(np.diff(s) > 0.0)
        assert s[-1] == pytest.approx(af.perimeter, rel=1e-12)

    def test_leading_edge_arc_length_is_refined_off_the_input_points(self) -> None:
        """s_le comes from the spline, so it need not equal any input point's s."""
        af = naca("4412", 201)
        assert 0.0 < af.s_le < af.perimeter
        assert abs(af.s_le - af.arc_length[af.le_index]) < 0.05
