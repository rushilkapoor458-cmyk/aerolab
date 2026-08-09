"""Empirical closure relations for the integral boundary-layer methods.

Every relation here is a curve fit to experiment or to exact solutions, valid
over a stated range and meaningless outside it. Each function therefore carries
its range in the docstring and refuses inputs outside it rather than
extrapolating — a shape factor of 5 fed to a correlation fitted over 1.1 to 2.8
will return a number, and that number will be wrong.

Non-dimensionalisation
----------------------
``lambda_`` (Thwaites' pressure-gradient parameter) and the shape factors ``H``
and ``H1`` are dimensionless. ``Re_theta`` is based on momentum thickness. Skin
friction ``cf = tau_w / (0.5 * rho * Ue**2)`` uses the **local edge** dynamic
pressure, not the freestream — this is the usual convention for integral methods
and it matters when the edge velocity is far from freestream.

References
----------
Thwaites, B., "Approximate calculation of the laminar boundary layer",
Aeronautical Quarterly 1, 1949.
Cebeci, T. and Bradshaw, P., *Momentum Transfer in Boundary Layers*, 1977.
Head, M. R., "Entrainment in the turbulent boundary layer", ARC R&M 3152, 1958.
Ludwieg, H. and Tillmann, W., "Investigations of the wall shearing stress in
turbulent boundary layers", NACA TM 1285, 1950.
White, F. M., *Viscous Fluid Flow*, 3rd ed., 2006.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from aerolab.exceptions import ValidityRangeError

FloatArray = NDArray[np.float64]

__all__ = [
    "LAMBDA_SEPARATION",
    "LAMBDA_MIN",
    "LAMBDA_MAX",
    "TURBULENT_SEPARATION_H",
    "thwaites_shape_factor",
    "thwaites_shear",
    "head_h1_from_h",
    "head_h_from_h1",
    "head_entrainment",
    "ludwieg_tillmann_cf",
]

#: Thwaites' parameter at laminar separation.
#:
#: The correlation's own zero-shear point is at lambda = -0.0898, but -0.0842 is
#: the value normally quoted, and it is the better predictor. On Howarth's
#: linearly retarded flow ``Ue = U0(1 - x/L)``, whose exact separation is at
#: x/L = 0.1198, the two give:
#:
#:     lambda = -0.0898  ->  x/L = 0.1230   (+2.7%)
#:     lambda = -0.0842  ->  x/L = 0.1179   (-1.6%)
#:
#: so the slightly conservative threshold is also the more accurate one. Both
#: figures are asserted in ``tests/test_viscous_closure.py``.
LAMBDA_SEPARATION = -0.0842

#: Range over which the Thwaites correlations were fitted.
LAMBDA_MIN = -0.10
LAMBDA_MAX = 0.10

#: Shape factor taken to indicate turbulent separation.
#:
#: Head's method has no sharp separation point. Values between 2.4 and 2.8 are
#: used in the literature; 2.6 is the middle of that range. Because the
#: criterion is a convention rather than a result, the threshold is a parameter
#: of the solver and this is only its default.
TURBULENT_SEPARATION_H = 2.6


def _as_array(values: ArrayLike) -> FloatArray:
    return np.asarray(values, dtype=np.float64)


def _check_range(
    values: FloatArray, low: float, high: float, name: str, context: str
) -> None:
    if np.any(values < low) or np.any(values > high):
        raise ValidityRangeError(
            f"{name} = [{float(np.min(values)):.5f}, {float(np.max(values)):.5f}] "
            f"is outside the range [{low}, {high}] over which {context}. "
            "Extrapolating an empirical correlation returns a plausible number "
            "that is not a prediction."
        )


def thwaites_shape_factor(lambda_: ArrayLike) -> FloatArray:
    """Shape factor ``H = delta*/theta`` from Thwaites' parameter.

    Parameters
    ----------
    lambda_ : array_like
        Thwaites' parameter ``lambda = (theta**2 / nu) * dUe/ds``, in
        ``[-0.10, 0.10]``. Positive is a favourable (accelerating) gradient.

    Returns
    -------
    ndarray
        Shape factor, dimensionless.

    Raises
    ------
    ValidityRangeError
        If any value lies outside the fitted range.

    Notes
    -----
    Uses the two-branch fit of Cebeci and Bradshaw:

    .. math::
        H = 2.61 - 3.75\\lambda + 5.24\\lambda^2, \\qquad 0 \\le \\lambda \\le 0.1

        H = 2.088 + \\frac{0.0731}{\\lambda + 0.14},
            \\qquad -0.1 \\le \\lambda < 0

    At ``lambda = 0`` both branches give 2.61, against the exact Blasius value of
    2.59 — a 0.8% error that is inherent to the method. The two branches differ
    from each other there by 1.4e-4, a discontinuity in the published fit itself
    rather than in this implementation; it is far below the fit's own accuracy
    and has no practical effect.
    """
    lam = _as_array(lambda_)
    _check_range(lam, LAMBDA_MIN, LAMBDA_MAX, "lambda", "Thwaites' correlation is fitted")
    return np.where(
        lam >= 0.0,
        2.61 - 3.75 * lam + 5.24 * lam**2,
        2.088 + 0.0731 / (lam + 0.14),
    )


def thwaites_shear(lambda_: ArrayLike) -> FloatArray:
    """Shear correlation ``l = (theta / (mu * Ue)) * tau_w`` from Thwaites' parameter.

    Parameters
    ----------
    lambda_ : array_like
        Thwaites' parameter, in ``[-0.10, 0.10]``.

    Returns
    -------
    ndarray
        Dimensionless shear function. Skin friction follows as
        ``cf = 2 * l / Re_theta``.

    Notes
    -----
    .. math::
        l = 0.22 + 1.57\\lambda - 1.8\\lambda^2, \\qquad 0 \\le \\lambda \\le 0.1

        l = 0.22 + 1.402\\lambda + \\frac{0.018\\lambda}{\\lambda + 0.107},
            \\qquad -0.1 \\le \\lambda < 0

    At ``lambda = 0`` this gives ``l = 0.22``, so ``cf = 0.44 / Re_theta``. The
    exact Blasius result is ``0.4409 / Re_theta`` — agreement to 0.2%, which is
    much better than the 1% error in ``theta`` itself.
    """
    lam = _as_array(lambda_)
    _check_range(lam, LAMBDA_MIN, LAMBDA_MAX, "lambda", "Thwaites' correlation is fitted")
    return np.where(
        lam >= 0.0,
        0.22 + 1.57 * lam - 1.8 * lam**2,
        0.22 + 1.402 * lam + 0.018 * lam / (lam + 0.107),
    )


def head_h1_from_h(h: ArrayLike) -> FloatArray:
    """Entrainment shape factor ``H1 = (delta - delta*)/theta`` from ``H``.

    Parameters
    ----------
    h : array_like
        Shape factor, in ``[1.1, 3.0]``. The lower bound is where the
        correlation's first branch becomes singular.

    Returns
    -------
    ndarray
        Entrainment shape factor.

    Notes
    -----
    .. math::
        H_1 = 3.3 + 0.8234 (H - 1.1)^{-1.287}, \\qquad H \\le 1.6

        H_1 = 3.3 + 1.5501 (H - 0.6778)^{-3.064}, \\qquad H > 1.6

    ``H1`` decreases as ``H`` rises, and tends to 3.3 as ``H`` grows without
    bound — which is why the turbulent solver treats ``H1`` approaching 3.3 as
    separation.
    """
    hh = _as_array(h)
    _check_range(hh, 1.1 + 1e-9, 3.0, "H", "Head's entrainment correlation is fitted")
    return np.where(
        hh <= 1.6,
        3.3 + 0.8234 * (hh - 1.1) ** -1.287,
        3.3 + 1.5501 * (hh - 0.6778) ** -3.064,
    )


def head_h_from_h1(h1: ArrayLike) -> FloatArray:
    """Shape factor ``H`` from the entrainment shape factor ``H1``.

    Parameters
    ----------
    h1 : array_like
        Entrainment shape factor, greater than 3.3.

    Returns
    -------
    ndarray
        Shape factor.

    Raises
    ------
    ValidityRangeError
        If any value is at or below 3.3, where ``H`` is unbounded.

    Notes
    -----
    .. math::
        H = 1.1 + 0.86 (H_1 - 3.3)^{-0.777}, \\qquad H_1 \\ge 5.3

        H = 0.6778 + 1.1538 (H_1 - 3.3)^{-0.326}, \\qquad H_1 < 5.3

    **The branches pair with those of** :func:`head_h1_from_h` **by their
    offsets, not by their order.** The forward branch for ``H <= 1.6`` contains
    ``(H - 1.1)`` and maps onto ``H1 >= 5.3``, so the inverse there is the
    ``1.1 +`` form; the forward branch for ``H > 1.6`` contains
    ``(H - 0.6778)`` and maps onto ``H1 < 5.3``, so the inverse there is the
    ``0.6778 +`` form.

    Writing them the other way round is an easy mistake and a quiet one. It
    costs only 1.4% at ``H = 1.4``, where a turbulent run begins, but reaches
    54% by ``H = 2.6`` — so the error grows through the adverse pressure
    gradient towards the trailing edge and shows up as premature separation
    rather than as an obviously wrong number. The round-trip test in
    ``tests/test_viscous_closure.py`` exists to catch exactly this.

    The two branches agree to 0.2% at the switch point ``H1 = 5.3``, where both
    give ``H`` close to 1.60 — the same value at which :func:`head_h1_from_h`
    changes branch.
    """
    hh1 = _as_array(h1)
    if np.any(hh1 <= 3.3):
        raise ValidityRangeError(
            f"H1 = {float(np.min(hh1)):.5f} is at or below 3.3, where the shape "
            "factor is unbounded. The turbulent boundary layer has separated."
        )
    return np.where(
        hh1 >= 5.3,
        1.1 + 0.86 * (hh1 - 3.3) ** -0.777,
        0.6778 + 1.1538 * (hh1 - 3.3) ** -0.326,
    )


def head_entrainment(h1: ArrayLike) -> FloatArray:
    """Head's entrainment function ``F(H1) = d(theta*H1)/ds``.

    Parameters
    ----------
    h1 : array_like
        Entrainment shape factor, greater than 3.0.

    Returns
    -------
    ndarray
        Entrainment rate, dimensionless.

    Notes
    -----
    ``F = 0.0306 (H1 - 3.0)**-0.6169``. Note the constant 3.0 here against the
    3.3 in :func:`head_h_from_h1`: the two are independent fits from Head's
    paper and the offsets genuinely differ. Since ``H1`` cannot fall below 3.3
    while ``H`` remains finite, ``F`` stays bounded, reaching 0.0643 at
    ``H1 = 3.3``.
    """
    hh1 = _as_array(h1)
    if np.any(hh1 <= 3.0):
        raise ValidityRangeError(
            f"H1 = {float(np.min(hh1)):.5f} is at or below 3.0, where Head's "
            "entrainment function is singular."
        )
    return 0.0306 * (hh1 - 3.0) ** -0.6169


def ludwieg_tillmann_cf(h: ArrayLike, re_theta: ArrayLike) -> FloatArray:
    """Turbulent skin friction from the Ludwieg-Tillmann correlation.

    Parameters
    ----------
    h : array_like
        Shape factor, in ``[1.0, 3.0]``.
    re_theta : array_like
        Reynolds number based on momentum thickness and **edge** velocity, at
        least 100.

    Returns
    -------
    ndarray
        ``cf = tau_w / (0.5 * rho * Ue**2)``, using the local edge dynamic
        pressure.

    Notes
    -----
    ``cf = 0.246 * 10**(-0.678 H) * Re_theta**-0.268``.

    The correlation was fitted to equilibrium and mildly non-equilibrium
    boundary layers and is not reliable close to separation, where it
    nonetheless returns a small positive number rather than zero. It therefore
    cannot itself be used to detect separation; that is what the shape-factor
    criterion is for.
    """
    hh = _as_array(h)
    rt = _as_array(re_theta)
    _check_range(hh, 1.0, 3.0, "H", "the Ludwieg-Tillmann correlation is fitted")
    if np.any(rt < 100.0):
        raise ValidityRangeError(
            f"Re_theta = {float(np.min(rt)):.1f} is below 100; the "
            "Ludwieg-Tillmann correlation describes turbulent layers and has no "
            "meaning at this Reynolds number."
        )
    return 0.246 * 10.0 ** (-0.678 * hh) * rt**-0.268
