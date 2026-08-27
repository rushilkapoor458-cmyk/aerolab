"""Analytic NACA 4-digit and 5-digit section generators.

Everything here is derived from the defining relations rather than read from a
table. In particular the 5-digit camber-line constants ``m`` and ``k1`` are
obtained by root-finding on the conditions that *define* them — position of
maximum camber for ``m``, design lift coefficient for ``k1``, and zero
quarter-chord pitching moment for the reflexed series — and the published
tabulations in Abbott & von Doenhoff are then used as an independent check in
the tests, not as an input.

References
----------
Abbott, I. H. and von Doenhoff, A. E., *Theory of Wing Sections*, Dover, 1959.
Jacobs, E. N., Ward, K. E. and Pinkerton, R. M., "The characteristics of 78
related airfoil sections from tests in the variable-density wind tunnel",
NACA Report 460, 1933.
Jacobs, E. N., Pinkerton, R. M. and Greenberg, H., "Tests of related forward-
camber airfoils in the variable-density wind tunnel", NACA Report 610, 1937.

Conventions
-----------
All lengths are non-dimensionalised by chord. ``x`` runs from 0 at the leading
edge to 1 at the trailing edge. Camber ``y_c`` and half-thickness ``y_t`` are
in chords. No angles appear in this module's public API; the ``theta`` used
internally is the camber-line inclination in radians.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import brentq

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil

FloatArray = NDArray[np.float64]

__all__ = [
    "naca",
    "naca4",
    "naca5",
    "thickness_distribution",
    "camber_line_4digit",
    "camber_line_5digit",
    "FiveDigitCamber",
    "solve_five_digit_camber",
]

# Coefficients of the NACA thickness function
#     y_t = 5t (a0*sqrt(x) + a1*x + a2*x^2 + a3*x^3 + a4*x^4)
# The original series uses a4 = -0.1015, for which the coefficients sum to
# 0.0021 rather than zero, leaving a trailing-edge half-gap of 0.0105*t. The
# widely used closed variant changes a4 to -0.1036 so the sum is exactly zero.
# That change is not free: it perturbs the whole polynomial slightly, and the
# maximum thickness of a "12%" section becomes 0.12001c instead of 0.12000c.
# See NOTES.md, A1.1.
_A0, _A1, _A2, _A3 = 0.2969, -0.1260, -0.3516, 0.2843
_A4_OPEN = -0.1015
_A4_CLOSED = -0.1036

#: Design lift coefficient per unit of the first digit of a 5-digit designation.
_CL_PER_FIRST_DIGIT = 0.15
#: Chordwise position of maximum camber per unit of the second digit.
_XF_PER_SECOND_DIGIT = 0.05


# --------------------------------------------------------------------------
# Thickness
# --------------------------------------------------------------------------


def thickness_distribution(
    x: ArrayLike, thickness: float, *, closed_te: bool = True
) -> FloatArray:
    """NACA half-thickness ``y_t`` at chordwise stations ``x``.

    Parameters
    ----------
    x : array_like
        Chordwise stations ``x/c`` in [0, 1].
    thickness : float
        Maximum thickness as a fraction of chord (0.12 for a "12%" section).
    closed_te : bool, optional
        If True (default) use the modified quartic coefficient that closes the
        trailing edge exactly. If False use the original NACA coefficient,
        which leaves a half-gap of ``0.0105 * thickness`` at ``x = 1``.

    Returns
    -------
    ndarray
        Half-thickness ``y_t/c``, measured **perpendicular to the camber line**
        (which for a symmetric section is the chord line). The full thickness
        of the section is ``2 * y_t``.

    Notes
    -----
    The leading edge is a parabola: as ``x -> 0``, ``y_t -> 5*t*a0*sqrt(x)``,
    which corresponds to a leading-edge radius of ``(5*t*a0)**2 / 2``, or
    ``1.1019 * t**2``. That closed form is used as a test target for
    :attr:`~aerolab.geometry.airfoil.Airfoil.le_radius`.
    """
    xa = np.asarray(x, dtype=np.float64)
    if np.any(xa < -1e-12) or np.any(xa > 1.0 + 1e-12):
        raise GeometryError(
            f"thickness stations must lie in [0, 1]; got "
            f"[{float(np.min(xa)):.6f}, {float(np.max(xa)):.6f}]"
        )
    if thickness <= 0.0:
        raise GeometryError(f"thickness must be positive, got {thickness}")
    xa = np.clip(xa, 0.0, 1.0)
    a4 = _A4_CLOSED if closed_te else _A4_OPEN
    return 5.0 * thickness * (
        _A0 * np.sqrt(xa) + _A1 * xa + _A2 * xa**2 + _A3 * xa**3 + a4 * xa**4
    )


# --------------------------------------------------------------------------
# 4-digit camber
# --------------------------------------------------------------------------


def camber_line_4digit(
    x: ArrayLike, max_camber: float, camber_position: float
) -> tuple[FloatArray, FloatArray]:
    """4-digit camber line and its slope.

    The mean line is two parabolic arcs meeting with continuous slope at
    ``x = p``:

    .. math::
        y_c = \\frac{m}{p^2}(2px - x^2), \\quad x < p

        y_c = \\frac{m}{(1-p)^2}\\left[(1-2p) + 2px - x^2\\right], \\quad x \\ge p

    Parameters
    ----------
    x : array_like
        Chordwise stations ``x/c`` in [0, 1].
    max_camber : float
        Maximum camber ``m`` as a fraction of chord (0.02 for a "2" first digit).
    camber_position : float
        Chordwise position ``p`` of maximum camber, as a fraction of chord
        (0.4 for a "4" second digit).

    Returns
    -------
    y_c : ndarray
        Camber-line height in chords, positive up.
    dyc_dx : ndarray
        Camber-line slope, dimensionless. ``arctan`` of this is the local mean
        line inclination in **radians**.
    """
    xa = np.asarray(x, dtype=np.float64)
    if max_camber == 0.0:
        return np.zeros_like(xa), np.zeros_like(xa)
    if not 0.0 < camber_position < 1.0:
        raise GeometryError(
            f"a cambered 4-digit section needs 0 < p < 1, got p = {camber_position}. "
            "A non-zero first digit with a zero second digit is not a valid "
            "designation."
        )

    m, p = float(max_camber), float(camber_position)
    fore = xa < p
    y_c = np.where(
        fore,
        (m / p**2) * (2.0 * p * xa - xa**2),
        (m / (1.0 - p) ** 2) * ((1.0 - 2.0 * p) + 2.0 * p * xa - xa**2),
    )
    dyc_dx = np.where(
        fore,
        (2.0 * m / p**2) * (p - xa),
        (2.0 * m / (1.0 - p) ** 2) * (p - xa),
    )
    return y_c, dyc_dx


# --------------------------------------------------------------------------
# 5-digit camber
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FiveDigitCamber:
    """Solved constants of a NACA 5-digit mean line.

    Attributes
    ----------
    m : float
        Transition station of the cubic, in chords. Not the position of maximum
        camber — that is ``x_f``, and ``m > x_f`` always.
    k1 : float
        Overall scale of the mean line, set by the design lift coefficient.
    k2_over_k1 : float
        Reflex parameter. Zero for the standard (non-reflexed) series.
    x_f : float
        Chordwise position of maximum camber, in chords.
    cl_design : float
        Design (ideal) lift coefficient the mean line was scaled to.
    reflexed : bool
        Whether this is a reflexed mean line.
    """

    m: float
    k1: float
    k2_over_k1: float
    x_f: float
    cl_design: float
    reflexed: bool


def _five_digit_slope(
    m: float, k1: float, k2_over_k1: float, reflexed: bool
) -> Callable[[FloatArray], FloatArray]:
    """Return the mean-line slope function ``dyc_dx(x)`` for given constants."""

    if not reflexed:

        def slope(xa: FloatArray) -> FloatArray:
            return np.where(
                xa < m,
                (k1 / 6.0) * (3.0 * xa**2 - 6.0 * m * xa + m**2 * (3.0 - m)),
                -(k1 * m**3) / 6.0,
            )

    else:
        tail = k2_over_k1 * (1.0 - m) ** 3 + m**3

        def slope(xa: FloatArray) -> FloatArray:
            return np.where(
                xa <= m,
                (k1 / 6.0) * (3.0 * (xa - m) ** 2 - tail),
                (k1 / 6.0) * (3.0 * k2_over_k1 * (xa - m) ** 2 - tail),
            )

    return slope


def _cosine_fourier_coefficients(
    slope: Callable[[FloatArray], FloatArray], m: float, order: int = 96
) -> tuple[float, float]:
    """Thin-airfoil-theory coefficients ``A1`` and ``A2`` of a mean line.

    With the Glauert substitution ``x = (1 - cos(theta)) / 2``,

    .. math::
        A_n = \\frac{2}{\\pi}\\int_0^{\\pi} \\frac{dy_c}{dx}\\cos(n\\theta)\\,d\\theta

    The integrand has a slope discontinuity at ``x = m``, so the interval is
    split there and each half integrated with fixed-order Gauss-Legendre
    quadrature. On each half the integrand is a smooth trigonometric
    polynomial, so a high fixed order is effectively exact and — unlike an
    adaptive rule — gives bitwise-repeatable results, which matters because
    these coefficients sit inside a root solve.
    """
    theta_break = float(np.arccos(np.clip(1.0 - 2.0 * m, -1.0, 1.0)))
    nodes, weights = np.polynomial.legendre.leggauss(order)

    a1 = 0.0
    a2 = 0.0
    for lo, hi in ((0.0, theta_break), (theta_break, np.pi)):
        if hi <= lo:
            continue
        half = 0.5 * (hi - lo)
        mid = 0.5 * (hi + lo)
        theta = half * nodes + mid
        w = half * weights
        s = slope(0.5 * (1.0 - np.cos(theta)))
        a1 += float(np.sum(w * s * np.cos(theta)))
        a2 += float(np.sum(w * s * np.cos(2.0 * theta)))

    scale = 2.0 / np.pi
    return scale * a1, scale * a2


def _bracketed_root(
    func: Callable[[float], float], lo: float, hi: float, n_scan: int = 400
) -> float:
    """Find a root of ``func`` in ``[lo, hi]``, locating a sign change first.

    Raises
    ------
    GeometryError
        If no sign change exists in the interval. A root solver handed a bad
        bracket will either raise something opaque or wander to a spurious
        answer; this reports the actual problem.
    """
    grid = np.linspace(lo, hi, n_scan)
    values = np.array([func(g) for g in grid])
    signs = np.sign(values)
    changes = np.nonzero(signs[:-1] * signs[1:] < 0)[0]
    if changes.size == 0:
        raise GeometryError(
            f"no sign change of the defining relation on [{lo:.4f}, {hi:.4f}]; "
            "the requested mean line does not exist in the NACA 5-digit family"
        )
    i = int(changes[0])
    return float(brentq(func, grid[i], grid[i + 1], xtol=1e-14, rtol=1e-15))


def solve_five_digit_camber(
    x_f: float, cl_design: float, *, reflexed: bool = False
) -> FiveDigitCamber:
    """Solve for the constants of a NACA 5-digit mean line.

    Nothing here is tabulated. The constants come out of the conditions that
    define them:

    - **Standard series.** ``m`` follows from the position of maximum camber.
      Setting the cubic's slope to zero gives ``x_f = m(1 - sqrt(m/3))``, which
      is inverted numerically for ``m``.
    - **Reflexed series.** ``m`` is instead fixed by the defining property of a
      reflexed mean line, ``Cm_c/4 = 0``, with the reflex parameter tied to
      ``m`` and ``x_f`` by ``k2/k1 = [3(m - x_f)^2 - m^3] / (1 - m)^3``. In thin
      airfoil theory ``Cm_c/4 = (pi/4)(A2 - A1)``, so the condition is
      ``A1 = A2``, which is homogeneous in ``k1`` and therefore independent of it.
    - **Both.** ``k1`` scales the mean line to the design lift coefficient. At
      the ideal angle of attack ``Cl_i = pi * A1``, and since ``A1`` is linear
      in ``k1`` the scale follows directly.

    Parameters
    ----------
    x_f : float
        Chordwise position of maximum camber, in chords (0.15 for the "230"
        series).
    cl_design : float
        Design (ideal) lift coefficient (0.3 for the "230" series).
    reflexed : bool, optional
        Whether to solve the reflexed mean line.

    Returns
    -------
    FiveDigitCamber
        The solved constants.

    Raises
    ------
    GeometryError
        If no mean line of the requested family exists for these inputs.

    Notes
    -----
    The solved constants reproduce the tabulations in Abbott & von Doenhoff to
    about 0.2% — the residual is in the published values, which were computed by
    hand in the 1930s and rounded to four decimal places, not in this solve. The
    comparison is made explicitly in ``tests/test_geometry_naca.py``.
    """
    if not 0.0 < x_f < 0.5:
        raise GeometryError(
            f"position of maximum camber must satisfy 0 < x_f < 0.5, got {x_f}"
        )

    if not reflexed:
        # x_f = m(1 - sqrt(m/3)) rises monotonically from x_f to its maximum of
        # 4/9 at m = 4/3, so the bracket (x_f, 4/3) always contains the root.
        m = _bracketed_root(
            lambda mm: mm * (1.0 - np.sqrt(mm / 3.0)) - x_f, x_f + 1e-12, 4.0 / 3.0
        )
        k2_over_k1 = 0.0
    else:

        def reflex_ratio(mm: float) -> float:
            return (3.0 * (mm - x_f) ** 2 - mm**3) / (1.0 - mm) ** 3

        def moment_residual(mm: float) -> float:
            slope = _five_digit_slope(mm, 1.0, reflex_ratio(mm), reflexed=True)
            a1, a2 = _cosine_fourier_coefficients(slope, mm)
            return a2 - a1

        m = _bracketed_root(moment_residual, x_f + 1e-6, 0.97)
        k2_over_k1 = reflex_ratio(m)

    unit_slope = _five_digit_slope(m, 1.0, k2_over_k1, reflexed)
    a1_unit, _ = _cosine_fourier_coefficients(unit_slope, m)
    cl_unit = np.pi * a1_unit
    if abs(cl_unit) < 1e-12:
        raise GeometryError(
            "the solved mean line produces no lift at its ideal angle, so it "
            "cannot be scaled to a design lift coefficient"
        )
    k1 = float(cl_design / cl_unit)

    return FiveDigitCamber(
        m=float(m),
        k1=k1,
        k2_over_k1=float(k2_over_k1),
        x_f=float(x_f),
        cl_design=float(cl_design),
        reflexed=bool(reflexed),
    )


def camber_line_5digit(
    x: ArrayLike, camber: FiveDigitCamber
) -> tuple[FloatArray, FloatArray]:
    """5-digit camber line and its slope.

    Standard (non-reflexed) mean line, a cubic ahead of ``m`` and a straight
    line aft of it:

    .. math::
        y_c = \\frac{k_1}{6}\\left[x^3 - 3mx^2 + m^2(3-m)x\\right], \\quad x < m

        y_c = \\frac{k_1 m^3}{6}(1 - x), \\quad x \\ge m

    Reflexed mean line, a cubic on both sides with the aft cubic scaled by
    ``k2/k1`` so that the mean line turns back up towards the trailing edge:

    .. math::
        y_c = \\frac{k_1}{6}\\left[(x-m)^3 - \\frac{k_2}{k_1}(1-m)^3 x
              - m^3 x + m^3\\right], \\quad x \\le m

        y_c = \\frac{k_1}{6}\\left[\\frac{k_2}{k_1}(x-m)^3
              - \\frac{k_2}{k_1}(1-m)^3 x - m^3 x + m^3\\right], \\quad x > m

    Parameters
    ----------
    x : array_like
        Chordwise stations ``x/c`` in [0, 1].
    camber : FiveDigitCamber
        Solved mean-line constants, from :func:`solve_five_digit_camber`.

    Returns
    -------
    y_c : ndarray
        Camber-line height in chords, positive up.
    dyc_dx : ndarray
        Camber-line slope, dimensionless.
    """
    xa = np.asarray(x, dtype=np.float64)
    m, k1, r = camber.m, camber.k1, camber.k2_over_k1

    if not camber.reflexed:
        y_c = np.where(
            xa < m,
            (k1 / 6.0) * (xa**3 - 3.0 * m * xa**2 + m**2 * (3.0 - m) * xa),
            (k1 * m**3 / 6.0) * (1.0 - xa),
        )
    else:
        tail = r * (1.0 - m) ** 3 + m**3
        y_c = np.where(
            xa <= m,
            (k1 / 6.0) * ((xa - m) ** 3 - tail * xa + m**3),
            (k1 / 6.0) * (r * (xa - m) ** 3 - tail * xa + m**3),
        )

    dyc_dx = _five_digit_slope(m, k1, r, camber.reflexed)(xa)
    return y_c, dyc_dx


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def _cosine_stations(n_surface: int) -> FloatArray:
    """``n_surface`` cosine-clustered stations from leading to trailing edge."""
    beta = np.linspace(0.0, np.pi, n_surface)
    return 0.5 * (1.0 - np.cos(beta))


def _surface_points(
    x_c: FloatArray, y_c: FloatArray, dyc_dx: FloatArray, y_t: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Lay half-thickness off perpendicular to the mean line, in Selig order.

    This is the classical NACA construction: the thickness form is applied
    normal to the camber line, not vertically, so the upper and lower surface
    points at a given camber station sit at *different* ``x``. For a strongly
    cambered section the first point or two of a surface can end up at slightly
    negative ``x`` — that is correct behaviour, not a bug, and is why
    :class:`~aerolab.geometry.airfoil.Airfoil` does not assume ``x >= 0``.
    """
    theta = np.arctan(dyc_dx)
    sin_t, cos_t = np.sin(theta), np.cos(theta)

    x_upper = x_c - y_t * sin_t
    z_upper = y_c + y_t * cos_t
    x_lower = x_c + y_t * sin_t
    z_lower = y_c - y_t * cos_t

    # Selig order: upper trailing edge, forward to the leading edge, then aft
    # along the lower surface. The leading-edge point is shared.
    x = np.concatenate([x_upper[::-1], x_lower[1:]])
    z = np.concatenate([z_upper[::-1], z_lower[1:]])
    return x, z


