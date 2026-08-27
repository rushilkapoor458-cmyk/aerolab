"""The :class:`Airfoil` container and extraction of geometric properties.

Conventions
-----------
Coordinates are non-dimensionalised by chord: ``x`` runs aft from the leading
edge, ``z`` is positive up. Points are stored in **Selig order** — starting at
the upper trailing edge, forward along the upper surface to the leading edge,
then aft along the lower surface to the lower trailing edge. Traversed that
way the contour is **counter-clockwise** in the (x, z) plane: the upper surface
is walked from right to left across positive ``z``, which is the positive sense
of rotation. The signed shoelace area is therefore **positive**. This is
asserted on construction and relied on by :mod:`aerolab.geometry.panels` when
it orients panel normals outward.

Thickness convention
--------------------
``thickness_at`` reports the **vertical** distance ``z_upper(x) - z_lower(x)``
at a common ``x`` station. This is *not* the same as the NACA thickness
function ``2*y_t(x)``, which is measured perpendicular to the camber line and
laid off at shifted ``x`` stations. The two agree exactly for a symmetric
airfoil and differ by ``O(camber slope squared)`` otherwise — for NACA 4412
the discrepancy is a few tenths of a percent. The vertical definition is used
here because it is the only one that is well posed for an arbitrary imported
airfoil, whose camber line is not known a priori. See NOTES.md, A1.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import NamedTuple

import numpy as np
from numpy.polynomial import Polynomial
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import CubicSpline, PchipInterpolator
from scipy.optimize import minimize_scalar

from aerolab.exceptions import GeometryError
from aerolab.geometry.spline import contour_spline, cumulative_arc_length, refine_le

FloatArray = NDArray[np.float64]

__all__ = ["Airfoil", "Extremum"]

#: Segments shorter than this (in chords) are treated as duplicate points.
_MIN_SEGMENT_LENGTH = 1e-12


class Extremum(NamedTuple):
    """An extremal value of a distribution and the station where it occurs.

    Attributes
    ----------
    value : float
        The extremal value, non-dimensionalised by chord.
    x : float
        Chordwise station ``x/c`` at which it occurs.
    """

    value: float
    x: float


def _as_coordinate_array(values: ArrayLike, label: str) -> FloatArray:
    """Coerce to a read-only 1-D float64 array, or raise."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise GeometryError(f"{label} must be one-dimensional, got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        bad = int(np.argmax(~np.isfinite(arr)))
        raise GeometryError(f"{label} contains a non-finite value at index {bad}")
    out = arr.copy()
    out.flags.writeable = False
    return out


def _signed_area(x: FloatArray, z: FloatArray) -> float:
    """Signed shoelace area of the closed polygon, in chords squared.

    Positive for a counter-clockwise traversal, which is what Selig ordering
    gives. The polygon is closed implicitly from the last point back to the
    first, so an airfoil with an open trailing edge is closed by a straight
    base segment across the gap.
    """
    return 0.5 * float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z))


def _strictly_increasing(
    x: FloatArray, z: FloatArray, *, max_dropped: int, label: str
) -> tuple[FloatArray, FloatArray]:
    """Drop points that do not strictly increase in ``x``.

    A classically constructed cambered airfoil lays its surface points off
    perpendicular to the camber line, which can push the first point or two of
    a surface to slightly *negative* ``x``. That makes ``x`` non-monotone over
    a couple of points right at the nose. Dropping them is harmless. Dropping
    many of them is not — it means the geometry is not a simple single-valued
    surface, and this raises instead.
    """
    keep = [0]
    for i in range(1, x.size):
        if x[i] > x[keep[-1]]:
            keep.append(i)
    dropped = x.size - len(keep)
    if dropped > max_dropped:
        raise GeometryError(
            f"the {label} surface is not single-valued in x: {dropped} of {x.size} "
            f"points would have to be discarded to make it monotone (limit "
            f"{max_dropped}). Vertical thickness and camber are undefined for such "
            "a geometry."
        )
    index = np.asarray(keep, dtype=np.intp)
    return x[index], z[index]


