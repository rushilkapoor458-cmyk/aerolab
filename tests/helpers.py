"""Shared analytic test geometries.

An ellipse is the workhorse: it is a valid airfoil contour whose area,
thickness, camber and nose radius are all known exactly, so geometric
properties can be checked against closed-form answers rather than against a
NACA section produced by the very code under test.

For semi-axes ``(a, b)`` with the section spanning ``x`` in ``[0, 2a]``:

=================  ==========================================
area               ``pi * a * b``
thickness at x     ``2b * sqrt(1 - ((x - a)/a)**2)``
camber             zero everywhere
nose radius        ``b**2 / a``
=================  ==========================================
"""

from __future__ import annotations

import numpy as np

from aerolab.geometry.airfoil import Airfoil

#: Semi-axes giving a unit-chord section of 20% thickness.
A_SEMI = 0.5
B_SEMI = 0.1


def ellipse(n: int = 401, a: float = A_SEMI, b: float = B_SEMI) -> Airfoil:
    """Ellipse in Selig order, with ``n`` points.

    ``phi`` runs from 0 to ``2*pi``: it starts at the trailing edge ``(2a, 0)``,
    passes over the upper surface, reaches the leading edge at ``(0, 0)``, and
    returns along the lower surface. Uniform spacing in ``phi`` gives cosine-like
    clustering in ``x`` at both ends, which is what the nose-radius fit needs.

    The first and last points coincide. That is not a duplicate-point error:
    they are the two trailing-edge points of a contour with zero trailing-edge
    gap, and they are not adjacent in the array.
    """
    phi = np.linspace(0.0, 2.0 * np.pi, n)
    return Airfoil(a + a * np.cos(phi), b * np.sin(phi), name="ellipse")


def ellipse_area(a: float = A_SEMI, b: float = B_SEMI) -> float:
    """Exact enclosed area of the ellipse, in chords squared."""
    return float(np.pi * a * b)


def ellipse_perimeter(a: float = A_SEMI, b: float = B_SEMI) -> float:
    """Ramanujan's second approximation to the ellipse perimeter.

    Accurate to better than one part in 1e7 for these aspect ratios, which is
    far tighter than any tolerance asserted against it.
    """
    h = (a - b) ** 2 / (a + b) ** 2
    return float(np.pi * (a + b) * (1.0 + 3.0 * h / (10.0 + np.sqrt(4.0 - 3.0 * h))))