def _check_point_count(n_points: int) -> int:
    """Validate the requested point count and return points per surface."""
    if n_points < 21:
        raise GeometryError(
            f"n_points must be at least 21 to resolve a section, got {n_points}"
        )
    if n_points % 2 == 0:
        raise GeometryError(
            f"n_points must be odd so that the leading edge is a single shared "
            f"point, got {n_points}. Try {n_points + 1}."
        )
    return (n_points + 1) // 2


def _parse_digits(designation: str, expected: int) -> tuple[str, str]:
    """Strip an optional 'naca' prefix and validate the digit count."""
    cleaned = designation.strip().lower().replace("-", "").replace(" ", "")
    if cleaned.startswith("naca"):
        cleaned = cleaned[4:]
    if not cleaned.isdigit():
        raise GeometryError(
            f"NACA designation must be digits (optionally prefixed 'naca'), "
            f"got {designation!r}"
        )
    if len(cleaned) != expected:
        raise GeometryError(
            f"expected a {expected}-digit NACA designation, got {cleaned!r} "
            f"({len(cleaned)} digits)"
        )
    return cleaned, designation.strip()


def naca4(
    designation: str,
    n_points: int = 201,
    *,
    closed_te: bool = True,
    name: str | None = None,
) -> Airfoil:
    """Generate a NACA 4-digit section.

    Parameters
    ----------
    designation : str
        Four digits, optionally prefixed ``naca`` (``"0012"``, ``"naca2412"``).
        First digit is maximum camber in percent chord, second is its position
        in tenths of chord, last two are thickness in percent chord.
    n_points : int, optional
        Total number of points in the returned contour. Must be odd so the
        leading edge is a single shared point. Default 201, giving 100 panels
        per surface.
    closed_te : bool, optional
        If True (default) the trailing edge closes exactly. If False the
        original NACA thickness polynomial is used, leaving a finite-thickness
        trailing edge of ``0.0210 * t`` chords.
    name : str, optional
        Label for the airfoil; defaults to the designation as supplied.

    Returns
    -------
    Airfoil
        Contour in Selig order, cosine-clustered in the camber-station
        parameter so points bunch at both the leading and trailing edges.

    Examples
    --------
    >>> af = naca4("0012")
    >>> round(af.max_thickness.value, 4)
    0.12
    """
    digits, original = _parse_digits(designation, 4)
    n_surface = _check_point_count(n_points)

    max_camber = int(digits[0]) / 100.0
    camber_position = int(digits[1]) / 10.0
    thickness = int(digits[2:4]) / 100.0
    if thickness <= 0.0:
        raise GeometryError(
            f"NACA {digits} has zero thickness; a section needs a non-zero "
            "last two digits"
        )

    x_c = _cosine_stations(n_surface)
    y_c, dyc_dx = camber_line_4digit(x_c, max_camber, camber_position)
    y_t = thickness_distribution(x_c, thickness, closed_te=closed_te)
    x, z = _surface_points(x_c, y_c, dyc_dx, y_t)
    return Airfoil.from_points(x, z, name=name or f"NACA {original.upper().removeprefix('NACA').strip()}")


