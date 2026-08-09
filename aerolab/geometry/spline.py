"""Arc-length spline utilities shared by the geometry modules.

These functions take plain coordinate arrays rather than an
:class:`~aerolab.geometry.airfoil.Airfoil` so that both ``airfoil.py`` and
``repanel.py`` can use them without a circular import.

Why arc length
    An airfoil surface is double-valued in ``x`` and has infinite ``dz/dx`` at
    the nose. Splining against cumulative arc length avoids both problems and is
    the only parametrisation in which the leading edge is an ordinary point.

End conditions
    Natural (zero second derivative) at both trailing-edge points. The trailing
    edge is a real corner with a finite included angle; a periodic or otherwise
    smoothed spline would round it off and change the Kutta condition the Phase 2
    solver applies there.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize_scalar

FloatArray = NDArray[np.float64]

__all__ = ["cumulative_arc_length", "contour_spline", "refine_le"]


def cumulative_arc_length(x: FloatArray, z: FloatArray) -> FloatArray:
    """Cumulative straight-line arc length along a point sequence, starting at zero.

    Parameters
    ----------
    x, z : ndarray
        Coordinates, in chords.

    Returns
    -------
    ndarray
        Cumulative distance at each point, in chords. Same length as ``x``.
    """
    segments = np.hypot(np.diff(x), np.diff(z))
    return np.concatenate([[0.0], np.cumsum(segments)])


def contour_spline(
    x: FloatArray, z: FloatArray, s: FloatArray | None = None
) -> tuple[CubicSpline, CubicSpline, FloatArray]:
    """Cubic splines ``x(s)`` and ``z(s)`` against arc length.

    Parameters
    ----------
    x, z : ndarray
        Contour coordinates in Selig order, in chords.
    s : ndarray, optional
        Precomputed cumulative arc length. Computed if omitted.

    Returns
    -------
    spline_x, spline_z : CubicSpline
        Splines with natural end conditions, preserving the trailing-edge corner.
    s : ndarray
        The arc-length parameter used.
    """
    if s is None:
        s = cumulative_arc_length(x, z)
    return (
        CubicSpline(s, x, bc_type="natural"),
        CubicSpline(s, z, bc_type="natural"),
        s,
    )


def refine_le(
    spline_x: CubicSpline,
    spline_z: CubicSpline,
    te_point: FloatArray,
    s_lo: float,
    s_hi: float,
    s_guess: float,
) -> float:
    """Arc length of the point on the spline furthest from the trailing edge.

    The leading edge is defined as the point of maximum distance from the
    trailing-edge midpoint. That definition has a useful consequence: at a
    maximum of distance the derivative vanishes, so the surface tangent there is
    **perpendicular to the chord line**. The nose axis is therefore the chord
    direction, which is what :func:`~aerolab.geometry.airfoil.Airfoil.le_radius`
    relies on when it rotates into the leading-edge frame.

    Parameters
    ----------
    spline_x, spline_z : CubicSpline
        Contour splines against arc length.
    te_point : ndarray
        Trailing-edge midpoint ``(x, z)``, in chords.
    s_lo, s_hi : float
        Bracket to search within, in chords.
    s_guess : float
        Fallback returned if the bounded search does not converge.

    Returns
    -------
    float
        Arc length at the leading edge, in chords.
    """
    if s_lo >= s_hi:
        return float(s_guess)

    def negative_distance(ss: float) -> float:
        return -float(
            np.hypot(spline_x(ss) - te_point[0], spline_z(ss) - te_point[1])
        )

    result = minimize_scalar(
        negative_distance,
        bounds=(s_lo, s_hi),
        method="bounded",
        options={"xatol": 1e-12},
    )
    return float(result.x) if result.success else float(s_guess)
