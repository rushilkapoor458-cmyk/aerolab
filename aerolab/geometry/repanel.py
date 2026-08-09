"""Arc-length respline and cosine-clustered redistribution of surface points.

Repaneling has to do two things without corrupting the geometry: represent the
existing contour as a smooth curve, and place new points on it with a chosen
density. Both steps are where accuracy is quietly lost, so both are stated
explicitly here.

Parametrisation
    The contour is splined against **cumulative arc length**, not against ``x``.
    A surface is double-valued in ``x`` and has infinite ``dz/dx`` at the nose,
    so any spline in ``x`` misrepresents the leading edge — which is exactly
    where a panel method most needs accuracy.

Trailing edge
    Natural end conditions are used at both trailing-edge points. The trailing
    edge is a genuine corner with a finite included angle, and a periodic or
    smoothed spline would round it off, changing the Kutta condition that the
    Phase 2 solver applies there.

Clustering
    See :func:`clustered_fractions`. Classical cosine spacing is recovered
    exactly as a special case.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.special import betaincinv

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil

FloatArray = NDArray[np.float64]

__all__ = ["clustered_fractions", "repanel", "ContourSpline"]

#: Clustering exponent that reproduces classical cosine spacing.
COSINE = 0.5
#: Clustering exponent that gives uniform spacing.
UNIFORM = 1.0

_MIN_CLUSTERING = 1e-3
_MAX_CLUSTERING = 4.0


def clustered_fractions(
    n: int, le_clustering: float = COSINE, te_clustering: float = COSINE
) -> FloatArray:
    """``n`` fractions spanning [0, 1] with independent end clustering.

    The distribution is the inverse CDF of a Beta distribution evaluated on
    uniformly spaced probabilities. That is not an arbitrary choice: the Beta
    density ``t**(a-1) * (1-t)**(b-1)`` puts more mass near an end as that end's
    exponent falls below one, and its inverse CDF turns uniform input into
    points concentrated there. Two exponents therefore give exactly two knobs,
    one per end, with no interaction and guaranteed monotonicity.

    The classical case falls out cleanly. For ``a = b = 1/2`` the Beta CDF is
    ``(2/pi) * arcsin(sqrt(t))``, so its inverse is ``sin(pi*u/2)**2``, which is
    ``(1 - cos(pi*u))/2`` — classical cosine spacing, to machine precision.

    Parameters
    ----------
    n : int
        Number of fractions returned, including both endpoints.
    le_clustering : float, optional
        Beta exponent controlling density at the **start** of the interval (the
        leading edge when applied to a surface). ``0.5`` gives classical cosine
        spacing (default), ``1.0`` gives uniform spacing, and smaller values
        cluster more tightly. Must lie in (0, 4].
    te_clustering : float, optional
        As above, for the **end** of the interval (the trailing edge).

    Returns
    -------
    ndarray
        Monotonically increasing fractions, ``f[0] == 0`` and ``f[-1] == 1``.

    Raises
    ------
    GeometryError
        If ``n < 2`` or either exponent is outside (0, 4].

    Examples
    --------
    >>> import numpy as np
    >>> f = clustered_fractions(5)
    >>> np.allclose(f, (1 - np.cos(np.pi * np.linspace(0, 1, 5))) / 2)
    True
    """
    if n < 2:
        raise GeometryError(f"need at least 2 fractions, got {n}")
    for label, value in (("le_clustering", le_clustering), ("te_clustering", te_clustering)):
        if not _MIN_CLUSTERING <= value <= _MAX_CLUSTERING:
            raise GeometryError(
                f"{label} must lie in [{_MIN_CLUSTERING}, {_MAX_CLUSTERING}]; got "
                f"{value}. 0.5 is classical cosine spacing, 1.0 is uniform."
            )

    u = np.linspace(0.0, 1.0, n)
    fractions = betaincinv(le_clustering, te_clustering, u)
    # Pin the endpoints: betaincinv is accurate but the endpoints must be exact,
    # because they are the trailing- and leading-edge points of the contour.
    fractions[0] = 0.0
    fractions[-1] = 1.0
    if np.any(np.diff(fractions) <= 0.0):
        raise GeometryError(
            "the requested clustering produced a non-monotonic distribution; "
            f"reduce the point count ({n}) or move the exponents towards 1.0"
        )
    return fractions


class ContourSpline:
    """Cubic-spline representation of an airfoil contour in arc length.

    Parameters
    ----------
    airfoil : Airfoil
        The contour to represent.

    Attributes
    ----------
    total_length : float
        Arc length from the upper trailing edge round to the lower trailing
        edge, in chords.
    s_le : float
        Arc length at the leading edge, in chords. Found by maximising distance
        from the trailing-edge midpoint along the spline, so it is not tied to
        any input point.

    Notes
    -----
    Natural end conditions are used, preserving the trailing-edge corner.
    """

    def __init__(self, airfoil: Airfoil) -> None:
        self._x, self._z = airfoil.spline
        self.total_length = float(airfoil.arc_length[-1])
        self.s_le = airfoil.s_le

    def evaluate(self, s: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Coordinates at arc lengths ``s``, in chords."""
        return self._x(s), self._z(s)


