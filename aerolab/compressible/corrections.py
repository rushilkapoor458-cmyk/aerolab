"""Compressibility corrections to incompressible pressure coefficients.

Both rules here map an incompressible ``Cp`` onto a compressible one at a given
freestream Mach number. Neither solves a compressible flow: they are algebraic
corrections derived from linearised potential theory, and they inherit its
assumptions — thin sections, small perturbations, no shocks.

Prandtl-Glauert
    ``Cp = Cp_0 / beta`` with ``beta = sqrt(1 - M^2)``. Linear in ``Cp_0``, so
    integrated forces scale by the same factor: ``Cl = Cl_0 / beta`` exactly.

Karman-Tsien
    ``Cp = Cp_0 / [beta + (M^2/(1+beta)) (Cp_0/2)]``. Non-linear in ``Cp_0``,
    which means it corrects a strong suction peak more than a weak one — closer
    to reality — and it also means integrated forces are **not** a simple
    scaling of the incompressible ones. This module integrates the corrected
    pressure distribution rather than scaling the incompressible coefficient,
    which is the only route that stays consistent for both rules.

Where they stop working
-----------------------
Both are subcritical approximations. Once the local Mach number reaches 1 a
shock forms, the flow is no longer isentropic, and neither correction has any
claim on the answer. The transition is not sharp, so this module reports the
maximum local Mach number and flags results above 0.7 rather than silently
returning a number. See :class:`CompressibleField`.

Conventions
-----------
``Cp`` is incompressible on input and compressible on output. ``M`` is a Mach
number, never a velocity. ``gamma`` is the ratio of specific heats, 1.4 for air.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import brentq

from aerolab.exceptions import ValidityRangeError

FloatArray = NDArray[np.float64]

CorrectionMethod = Literal["prandtl-glauert", "karman-tsien", "none"]

__all__ = [
    "GAMMA_AIR",
    "TRUSTWORTHY_LOCAL_MACH",
    "CompressibleField",
    "prandtl_glauert",
    "karman_tsien",
    "local_mach_number",
    "apply_correction",
    "critical_mach_number",
]

#: Ratio of specific heats for air.
GAMMA_AIR = 1.4

#: Local Mach number above which both corrections stop being trustworthy.
#:
#: Not a cliff. Below it the linearised rules are within a few percent of
#: measured pressures; by 0.8 they are visibly wrong; at 1.0 a shock forms and
#: the isentropic assumption underneath them fails outright. Results above this
#: are returned with a flag rather than suppressed, because the user may
#: legitimately want to see how close to critical a section is.
TRUSTWORTHY_LOCAL_MACH = 0.7

#: Freestream Mach number above which the corrections are refused outright.
MAX_FREESTREAM_MACH = 0.95


def _check_mach(mach: float) -> None:
    if mach < 0.0:
        raise ValidityRangeError(f"Mach number must be non-negative, got {mach}")
    if mach > MAX_FREESTREAM_MACH:
        raise ValidityRangeError(
            f"freestream Mach number {mach} exceeds {MAX_FREESTREAM_MACH}. "
            "Prandtl-Glauert and Karman-Tsien are subcritical corrections; near "
            "Mach 1 the 1/sqrt(1 - M^2) factor diverges and neither has any "
            "claim on the answer."
        )


def prandtl_glauert(cp_incompressible: ArrayLike, mach: float) -> FloatArray:
    """Prandtl-Glauert correction.

    Parameters
    ----------
    cp_incompressible : array_like
        Incompressible pressure coefficient.
    mach : float
        Freestream Mach number, below 0.95.

    Returns
    -------
    ndarray
        Corrected pressure coefficient, ``Cp_0 / sqrt(1 - M**2)``.

    Notes
    -----
    Being linear in ``Cp_0``, this scales every pressure by the same factor —
    including the stagnation pressure at the nose, where ``Cp_0 = 1`` and the
    true compressible value is above 1 but not by ``1/beta``. That is the
    correction's best-known weakness and the reason Karman-Tsien exists.
    """
    _check_mach(mach)
    cp = np.asarray(cp_incompressible, dtype=np.float64)
    return cp / np.sqrt(1.0 - mach**2)


def karman_tsien(cp_incompressible: ArrayLike, mach: float) -> FloatArray:
    """Karman-Tsien correction.

    Parameters
    ----------
    cp_incompressible : array_like
        Incompressible pressure coefficient.
    mach : float
        Freestream Mach number, below 0.95.

    Returns
    -------
    ndarray
        Corrected pressure coefficient.

    Raises
    ------
    ValidityRangeError
        If the denominator vanishes, which happens for strongly positive
        ``Cp_0`` at high Mach and means the correction has left its range.

    Notes
    -----
    .. math::
        C_p = \\frac{C_{p_0}}
             {\\beta + \\dfrac{M^2}{1 + \\beta}\\dfrac{C_{p_0}}{2}},
        \\qquad \\beta = \\sqrt{1 - M^2}

    Being non-linear, it amplifies a strong suction peak more than a weak one,
    which is the physically right behaviour and why it tracks measured
    pressures better than Prandtl-Glauert up to about the critical Mach number.
    """
    _check_mach(mach)
    cp = np.asarray(cp_incompressible, dtype=np.float64)
    beta = np.sqrt(1.0 - mach**2)
    denominator = beta + (mach**2 / (1.0 + beta)) * (cp / 2.0)
    if np.any(denominator <= 1e-6):
        worst = float(np.min(denominator))
        raise ValidityRangeError(
            f"the Karman-Tsien denominator reaches {worst:.4f} at Mach {mach} for "
            "the supplied pressure distribution. It must stay positive: once it "
            "passes through zero the correction changes the sign of Cp, turning a "
            "suction peak into a pressure peak. This happens far beyond the "
            "correction's range and the result would be meaningless."
        )
    return cp / denominator


def local_mach_number(
    cp: ArrayLike, mach: float, gamma: float = GAMMA_AIR
) -> FloatArray:
    """Local Mach number implied by a compressible pressure coefficient.

    Parameters
    ----------
    cp : array_like
        **Compressible** pressure coefficient, i.e. already corrected.
    mach : float
        Freestream Mach number.
    gamma : float, optional
        Ratio of specific heats.

    Returns
    -------
    ndarray
        Local Mach number. Zero where the isentropic relation would give a
        negative squared Mach number, which happens only at pressures above
        stagnation and indicates the correction has broken down.

    Notes
    -----
    From the definition of ``Cp`` and the isentropic relation, in closed form:

    .. math::
        \\frac{p}{p_\\infty} = 1 + \\frac{\\gamma M_\\infty^2}{2} C_p

        M^2 = \\frac{2}{\\gamma - 1}\\left[
              \\frac{1 + \\frac{\\gamma-1}{2}M_\\infty^2}
                   {(p/p_\\infty)^{(\\gamma-1)/\\gamma}} - 1\\right]

    No iteration is needed. At ``M_inf = 0`` the local Mach number is zero
    everywhere by definition, and that limit is returned directly rather than
    evaluated, since the expression is 0/0 there.
    """
    cp_array = np.asarray(cp, dtype=np.float64)
    if mach <= 0.0:
        return np.zeros_like(cp_array)

    pressure_ratio = 1.0 + 0.5 * gamma * mach**2 * cp_array
    if np.any(pressure_ratio <= 0.0):
        raise ValidityRangeError(
            f"the corrected pressure coefficient implies a negative absolute "
            f"pressure at Mach {mach}; the correction has broken down"
        )
    stagnation = 1.0 + 0.5 * (gamma - 1.0) * mach**2
    squared = (2.0 / (gamma - 1.0)) * (
        stagnation / pressure_ratio ** ((gamma - 1.0) / gamma) - 1.0
    )
    return np.sqrt(np.maximum(squared, 0.0))


@dataclass(frozen=True)
class CompressibleField:
    """A corrected pressure distribution and what can be said about it.

    Attributes
    ----------
    cp : ndarray
        Corrected pressure coefficient.
    cp_incompressible : ndarray
        The input, retained so the size of the correction can be seen.
    mach : float
        Freestream Mach number.
    method : str
        Correction applied.
    """

    cp: FloatArray
    cp_incompressible: FloatArray
    mach: float
    method: CorrectionMethod

    @cached_property
    def local_mach(self) -> FloatArray:
        """Local Mach number at each station."""
        return local_mach_number(self.cp, self.mach)

    @cached_property
    def max_local_mach(self) -> float:
        """Highest local Mach number anywhere on the surface."""
        return float(np.max(self.local_mach))

    @property
    def is_trustworthy(self) -> bool:
        """Whether the peak local Mach number is below the trustworthy limit."""
        return self.max_local_mach <= TRUSTWORTHY_LOCAL_MACH

    @property
    def is_supercritical(self) -> bool:
        """Whether the flow has gone sonic somewhere, so a shock is expected."""
        return self.max_local_mach >= 1.0

    @property
    def warning(self) -> str | None:
        """A sentence describing the problem, or None if there is none."""
        if self.is_supercritical:
            return (
                f"local Mach reaches {self.max_local_mach:.3f} at freestream Mach "
                f"{self.mach:.3f}: the flow is supercritical, a shock is expected, "
                f"and the {self.method} correction assumes isentropic flow. This "
                "result is not a prediction."
            )
        if not self.is_trustworthy:
            return (
                f"local Mach reaches {self.max_local_mach:.3f} at freestream Mach "
                f"{self.mach:.3f}, above the {TRUSTWORTHY_LOCAL_MACH} at which "
                f"the {self.method} correction stops being trustworthy. Treat the "
                "pressures as indicative."
            )
        return None

    def check(self) -> "CompressibleField":
        """Raise if the correction is outside its trustworthy range.

        Raises
        ------
        ValidityRangeError
            Carrying the peak local Mach number and what it implies.
        """
        if self.warning is not None:
            raise ValidityRangeError(self.warning)
        return self

    def __repr__(self) -> str:
        state = "trustworthy" if self.is_trustworthy else "OUTSIDE RANGE"
        return (
            f"<CompressibleField {self.method}, M={self.mach:.3f}, "
            f"max local M={self.max_local_mach:.3f}, {state}>"
        )


def apply_correction(
    cp_incompressible: ArrayLike,
    mach: float,
    method: CorrectionMethod = "karman-tsien",
) -> CompressibleField:
    """Apply a compressibility correction and report its validity.

    Parameters
    ----------
    cp_incompressible : array_like
        Incompressible pressure coefficient.
    mach : float
        Freestream Mach number. Zero returns the input unchanged.
    method : {"karman-tsien", "prandtl-glauert", "none"}, optional
        Correction to apply. Karman-Tsien by default, being the better of the
        two below the critical Mach number.

    Returns
    -------
    CompressibleField
        Never raises for being outside the trustworthy range — it flags it. Call
        :meth:`CompressibleField.check` to turn that into an exception.
    """
    cp = np.asarray(cp_incompressible, dtype=np.float64)
    if method == "none" or mach == 0.0:
        corrected = cp.copy()
    elif method == "prandtl-glauert":
        corrected = prandtl_glauert(cp, mach)
    elif method == "karman-tsien":
        corrected = karman_tsien(cp, mach)
    else:
        raise ValidityRangeError(
            f"correction must be 'karman-tsien', 'prandtl-glauert' or 'none', "
            f"got {method!r}"
        )
    return CompressibleField(
        cp=corrected, cp_incompressible=cp, mach=float(mach), method=method
    )


def critical_mach_number(
    cp_min_incompressible: float,
    method: CorrectionMethod = "karman-tsien",
    gamma: float = GAMMA_AIR,
) -> float:
    """Freestream Mach number at which the flow first goes sonic.

    Parameters
    ----------
    cp_min_incompressible : float
        Most negative incompressible pressure coefficient on the section.
    method : {"karman-tsien", "prandtl-glauert"}, optional
        Correction used to march the peak suction up with Mach number.
    gamma : float, optional
        Ratio of specific heats.

    Returns
    -------
    float
        Critical Mach number.

    Raises
    ------
    ValidityRangeError
        If the section does not go critical below Mach 0.95, or if the supplied
        pressure coefficient is not a suction.

    Notes
    -----
    Found by root-finding on ``max(local Mach) = 1``: the peak suction is
    corrected at a trial freestream Mach number and the implied local Mach
    number computed, which is exactly the graphical construction of intersecting
    the correction curve with the sonic line.

    The result is the Mach number at which a shock **first appears**, not the
    one at which drag rises. Drag divergence follows at 0.05 to 0.1 higher,
    depending on section — this package does not predict it.
    """
    if cp_min_incompressible >= 0.0:
        raise ValidityRangeError(
            f"the minimum pressure coefficient must be a suction (negative), "
            f"got {cp_min_incompressible}"
        )

    def sonic_gap(mach: float) -> float:
        """Local Mach minus one, or NaN where the correction has broken down."""
        try:
            field = apply_correction(
                np.array([cp_min_incompressible]), mach, method=method
            )
            return float(local_mach_number(field.cp, mach, gamma)[0]) - 1.0
        except ValidityRangeError:
            return float("nan")

    # Scan upward for the *first* sign change rather than bracketing the whole
    # range. Karman-Tsien's denominator passes through zero at high Mach for a
    # strong suction, so the far end of the range is not merely inaccurate but
    # sign-flipped — bracketing across it would step over the physical root and
    # land on the breakdown.
    trial = np.linspace(1e-4, MAX_FREESTREAM_MACH, 400)
    gaps = np.array([sonic_gap(m) for m in trial])
    usable = np.isfinite(gaps)
    crossings = np.nonzero(
        usable[:-1] & usable[1:] & (np.sign(gaps[:-1]) * np.sign(gaps[1:]) < 0)
    )[0]
    if crossings.size == 0:
        raise ValidityRangeError(
            f"a section with minimum Cp of {cp_min_incompressible:.4f} does not "
            f"reach sonic conditions below Mach {MAX_FREESTREAM_MACH}, where "
            "these corrections are already refused"
        )
    index = int(crossings[0])
    return float(brentq(sonic_gap, trial[index], trial[index + 1], xtol=1e-10))
