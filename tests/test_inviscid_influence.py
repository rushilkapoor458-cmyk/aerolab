"""Tests for panel influence coefficients.

These are checked against the defining integral properties of a sheet — its
outward flux and its circulation — and against the far-field limits where a
panel becomes a point singularity. Both are independent of the closed-form
expressions being tested, so agreement means the algebra is right rather than
self-consistent.

Contour integrals use a plain sum over equally spaced points rather than the
trapezoid rule. For a periodic integrand that *is* the trapezoid rule, and it
converges spectrally; applying ``np.trapezoid`` to an array with the repeated
endpoint dropped silently omits one interval, which shows up as a relative
error of exactly one over the point count.

The self-influence terms get particular attention. A sign error there flips the
boundary condition on every panel at once, and the solver would still converge
happily — to a flow *through* the airfoil instead of around it.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import GeometryError
from aerolab.inviscid.influence import panel_frames, panel_influence, self_influence

pytestmark = pytest.mark.validation

# A single panel along the x-axis from the origin to (1, 0).
UNIT_START = np.array([[0.0, 0.0]])
UNIT_END = np.array([[1.0, 0.0]])


def unit_panel_velocity(points):
    """Source and vortex velocity of the unit panel, shaped ``(p, 2)``."""
    source, vortex = panel_influence(UNIT_START, UNIT_END, np.atleast_2d(points))
    return source[:, 0, :], vortex[:, 0, :]


class TestPanelFrames:
    def test_tangent_and_normal_are_orthonormal(self) -> None:
        starts = np.array([[0.0, 0.0], [1.0, 0.5]])
        ends = np.array([[1.0, 0.0], [0.2, -0.3]])
        lengths, tangents, normals = panel_frames(starts, ends)
        assert np.allclose(lengths, [1.0, np.hypot(0.8, 0.8)])
        assert np.allclose(np.linalg.norm(tangents, axis=1), 1.0)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)
        assert np.allclose(np.sum(tangents * normals, axis=1), 0.0)

    def test_local_frame_is_right_handed(self) -> None:
        """t x n_loc = +1. The airfoil's outward normal is the negative of this."""
        starts = np.array([[0.0, 0.0], [1.0, 0.5]])
        ends = np.array([[1.0, 0.0], [0.2, -0.3]])
        _, t, n = panel_frames(starts, ends)
        cross = t[:, 0] * n[:, 1] - t[:, 1] * n[:, 0]
        assert np.allclose(cross, 1.0)

    def test_zero_length_panel_is_rejected(self) -> None:
        with pytest.raises(GeometryError, match="zero length"):
            panel_frames(np.array([[0.0, 0.0]]), np.array([[0.0, 0.0]]))


class TestSourcePanel:
    """A source sheet, checked by its flux."""

    def test_flux_through_a_surrounding_contour_equals_the_total_strength(self) -> None:
        """Divergence theorem: a unit source sheet of length S emits flux S."""
        theta = np.linspace(0.0, 2.0 * np.pi, 20001)[:-1]
        radius = 7.0
        points = np.column_stack(
            [0.5 + radius * np.cos(theta), radius * np.sin(theta)]
        )
        source, _ = unit_panel_velocity(points)
        outward = np.column_stack([np.cos(theta), np.sin(theta)])
        step = theta[1] - theta[0]
        flux = np.sum(np.sum(source * outward, axis=1)) * radius * step
        assert flux == pytest.approx(1.0, rel=1e-9)

    def test_no_circulation(self) -> None:
        """A source sheet is irrotational: its circulation is zero."""
        theta = np.linspace(0.0, 2.0 * np.pi, 20001)[:-1]
        radius = 7.0
        points = np.column_stack(
            [0.5 + radius * np.cos(theta), radius * np.sin(theta)]
        )
        source, _ = unit_panel_velocity(points)
        tangent = np.column_stack([-np.sin(theta), np.cos(theta)])
        step = theta[1] - theta[0]
        circulation = np.sum(np.sum(source * tangent, axis=1)) * radius * step
        assert circulation == pytest.approx(0.0, abs=1e-9)

    def test_far_field_is_a_point_source(self) -> None:
        """At distance the sheet collapses to a point source of strength S."""
        for radius in (50.0, 200.0):
            theta = np.linspace(0.0, 2.0 * np.pi, 17)[:-1]
            points = np.column_stack(
                [0.5 + radius * np.cos(theta), radius * np.sin(theta)]
            )
            source, _ = unit_panel_velocity(points)
            expected = np.column_stack([np.cos(theta), np.sin(theta)]) / (
                2.0 * np.pi * radius
            )
            assert np.allclose(source, expected, rtol=2e-3)

    def test_symmetric_about_the_panel(self) -> None:
        above = np.array([[0.5, 0.3], [0.2, 0.3]])
        below = np.array([[0.5, -0.3], [0.2, -0.3]])
        s_above, _ = unit_panel_velocity(above)
        s_below, _ = unit_panel_velocity(below)
        assert np.allclose(s_above[:, 0], s_below[:, 0])
        assert np.allclose(s_above[:, 1], -s_below[:, 1])