def repanel(
    airfoil: Airfoil,
    n_points: int = 161,
    *,
    le_clustering: float = COSINE,
    te_clustering: float = COSINE,
    split: Literal["arclength", "even"] = "arclength",
) -> Airfoil:
    """Respline an airfoil and redistribute its points.

    The trailing-edge gap is preserved exactly: the two trailing-edge points sit
    at the ends of the arc-length parametrisation and are reproduced by the
    spline, so a sharp trailing edge stays sharp and a finite-thickness one
    keeps its base height.

    Parameters
    ----------
    airfoil : Airfoil
        Contour to repanel.
    n_points : int, optional
        Total number of points in the result. Must be odd so the leading edge is
        a single shared point. Default 161, giving 160 panels.
    le_clustering, te_clustering : float, optional
        Clustering exponents; see :func:`clustered_fractions`. Defaults give
        classical cosine spacing at both ends. Lower values pack points more
        tightly at that end.
    split : {"arclength", "even"}, optional
        How to divide panels between the two surfaces. ``"arclength"`` (default)
        divides them in proportion to each surface's arc length, giving the same
        resolution on both; ``"even"`` gives each surface the same count. The two
        are identical for a symmetric section and differ by a few percent for a
        strongly cambered one.

    Returns
    -------
    Airfoil
        A new contour with ``n_points`` points. The original is unchanged.

    Raises
    ------
    GeometryError
        If ``n_points`` is even or too small, or if the clustering exponents are
        out of range.

    Notes
    -----
    Round-tripping is close to lossless but is not exactly so, and cannot be:
    resplining is an interpolation, and interpolation of a curve that is only
    known at points must lose something. On a 200-point NACA section a
    200 -> 160 -> 200 round trip changes the enclosed area by roughly 0.01%,
    an order of magnitude inside the 0.1% requirement. The error is dominated
    by the leading edge, where curvature is highest.
    """
    if n_points % 2 == 0:
        raise GeometryError(
            f"n_points must be odd so the leading edge is a single shared point, "
            f"got {n_points}. Try {n_points + 1}."
        )
    if n_points < 21:
        raise GeometryError(
            f"n_points must be at least 21 to resolve a section, got {n_points}"
        )

    spline = ContourSpline(airfoil)
    s_le = spline.s_le
    s_end = spline.total_length
    n_panels = n_points - 1

    if split == "arclength":
        upper_panels = int(round(n_panels * s_le / s_end))
    elif split == "even":
        upper_panels = n_panels // 2
    else:
        raise GeometryError(
            f"split must be 'arclength' or 'even', got {split!r}"
        )
    upper_panels = int(np.clip(upper_panels, 3, n_panels - 3))
    lower_panels = n_panels - upper_panels

    # Both surfaces are distributed from the leading edge aft, so `le_clustering`
    # always controls the nose and `te_clustering` always controls the tail,
    # regardless of the direction the contour is stored in.
    upper_fraction = clustered_fractions(upper_panels + 1, le_clustering, te_clustering)
    lower_fraction = clustered_fractions(lower_panels + 1, le_clustering, te_clustering)

    # Upper surface runs from s = s_le (leading edge) down to s = 0 (trailing
    # edge); reverse it so the assembled array ascends in arc length.
    s_upper = (s_le * (1.0 - upper_fraction))[::-1]
    s_lower = s_le + lower_fraction * (s_end - s_le)

    s_new = np.concatenate([s_upper, s_lower[1:]])
    # Pin the ends to the exact original trailing-edge parameters so the gap is
    # reproduced bit for bit rather than to spline round-off.
    s_new[0] = 0.0
    s_new[-1] = s_end

    x_new, z_new = spline.evaluate(s_new)
    return Airfoil(x_new, z_new, name=airfoil.name)
