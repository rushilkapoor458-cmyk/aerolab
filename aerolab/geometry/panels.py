"""Panel geometry derived from an airfoil contour.

This is the geometric half of a panel method: endpoints, control points,
lengths, and the tangent/normal frame on each panel. No aerodynamics happens
here — the Phase 2 solver consumes these and adds the influence coefficients.

Orientation
    Selig ordering traverses the contour **counter-clockwise** in the (x, z)
    plane (:class:`~aerolab.geometry.airfoil.Airfoil` asserts this on
    construction). Travelling counter-clockwise keeps the interior on the left,
    so the outward normal points right: the tangent rotated by -90 degrees,
    ``n = (t_z, -t_x)``. Check it on the upper surface, which is walked from
    trailing edge to leading edge with ``t = (-1, 0)``; the formula gives
    ``n = (0, +1)``, which points up and away from the section. Getting this
    backwards flips the sign of every boundary condition in the panel solve, so
    it is verified directly in ``tests/test_geometry_panels.py`` against a
    known-outward direction rather than reasoned about only in a comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
from numpy.typing import NDArray

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil

FloatArray = NDArray[np.float64]

__all__ = ["Panels"]


@dataclass(frozen=True, eq=False)
class Panels:
    """Flat panels spanning consecutive points of an airfoil contour.

    Parameters
    ----------
    airfoil : Airfoil
        Contour to panel. Panel ``i`` runs from point ``i`` to point ``i + 1``,
        so there are ``n_points - 1`` panels, ordered from the upper trailing
        edge forward to the leading edge and back to the lower trailing edge.

    Notes
    -----
    The trailing-edge base is **not** panelled. For a finite-thickness trailing
    edge the gap between the first and last points is left open; how that gap is
    closed is a modelling decision belonging to the solver, not to the geometry.

    There is deliberately no minimum-panel-count check here. ``Airfoil`` already
    refuses fewer than seven points, so any airfoil that exists has at least six
    panels; a guard against fewer would be unreachable code, and unreachable
    validation is worse than none because it cannot be tested.
    """

    airfoil: Airfoil

    def __len__(self) -> int:
        return self.airfoil.n_panels

    def __repr__(self) -> str:
        return (
            f"<Panels of {self.airfoil.name!r}: {len(self)} panels, "
            f"lengths {self.lengths.min():.5f}c to {self.lengths.max():.5f}c>"
        )

    @property
    def n_panels(self) -> int:
        """Number of panels."""
        return self.airfoil.n_panels

    @cached_property
    def start_points(self) -> FloatArray:
        """``(n_panels, 2)`` array of panel start points, in chords."""
        return np.column_stack([self.airfoil.x[:-1], self.airfoil.z[:-1]])

    @cached_property
    def end_points(self) -> FloatArray:
        """``(n_panels, 2)`` array of panel end points, in chords."""
        return np.column_stack([self.airfoil.x[1:], self.airfoil.z[1:]])

    @cached_property
    def control_points(self) -> FloatArray:
        """``(n_panels, 2)`` array of panel midpoints, in chords.

        Constant-strength panel methods enforce the boundary condition at the
        midpoint, where the self-induced velocity of a constant-strength
        distribution is finite.
        """
        return 0.5 * (self.start_points + self.end_points)

    @cached_property
    def lengths(self) -> FloatArray:
        """Panel lengths, in chords."""
        delta = self.end_points - self.start_points
        return np.hypot(delta[:, 0], delta[:, 1])

    @cached_property
    def tangents(self) -> FloatArray:
        """``(n_panels, 2)`` unit tangents, pointing along the traversal direction."""
        delta = self.end_points - self.start_points
        return delta / self.lengths[:, None]

    @cached_property
    def normals(self) -> FloatArray:
        """``(n_panels, 2)`` unit normals, pointing **out of** the airfoil.

        For the counter-clockwise Selig traversal the interior lies to the left,
        so the outward direction is the tangent rotated by -90 degrees:
        ``n = (t_z, -t_x)``.
        """
        t = self.tangents
        return np.column_stack([t[:, 1], -t[:, 0]])

    @cached_property
    def angles(self) -> FloatArray:
        """Panel inclinations in **radians**, measured from the +x axis.

        Returned in ``(-pi, pi]`` from ``arctan2`` of the tangent components.
        """
        t = self.tangents
        return np.arctan2(t[:, 1], t[:, 0])

    @cached_property
    def total_length(self) -> float:
        """Sum of panel lengths, in chords. Equals the contour perimeter."""
        return float(np.sum(self.lengths))