class TestVortexPanel:
    """A vortex sheet, checked by its circulation."""

    def test_circulation_around_a_surrounding_contour(self) -> None:
        """A unit vortex sheet of length S has circulation S, clockwise.

        Clockwise is the sign convention of this module, so the
        counter-clockwise line integral comes out negative.
        """
        theta = np.linspace(0.0, 2.0 * np.pi, 20001)[:-1]
        radius = 7.0
        points = np.column_stack(
            [0.5 + radius * np.cos(theta), radius * np.sin(theta)]
        )
        _, vortex = unit_panel_velocity(points)
        tangent = np.column_stack([-np.sin(theta), np.cos(theta)])
        step = theta[1] - theta[0]
        counter_clockwise = np.sum(np.sum(vortex * tangent, axis=1)) * radius * step
        assert counter_clockwise == pytest.approx(-1.0, rel=1e-9)

    def test_no_net_flux(self) -> None:
        theta = np.linspace(0.0, 2.0 * np.pi, 20001)[:-1]
        radius = 7.0
        points = np.column_stack(
            [0.5 + radius * np.cos(theta), radius * np.sin(theta)]
        )
        _, vortex = unit_panel_velocity(points)
        outward = np.column_stack([np.cos(theta), np.sin(theta)])
        step = theta[1] - theta[0]
        flux = np.sum(np.sum(vortex * outward, axis=1)) * radius * step
        assert flux == pytest.approx(0.0, abs=1e-9)

    def test_is_the_source_field_rotated_by_ninety_degrees(self) -> None:
        """``(u, w)_vortex = (w, -u)_source``, which is why one routine gives both."""
        rng = np.random.default_rng(0)
        points = rng.uniform(-4.0, 4.0, size=(60, 2))
        points[np.abs(points[:, 1]) < 0.05, 1] = 0.4     # keep clear of the sheet
        source, vortex = unit_panel_velocity(points)
        assert np.allclose(vortex[:, 0], source[:, 1], atol=1e-12)
        assert np.allclose(vortex[:, 1], -source[:, 0], atol=1e-12)


class TestSelfInfluence:
    """The exterior limit at a panel's own midpoint."""

    def test_source_self_influence_is_half_outward(self) -> None:
        """Approach the midpoint from outside and extrapolate, don't restate the algebra.

        The outward side is ``-n_loc``, so points are placed there at shrinking
        offsets. The limit must be ``+1/2`` along the outward normal.
        """
        _, tangents, local_normals = panel_frames(UNIT_START, UNIT_END)
        outward = -local_normals[0]
        midpoint = np.array([0.5, 0.0])

        offsets = np.array([1e-3, 1e-4, 1e-5, 1e-6])
        probes = midpoint[None, :] + offsets[:, None] * outward[None, :]
        source, _ = unit_panel_velocity(probes)
        normal_component = source @ outward
        # The approach is linear in the offset, so test the trend and the
        # limit rather than demanding every offset already be converged.
        error = np.abs(normal_component - 0.5)
        assert np.all(np.diff(error) < 0.0)
        assert np.allclose(error / offsets, error[0] / offsets[0], rtol=1e-3)
        assert error[-1] < 1e-6

        analytic_source, _ = self_influence(tangents, local_normals)
        assert analytic_source[0] @ outward == pytest.approx(0.5, abs=1e-12)
        assert analytic_source[0] @ tangents[0] == pytest.approx(0.0, abs=1e-12)

    def test_vortex_self_influence_is_minus_half_tangential(self) -> None:
        _, tangents, local_normals = panel_frames(UNIT_START, UNIT_END)
        outward = -local_normals[0]
        midpoint = np.array([0.5, 0.0])

        offsets = np.array([1e-3, 1e-4, 1e-5, 1e-6])
        probes = midpoint[None, :] + offsets[:, None] * outward[None, :]
        _, vortex = unit_panel_velocity(probes)
        tangential = vortex @ tangents[0]
        error = np.abs(tangential + 0.5)
        assert np.all(np.diff(error) < 0.0)
        assert np.allclose(error / offsets, error[0] / offsets[0], rtol=1e-3)
        assert error[-1] < 1e-6

        _, analytic_vortex = self_influence(tangents, local_normals)
        assert analytic_vortex[0] @ tangents[0] == pytest.approx(-0.5, abs=1e-12)
        assert analytic_vortex[0] @ outward == pytest.approx(0.0, abs=1e-12)

    def test_the_two_sides_of_a_vortex_sheet_differ_by_its_strength(self) -> None:
        """The tangential velocity jumps by exactly gamma across the sheet."""
        _, tangents, local_normals = panel_frames(UNIT_START, UNIT_END)
        midpoint = np.array([0.5, 0.0])
        offset = 1e-7
        _, above = unit_panel_velocity(midpoint + offset * local_normals[0])
        _, below = unit_panel_velocity(midpoint - offset * local_normals[0])
        jump = (above[0] - below[0]) @ tangents[0]
        assert jump == pytest.approx(1.0, abs=1e-5)

    def test_source_normal_velocity_jumps_by_its_strength(self) -> None:
        _, tangents, local_normals = panel_frames(UNIT_START, UNIT_END)
        midpoint = np.array([0.5, 0.0])
        offset = 1e-7
        above, _ = unit_panel_velocity(midpoint + offset * local_normals[0])
        below, _ = unit_panel_velocity(midpoint - offset * local_normals[0])
        jump = (above[0] - below[0]) @ local_normals[0]
        assert jump == pytest.approx(1.0, abs=1e-5)


class TestShapes:
    def test_output_shapes(self) -> None:
        starts = np.zeros((5, 2))
        ends = np.column_stack([np.arange(1.0, 6.0), np.ones(5)])
        points = np.zeros((7, 2)) + 10.0
        source, vortex = panel_influence(starts, ends, points)
        assert source.shape == (7, 5, 2)
        assert vortex.shape == (7, 5, 2)