def naca5(
    designation: str,
    n_points: int = 201,
    *,
    closed_te: bool = True,
    name: str | None = None,
) -> Airfoil:
    """Generate a NACA 5-digit section.

    Parameters
    ----------
    designation : str
        Five digits, optionally prefixed ``naca`` (``"23012"``, ``"naca23112"``).
        First digit sets the design lift coefficient (``Cl_i = 0.15 * digit``),
        second sets the position of maximum camber (``x_f = 0.05 * digit``),
        third is 0 for the standard mean line or 1 for the reflexed mean line,
        last two are thickness in percent chord.
    n_points : int, optional
        Total number of points in the returned contour; must be odd. Default 201.
    closed_te : bool, optional
        If True (default) the trailing edge closes exactly.
    name : str, optional
        Label for the airfoil; defaults to the designation as supplied.

    Returns
    -------
    Airfoil
        Contour in Selig order.

    Raises
    ------
    GeometryError
        If the third digit is not 0 or 1, or if no mean line of the requested
        family exists for the given position of maximum camber.

    Notes
    -----
    The mean-line constants are solved from their defining conditions rather
    than tabulated; see :func:`solve_five_digit_camber`.
    """
    digits, original = _parse_digits(designation, 5)
    n_surface = _check_point_count(n_points)

    cl_design = int(digits[0]) * _CL_PER_FIRST_DIGIT
    x_f = int(digits[1]) * _XF_PER_SECOND_DIGIT
    reflex_digit = int(digits[2])
    thickness = int(digits[3:5]) / 100.0

    if reflex_digit not in (0, 1):
        raise GeometryError(
            f"the third digit of a 5-digit designation selects the mean line and "
            f"must be 0 (standard) or 1 (reflexed); got {reflex_digit} in {digits!r}"
        )
    if thickness <= 0.0:
        raise GeometryError(f"NACA {digits} has zero thickness")

    x_c = _cosine_stations(n_surface)
    if cl_design == 0.0:
        y_c = np.zeros_like(x_c)
        dyc_dx = np.zeros_like(x_c)
    else:
        camber = solve_five_digit_camber(x_f, cl_design, reflexed=reflex_digit == 1)
        y_c, dyc_dx = camber_line_5digit(x_c, camber)

    y_t = thickness_distribution(x_c, thickness, closed_te=closed_te)
    x, z = _surface_points(x_c, y_c, dyc_dx, y_t)
    return Airfoil.from_points(x, z, name=name or f"NACA {original.upper().removeprefix('NACA').strip()}")