@dataclass(frozen=True, eq=False)
class Airfoil:
    """An airfoil contour, stored as a closed loop of surface points.

    Parameters
    ----------
    x, z : array_like
        Surface coordinates in **Selig order** (upper trailing edge, forward
        over the upper surface to the leading edge, aft over the lower surface
        to the lower trailing edge), non-dimensionalised by chord.
    name : str, optional
        Label used in plots and file headers. Carries no meaning to the solvers.

    Raises
    ------
    GeometryError
        If the contour is not a valid, clockwise, Selig-ordered airfoil. The
        constructor is deliberately strict: it is the single place where the
        ordering invariant is established, and every downstream module relies
        on it. Use :meth:`from_points` to repair a contour of unknown ordering.

    Notes
    -----
    Instances are immutable and their coordinate arrays are marked read-only,
    so derived quantities can be cached safely. Every geometric property is
    computed lazily on first access.
    """

    x: FloatArray = field()
    z: FloatArray = field()
    name: str = "unnamed"

    def __post_init__(self) -> None:
        x = _as_coordinate_array(self.x, "x")
        z = _as_coordinate_array(self.z, "z")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "z", z)

        if x.size != z.size:
            raise GeometryError(f"x and z differ in length: {x.size} vs {z.size}")
        if x.size < 7:
            raise GeometryError(
                f"an airfoil needs at least 7 points to have a defined leading "
                f"edge and two surfaces; got {x.size}"
            )

        segments = np.hypot(np.diff(x), np.diff(z))
        if np.any(segments < _MIN_SEGMENT_LENGTH):
            bad = int(np.argmin(segments))
            raise GeometryError(
                f"zero-length segment between points {bad} and {bad + 1} "
                f"at ({x[bad]:.6f}, {z[bad]:.6f}); duplicate points must be "
                "removed before construction"
            )

        x_max = float(np.max(x))
        trailing_tol = 0.02 * (x_max - float(np.min(x)))
        if (x_max - x[0]) > trailing_tol or (x_max - x[-1]) > trailing_tol:
            raise GeometryError(
                "coordinates are not in Selig order: the contour must both start "
                f"and end at the trailing edge (x_max = {x_max:.4f}, but the first "
                f"and last points are at x = {x[0]:.4f} and {x[-1]:.4f})"
            )

        area = _signed_area(x, z)
        if area <= 0.0:
            raise GeometryError(
                "coordinates are ordered clockwise (signed area "
                f"{area:+.6f}); Selig order traverses the contour "
                "counter-clockwise, upper surface first. Use "
                "Airfoil.from_points() to repair the ordering."
            )

    # ---------------------------------------------------------------- factory

    @classmethod
    def from_points(
        cls, x: ArrayLike, z: ArrayLike, name: str = "unnamed"
    ) -> "Airfoil":
        """Build an airfoil from points of unknown ordering, repairing what can be repaired.

        Removes duplicate consecutive points and reverses the contour if it is
        clockwise (that is, if the lower surface was listed first). It does
        **not** re-order a contour that starts part way along a surface — that
        is not repairable without guessing, and guessing is how silent errors
        get in.

        Parameters
        ----------
        x, z : array_like
            Surface coordinates, non-dimensionalised by chord.
        name : str, optional
            Label for the airfoil.

        Returns
        -------
        Airfoil
            A validated airfoil in Selig order.
        """
        xa = np.asarray(x, dtype=np.float64).ravel()
        za = np.asarray(z, dtype=np.float64).ravel()
        if xa.size != za.size:
            raise GeometryError(f"x and z differ in length: {xa.size} vs {za.size}")

        keep = np.ones(xa.size, dtype=bool)
        keep[1:] = np.hypot(np.diff(xa), np.diff(za)) >= _MIN_SEGMENT_LENGTH
        xa, za = xa[keep], za[keep]

        if _signed_area(xa, za) < 0.0:
            xa, za = xa[::-1].copy(), za[::-1].copy()

        return cls(xa, za, name=name)

    # ------------------------------------------------------------- basic size

    def __len__(self) -> int:
        return int(self.x.size)

    def __repr__(self) -> str:
        t = self.max_thickness
        return (
            f"<Airfoil {self.name!r}: {len(self)} points, "
            f"t_max={t.value:.4f}c at x/c={t.x:.3f}, "
            f"TE gap={self.te_gap:.5f}c>"
        )

    @property
    def n_points(self) -> int:
        """Number of surface points in the contour."""
        return int(self.x.size)

    @property
    def n_panels(self) -> int:
        """Number of panels the contour would yield (``n_points - 1``)."""
        return int(self.x.size) - 1

    @property
    def points(self) -> FloatArray:
        """Surface points as an ``(n, 2)`` array of ``(x, z)`` pairs."""
        return np.column_stack([self.x, self.z])

    # ----------------------------------------------------- landmark locations

    @cached_property
    def te_point(self) -> FloatArray:
        """Midpoint of the trailing edge, as ``(x, z)`` in chords.

        For a sharp trailing edge this is the trailing-edge point itself; for a
        finite-thickness trailing edge it is the centre of the base.
        """
        return np.array(
            [0.5 * (self.x[0] + self.x[-1]), 0.5 * (self.z[0] + self.z[-1])]
        )

    @cached_property
    def te_gap(self) -> float:
        """Trailing-edge thickness (base height), in chords.

        Zero for a sharp trailing edge. The NACA generators produce 0.00252c
        for a 12% airfoil unless a closed trailing edge is requested.
        """
        return float(np.hypot(self.x[0] - self.x[-1], self.z[0] - self.z[-1]))

    def is_sharp_te(self, tol: float = 1e-9) -> bool:
        """Whether the trailing edge is sharp to within ``tol`` chords."""
        return self.te_gap <= tol

    @cached_property
    def te_included_angle(self) -> float:
        """Included angle at the trailing edge, in **radians**.

        The wedge angle between the upper-surface and lower-surface tangents as
        they arrive at the trailing edge. Zero for a cusped trailing edge. This
        governs how badly conditioned the Kutta condition will be in the Phase 2
        panel solver.

        Estimated from the single panel at each end of the contour, so it is a
        discrete approximation whose accuracy depends on how finely the trailing
        edge is panelled. For a closed-trailing-edge NACA 0012 the analytic
        value is 16.55 degrees (0.2889 rad).
        """
        upper = np.array([self.x[0] - self.x[1], self.z[0] - self.z[1]])
        lower = np.array([self.x[-1] - self.x[-2], self.z[-1] - self.z[-2]])
        upper /= np.linalg.norm(upper)
        lower /= np.linalg.norm(lower)
        cos_angle = float(np.clip(np.dot(upper, lower), -1.0, 1.0))
        return float(np.arccos(cos_angle))

    @cached_property
    def le_index(self) -> int:
        """Index of the leading-edge point: the point furthest from the trailing edge.

        Distance from the trailing edge is used rather than minimum ``x``
        because the two differ for a cambered airfoil, and the furthest-point
        definition is the one that splits the contour into two well-behaved
        surfaces.
        """
        te = self.te_point
        return int(np.argmax(np.hypot(self.x - te[0], self.z - te[1])))

    @cached_property
    def le_point(self) -> FloatArray:
        """Leading-edge point as ``(x, z)`` in chords."""
        i = self.le_index
        return np.array([self.x[i], self.z[i]])

    @cached_property
    def chord(self) -> float:
        """Chord length: leading-edge point to trailing-edge midpoint, in chords.

        Equals 1.0 for a normalised airfoil. A value away from 1.0 means the
        contour has not been normalised; see :meth:`normalize`.
        """
        return float(np.linalg.norm(self.te_point - self.le_point))

    # ------------------------------------------------------- integral properties

    @cached_property
    def signed_area(self) -> float:
        """Signed shoelace area, in chords squared. Positive for Selig order."""
        return _signed_area(self.x, self.z)

    @cached_property
    def area(self) -> float:
        """Enclosed cross-sectional area, in chords squared.

        An open trailing edge is closed by a straight base segment across the
        gap, which is the same convention the panel methods use.
        """
        return abs(self.signed_area)

    @cached_property
    def perimeter(self) -> float:
        """Surface arc length from trailing edge round to trailing edge, in chords.

        Excludes the trailing-edge base segment.
        """
        return float(np.sum(np.hypot(np.diff(self.x), np.diff(self.z))))

    @cached_property
    def arc_length(self) -> FloatArray:
        """Cumulative arc length at each point, in chords, starting at zero.

        Measured along the contour from the upper trailing edge, so it
        increases monotonically through the leading edge to the lower trailing
        edge.
        """
        return cumulative_arc_length(self.x, self.z)

    @cached_property
    def spline(self) -> tuple[CubicSpline, CubicSpline]:
        """Cubic splines ``x(s)``, ``z(s)`` against arc length, natural end conditions."""
        spline_x, spline_z, _ = contour_spline(self.x, self.z, self.arc_length)
        return spline_x, spline_z

    @cached_property
    def s_le(self) -> float:
        """Arc length at the leading edge, in chords, refined on the spline.

        Not tied to any input point: the leading edge is located by maximising
        distance from the trailing-edge midpoint along the continuous curve.
        """
        s = self.arc_length
        i = self.le_index
        spline_x, spline_z = self.spline
        return refine_le(
            spline_x,
            spline_z,
            self.te_point,
            s_lo=float(s[max(i - 1, 0)]),
            s_hi=float(s[min(i + 1, s.size - 1)]),
            s_guess=float(s[i]),
        )

    @cached_property
    def _le_frame(self) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Origin, nose axis and cross-axis of the leading-edge frame.

        The origin is the refined leading-edge point. Because that point
        maximises distance from the trailing edge, the surface tangent there is
        perpendicular to the chord line, so the tangent and its normal form a
        frame aligned with the nose. ``axis`` points from the leading edge into
        the section; ``cross`` is perpendicular to it, along the surface.
        """
        spline_x, spline_z = self.spline
        s_le = self.s_le
        origin = np.array([float(spline_x(s_le)), float(spline_z(s_le))])

        tangent = np.array([float(spline_x(s_le, 1)), float(spline_z(s_le, 1))])
        norm = float(np.linalg.norm(tangent))
        if norm < 1e-14:
            raise GeometryError(
                "the contour spline has a vanishing tangent at the leading edge; "
                "the points near the nose are probably duplicated or collinear"
            )
        cross = tangent / norm
        axis = np.array([-cross[1], cross[0]])
        # Orient the axis into the section rather than out of the nose.
        if float(np.dot(axis, self.te_point - origin)) < 0.0:
            axis = -axis
        return origin, axis, cross

    # --------------------------------------------------------------- surfaces

    def surfaces(self) -> tuple[tuple[FloatArray, FloatArray], tuple[FloatArray, FloatArray]]:
        """Split the contour into upper and lower surfaces.

        Returns
        -------
        upper : tuple of ndarray
            ``(x, z)`` running from the leading edge aft to the trailing edge.
        lower : tuple of ndarray
            ``(x, z)`` running from the leading edge aft to the trailing edge.

        Notes
        -----
        Both surfaces include the leading-edge point, so they share one point
        and their lengths sum to ``n_points + 1``.
        """
        i = self.le_index
        upper = (self.x[i::-1].copy(), self.z[i::-1].copy())
        lower = (self.x[i:].copy(), self.z[i:].copy())
        return upper, lower

    @cached_property
    def _branch_interpolators(
        self,
    ) -> tuple[PchipInterpolator, PchipInterpolator, float, float]:
        """Monotone interpolators for each surface, parametrised by ``sqrt(x - x_le)``.

        The square-root abscissa matters. Near the nose an airfoil surface
        behaves like ``z ~ sqrt(x)``, which has infinite slope at ``x = 0`` and
        which any interpolant in ``x`` will represent badly. In
        ``xi = sqrt(x - x_le)`` the same surface is very nearly linear, so a
        monotone cubic (PCHIP) is accurate right up to the leading edge.

        PCHIP rather than a natural cubic spline because it is shape-preserving:
        it will not introduce the spurious overshoot near the nose that a cubic
        spline produces on rapidly varying data, and an overshoot there would
        show up directly as a wrong leading-edge thickness.
        """
        (xu, zu), (xl, zl) = self.surfaces()
        x_le = float(self.le_point[0])
        limit = max(2, int(0.02 * self.n_points))

        xu, zu = _strictly_increasing(xu, zu, max_dropped=limit, label="upper")
        xl, zl = _strictly_increasing(xl, zl, max_dropped=limit, label="lower")

        xi_u = np.sqrt(np.maximum(xu - x_le, 0.0))
        xi_l = np.sqrt(np.maximum(xl - x_le, 0.0))

        upper = PchipInterpolator(xi_u, zu, extrapolate=False)
        lower = PchipInterpolator(xi_l, zl, extrapolate=False)
        return upper, lower, x_le, float(min(xu[-1], xl[-1]))

    @property
    def x_range(self) -> tuple[float, float]:
        """Chordwise range over which thickness and camber are defined.

        The lower bound is the leading-edge station; the upper bound is the
        smaller of the two surfaces' trailing-edge stations, since a vertical
        cut beyond that intersects only one surface.
        """
        _, _, x_le, x_max = self._branch_interpolators
        return x_le, x_max

    def _cut(self, x: ArrayLike) -> tuple[FloatArray, FloatArray]:
        """Upper and lower surface heights at chordwise stations ``x``."""
        upper, lower, x_le, x_max = self._branch_interpolators
        xq = np.atleast_1d(np.asarray(x, dtype=np.float64))
        tol = 1e-9
        if np.any(xq < x_le - tol) or np.any(xq > x_max + tol):
            raise GeometryError(
                f"chordwise station outside the airfoil: requested "
                f"[{float(np.min(xq)):.6f}, {float(np.max(xq)):.6f}], "
                f"defined on [{x_le:.6f}, {x_max:.6f}]. Vertical cuts outside "
                "this range do not intersect both surfaces."
            )
        xi = np.sqrt(np.clip(xq - x_le, 0.0, None))
        return upper(xi), lower(xi)

    # ------------------------------------------------ thickness and camber

    def thickness_at(self, x: ArrayLike) -> FloatArray:
        """Vertical thickness at chordwise stations ``x``.

        Parameters
        ----------
        x : array_like
            Chordwise stations ``x/c``, within :attr:`x_range`.

        Returns
        -------
        ndarray
            ``z_upper(x) - z_lower(x)``, in chords. Always non-negative for a
            valid airfoil.

        Raises
        ------
        GeometryError
            If any station lies outside :attr:`x_range`. Thickness is never
            extrapolated.
        """
        zu, zl = self._cut(x)
        return zu - zl

    def camber_at(self, x: ArrayLike) -> FloatArray:
        """Mean-line height at chordwise stations ``x``.

        Parameters
        ----------
        x : array_like
            Chordwise stations ``x/c``, within :attr:`x_range`.

        Returns
        -------
        ndarray
            ``(z_upper(x) + z_lower(x)) / 2``, in chords. Positive means the
            mean line lies above the chord line.

        Notes
        -----
        This is the mean line of *vertical* cuts, which for a cambered airfoil
        is very slightly different from the NACA camber line used to construct
        it (the construction lays thickness off perpendicular to the mean line,
        not vertically). See NOTES.md, A1.4.
        """
        zu, zl = self._cut(x)
        return 0.5 * (zu + zl)

    def thickness_distribution(self, n: int = 201) -> tuple[FloatArray, FloatArray]:
        """Thickness sampled on a cosine-clustered chordwise grid.

        Parameters
        ----------
        n : int, optional
            Number of stations.

        Returns
        -------
        x, t : ndarray
            Stations ``x/c`` and vertical thickness ``t/c``.
        """
        x = self._cosine_stations(n)
        return x, self.thickness_at(x)

    def camber_distribution(self, n: int = 201) -> tuple[FloatArray, FloatArray]:
        """Camber sampled on a cosine-clustered chordwise grid.

        Parameters
        ----------
        n : int, optional
            Number of stations.

        Returns
        -------
        x, zc : ndarray
            Stations ``x/c`` and mean-line height ``z/c``.
        """
        x = self._cosine_stations(n)
        return x, self.camber_at(x)

    def _cosine_stations(self, n: int) -> FloatArray:
        """``n`` cosine-clustered stations spanning :attr:`x_range`."""
        if n < 3:
            raise GeometryError(f"need at least 3 stations, got {n}")
        lo, hi = self.x_range
        beta = np.linspace(0.0, np.pi, n)
        return lo + (hi - lo) * 0.5 * (1.0 - np.cos(beta))

    def _argmax_station(self, func, n_scan: int = 2001) -> float:
        """Chordwise station maximising ``func`` over :attr:`x_range`.

        A coarse scan brackets the maximum, then a bounded Brent search refines
        it against the continuous interpolant. Refining matters: on a 200-point
        airfoil the chordwise spacing near mid-chord is around 0.015c, so the
        location of maximum thickness read straight off the discrete points can
        be wrong by more than 0.007c — enough to fail a "max thickness at
        x/c = 0.30" check for reasons that have nothing to do with the geometry.

        Only the *station* is returned; the caller evaluates the quantity there.
        That keeps a single evaluation path for the reported value, so the
        returned value and station can never disagree.
        """
        lo, hi = self.x_range
        scan_x = self._cosine_stations(n_scan)
        scan_v = np.asarray(func(scan_x), dtype=np.float64)
        i = int(np.argmax(scan_v))
        left = max(scan_x[max(i - 1, 0)], lo)
        right = min(scan_x[min(i + 1, n_scan - 1)], hi)
        if left >= right:
            return float(scan_x[i])

        result = minimize_scalar(
            lambda xx: -float(np.asarray(func(np.array([xx])))[0]),
            bounds=(left, right),
            method="bounded",
            options={"xatol": 1e-10},
        )
        # Fall back to the scan maximum rather than trusting a refinement the
        # optimiser did not actually converge to.
        return float(result.x) if result.success else float(scan_x[i])

    @cached_property
    def max_thickness(self) -> Extremum:
        """Maximum vertical thickness and the station where it occurs.

        Returns
        -------
        Extremum
            ``value`` is ``t_max/c``; ``x`` is ``x/c`` at that station.
        """
        station = self._argmax_station(self.thickness_at)
        return Extremum(float(self.thickness_at(np.array([station]))[0]), station)

    @cached_property
    def max_camber(self) -> Extremum:
        """Maximum camber (by magnitude) and the station where it occurs.

        Returns
        -------
        Extremum
            ``value`` is the signed mean-line height ``z/c`` at the station of
            greatest ``|z|``; ``x`` is ``x/c`` at that station. The value keeps
            its sign so that a reflexed or negatively cambered section is not
            silently reported as positively cambered.
        """
        station = self._argmax_station(lambda xx: np.abs(self.camber_at(xx)))
        return Extremum(float(self.camber_at(np.array([station]))[0]), station)

    @cached_property
    def le_radius(self) -> float:
        """Leading-edge radius of curvature, in chords.

        Returns
        -------
        float
            Radius of the osculating circle at the nose, in chords.

        Raises
        ------
        GeometryError
            If either surface has fewer than five points near the nose. Fitting
            a curve through four points and reporting the result would be
            exactly the kind of plausible wrong number this package refuses to
            produce; repanel with more leading-edge clustering instead.

        Notes
        -----
        The contour is first rotated into the leading-edge frame, then each
        surface is fitted as ``eta = p1*sqrt(zeta) + p2*zeta + ...`` and the
        radius read off the leading coefficient as ``r = p1**2 / 2``. Both
        surfaces are fitted and averaged.

        The square-root abscissa is the whole point. A surface near the nose
        behaves like ``eta ~ sqrt(zeta)``, so written the other way round
        ``zeta`` contains a term in ``|eta|**3`` — even, but with a
        discontinuous third derivative at the nose. Polynomials in ``eta``
        converge against that only algebraically, which is why a direct circle
        or parabola fit is biased by whole percent and drifts with whatever
        window is chosen. In ``sqrt(zeta)`` the surface is analytic and a
        quartic fit is essentially exact.

        Accuracy differs sharply between symmetric and cambered sections. The
        figures below are measured, not argued:

        - **Symmetric.** Reproduces the closed-form ``1.1019 * t**2`` to within
          0.01%, and moves by only 0.002% between 201 and 3201 points.
          Effectively exact.
        - **Cambered.** Lands within about 0.7% of ``1.1019 * t**2`` (measured:
          +0.2% for NACA 2412, +0.7% for 4412, -0.6% for 23012), but wanders by
          up to 0.8% with point count. The scatter is the same size as the
          departure, so **no claim is made about a cambered nose radius beyond
          roughly 1%**, and in particular the sign of the departure from the
          symmetric value is not resolved. The limitation is the leading-edge
          frame: for a cambered section the nose axis comes from the spline
          tangent at the refined leading edge, which carries its own
          discretisation error. See NOTES.md, L1.3.
        """
        origin, axis, cross = self._le_frame
        delta = self.points - origin
        zeta = delta @ axis
        eta = delta @ cross

        i = self.le_index
        radii = []
        for label, index in (
            ("upper", np.arange(i, -1, -1)),
            ("lower", np.arange(i, self.n_points)),
        ):
            z_branch = zeta[index]
            e_branch = eta[index]
            window = 0.03
            for _ in range(4):
                mask = (z_branch >= 0.0) & (z_branch <= window)
                if int(np.count_nonzero(mask)) >= 6:
                    break
                window *= 2.0
            count = int(np.count_nonzero(mask))
            if count < 5:
                raise GeometryError(
                    f"only {count} points lie within {window:.3f}c of the leading "
                    f"edge on the {label} surface; at least 5 are needed to fit a "
                    "nose radius. Repanel with more leading-edge clustering."
                )
            degree = min(4, count - 2)
            fit = Polynomial.fit(
                np.sqrt(z_branch[mask]), np.abs(e_branch[mask]), degree
            )
            p1 = float(fit.deriv(1)(0.0))
            radii.append(0.5 * p1**2)

        return float(np.mean(radii))

    # ---------------------------------------------------------- transformations

    def normalize(self) -> "Airfoil":
        """Return a copy translated, rotated and scaled to unit chord.

        The leading-edge point is moved to the origin and the trailing-edge
        midpoint to ``(1, 0)``. Imported coordinate files are frequently a
        fraction of a percent off unit chord, or carry a small rotation; the
        panel methods assume neither.

        Returns
        -------
        Airfoil
            A new airfoil; the original is unchanged.
        """
        le = self.le_point
        te = self.te_point
        chord_vector = te - le
        chord = float(np.linalg.norm(chord_vector))
        if chord < 1e-9:
            raise GeometryError(
                f"cannot normalise: chord length is {chord:.3e}, "
                "the leading and trailing edges coincide"
            )
        angle = float(np.arctan2(chord_vector[1], chord_vector[0]))
        cos_a, sin_a = np.cos(-angle), np.sin(-angle)
        dx = self.x - le[0]
        dz = self.z - le[1]
        x_new = (dx * cos_a - dz * sin_a) / chord
        z_new = (dx * sin_a + dz * cos_a) / chord
        return Airfoil(x_new, z_new, name=self.name)

    def reversed(self) -> "Airfoil":
        """Return a copy with the point order reversed.

        Because :meth:`from_points` restores the counter-clockwise invariant,
        the returned airfoil is geometrically identical to this one. This exists
        for round-tripping files written in the opposite order, not as a way to
        obtain a reversed contour.
        """
        return Airfoil.from_points(self.x[::-1], self.z[::-1], name=self.name)
