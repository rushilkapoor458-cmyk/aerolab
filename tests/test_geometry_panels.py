"""Tests for panel geometry.

The important assertion in this module is that panel normals point *out* of the
section. A sign error there flips every boundary condition in the Phase 2 panel
solve, and the solver would converge happily to a wrong answer. So outwardness
is tested against an independent point-in-polygon test rather than by comparing
against the same rotation formula the implementation uses — otherwise the test
would only confirm that the code agrees with itself.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.path import Path

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil
from aerolab.geometry.naca import naca
from aerolab.geometry.panels import Panels

from tests.helpers import ellipse

SECTIONS = ["0012", "2412", "4412", "23012"]


class TestPanelCounts:
    def test_panel_count_is_one_less_than_the_point_count(self) -> None:
        af = naca("2412", 201)
        panels = Panels(af)
        assert panels.n_panels == 200
        assert len(panels) == 200

    def test_endpoints_are_consecutive_contour_points(self) -> None:
        af = naca("2412", 61)
        panels = Panels(af)
        assert np.allclose(panels.start_points[:, 0], af.x[:-1])
        assert np.allclose(panels.end_points[:, 0], af.x[1:])

    def test_control_points_are_midpoints(self) -> None:
        panels = Panels(naca("2412", 61))
        expected = 0.5 * (panels.start_points + panels.end_points)
        assert np.allclose(panels.control_points, expected)

    def test_minimum_panel_count_is_guaranteed_upstream(self) -> None:
        """Airfoil's seven-point minimum already bounds the panel count below.

        Pinning this makes explicit why Panels carries no minimum-count check
        of its own: the smallest constructible airfoil yields six panels.
        """
        x = np.array([1.0, 0.6, 0.2, 0.0, 0.2, 0.6, 1.0])
        z = np.array([0.0, 0.05, 0.05, 0.0, -0.05, -0.05, 0.0])
        assert Panels(Airfoil(x, z)).n_panels == 6

        with pytest.raises(GeometryError, match="at least 7 points"):
            Airfoil(x[:5], z[:5])


class TestPanelFrame:
    """Lengths, tangents and normals."""

    @pytest.mark.parametrize("code", SECTIONS)
    def test_lengths_sum_to_the_perimeter(self, code: str) -> None:
        af = naca(code, 201)
        assert Panels(af).total_length == pytest.approx(af.perimeter, rel=1e-12)

    @pytest.mark.parametrize("code", SECTIONS)
    def test_all_lengths_are_positive(self, code: str) -> None:
        assert np.all(Panels(naca(code, 201)).lengths > 0.0)

    @pytest.mark.parametrize("code", SECTIONS)
    def test_tangents_and_normals_are_unit_vectors(self, code: str) -> None:
        panels = Panels(naca(code, 201))
        assert np.allclose(np.linalg.norm(panels.tangents, axis=1), 1.0)
        assert np.allclose(np.linalg.norm(panels.normals, axis=1), 1.0)

    @pytest.mark.parametrize("code", SECTIONS)
    def test_normals_are_perpendicular_to_tangents(self, code: str) -> None:
        panels = Panels(naca(code, 201))
        assert np.allclose(np.sum(panels.normals * panels.tangents, axis=1), 0.0, atol=1e-14)

    def test_angles_match_the_tangent_directions(self) -> None:
        panels = Panels(naca("2412", 101))
        assert np.allclose(np.cos(panels.angles), panels.tangents[:, 0])
        assert np.allclose(np.sin(panels.angles), panels.tangents[:, 1])

    def test_angles_are_in_radians_not_degrees(self) -> None:
        """A guard against a unit slip at this boundary."""
        assert np.all(np.abs(Panels(naca("2412", 101)).angles) <= np.pi + 1e-12)


class TestNormalsPointOutward:
    """The assertion the Phase 2 boundary condition depends on."""

    @pytest.mark.parametrize("code", SECTIONS)
    def test_divergence_theorem_fixes_the_normal_direction(self, code: str) -> None:
        """The rigorous global check: sum of L*(c . n) equals twice the area.

        Applying the divergence theorem to ``F = (x, z)``, whose divergence is 2,
        gives ``closed_integral(F . n) ds = 2 * Area``. On a polygon each edge
        contributes exactly ``L * (c . n)`` with ``c`` the midpoint, so the
        identity holds to machine precision — no discretisation error to hide
        behind. Inward normals would give ``-2 * Area``, so the sign of this sum
        *is* the orientation of the normals.

        This is independent of the rotation formula under test: it appeals only
        to the area, computed by the shoelace sum.
        """
        af = naca(code, 201, closed_te=True)
        panels = Panels(af)
        flux = float(
            np.sum(panels.lengths * np.sum(panels.control_points * panels.normals, axis=1))
        )
        assert flux == pytest.approx(2.0 * af.area, rel=1e-12)
        assert flux > 0.0

    def test_divergence_check_accounts_for_an_open_trailing_edge(self) -> None:
        """With a finite base the panels do not close the contour; the gap is the difference.

        Adding the base segment's contribution recovers the identity, which
        confirms that exactly one segment is missing and that it is the base.
        """
        af = naca("0012", 201, closed_te=False)
        panels = Panels(af)
        flux = float(
            np.sum(panels.lengths * np.sum(panels.control_points * panels.normals, axis=1))
        )
        base_vector = af.points[0] - af.points[-1]
        base_length = float(np.linalg.norm(base_vector))
        base_tangent = base_vector / base_length
        base_normal = np.array([base_tangent[1], -base_tangent[0]])
        base_mid = 0.5 * (af.points[0] + af.points[-1])
        flux += base_length * float(np.dot(base_mid, base_normal))
        assert flux == pytest.approx(2.0 * af.area, rel=1e-12)

    @pytest.mark.parametrize("code", SECTIONS)
    def test_stepping_along_the_normal_leaves_the_section(self, code: str) -> None:
        """Local check by point-in-polygon, away from the razor-thin trailing edge.

        Panels aft of 90% chord are excluded. There the section is thinner than
        the panels are long, so any step large enough to be numerically
        meaningful crosses to the other surface — a fact about the geometry, not
        about the normals. The divergence-theorem test above covers every panel
        including those.
        """
        af = naca(code, 201)
        panels = Panels(af)
        polygon = Path(af.points)

        interior = panels.control_points[:, 0] < 0.9
        step = 0.2 * panels.lengths[interior, None]
        centres = panels.control_points[interior]
        normals = panels.normals[interior]

        assert not polygon.contains_points(centres + step * normals).any()
        assert polygon.contains_points(centres - step * normals).all()

    def test_upper_surface_normals_point_up(self) -> None:
        """Sanity check with a direction that needs no machinery to verify."""
        panels = Panels(naca("0012", 201))
        top = int(np.argmax(panels.control_points[:, 1]))
        bottom = int(np.argmin(panels.control_points[:, 1]))
        assert panels.normals[top, 1] > 0.9
        assert panels.normals[bottom, 1] < -0.9

    def test_normals_are_outward_for_an_ellipse_too(self) -> None:
        """For an ellipse the outward normal is known analytically at every point."""
        a, b = 0.5, 0.1
        panels = Panels(ellipse(401, a, b))
        cx, cz = panels.control_points[:, 0], panels.control_points[:, 1]
        # Gradient of (x-a)^2/a^2 + z^2/b^2 points outward everywhere.
        gx, gz = 2 * (cx - a) / a**2, 2 * cz / b**2
        norm = np.hypot(gx, gz)
        analytic = np.column_stack([gx / norm, gz / norm])
        assert np.allclose(
            np.sum(analytic * panels.normals, axis=1), 1.0, atol=2e-3
        )


class TestPanelDistribution:
    """Cosine clustering should be visible in the panel lengths."""

    def test_nose_and_tail_panels_are_the_shortest(self) -> None:
        panels = Panels(naca("0012", 201))
        lengths = panels.lengths
        i_short = int(np.argmin(lengths))
        # Shortest panel sits at the trailing edge or the leading edge.
        assert i_short < 3 or i_short > len(lengths) - 4 or abs(
            i_short - len(lengths) // 2
        ) < 3

    def test_trailing_edge_base_is_not_panelled(self) -> None:
        """The gap between the two trailing-edge points is left open."""
        af = naca("0012", 201, closed_te=False)
        panels = Panels(af)
        assert panels.n_panels == af.n_points - 1
        assert panels.total_length == pytest.approx(af.perimeter, rel=1e-12)
        assert panels.total_length < af.perimeter + af.te_gap