def naca(
    designation: str,
    n_points: int = 201,
    *,
    closed_te: bool = True,
    name: str | None = None,
) -> Airfoil:
    """Generate a NACA section, dispatching on the number of digits.

    Parameters
    ----------
    designation : str
        A 4- or 5-digit NACA designation, optionally prefixed ``naca``.
    n_points : int, optional
        Total number of points in the returned contour; must be odd.
    closed_te : bool, optional
        If True (default) the trailing edge closes exactly.
    name : str, optional
        Label for the airfoil.

    Returns
    -------
    Airfoil
        Contour in Selig order.

    Raises
    ------
    GeometryError
        If the designation is neither 4 nor 5 digits. The 6-series requires a
        conformal-mapping construction that is not implemented; see NOTES.md,
        L1.2.
    """
    cleaned = designation.strip().lower().replace("-", "").replace(" ", "")
    if cleaned.startswith("naca"):
        cleaned = cleaned[4:]
    if len(cleaned) == 4:
        return naca4(designation, n_points, closed_te=closed_te, name=name)
    if len(cleaned) == 5:
        return naca5(designation, n_points, closed_te=closed_te, name=name)
    raise GeometryError(
        f"only 4- and 5-digit NACA sections are implemented; got {designation!r} "
        f"({len(cleaned)} digits). The 6-series mean lines and thickness forms "
        "are defined by conformal mapping and are not available."
    )
