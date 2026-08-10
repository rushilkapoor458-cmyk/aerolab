"""Wind-tunnel wall corrections for a two-dimensional model.

A model in a tunnel is not in free air. The walls constrain the streamlines,
which speeds the flow up around the model (blockage) and curves it (streamline
curvature), so the section behaves as though it were at a different angle in a
faster stream. These corrections undo that, turning what the balance measured
into what free air would have given.

Four effects, following Allen and Vincenti as presented in Barlow, Rae and Pope:

Solid blockage
    The model's own volume narrows the working section.
Wake blockage
    The wake is slower than the freestream, so by continuity the flow outside it
    is faster.
Streamline curvature
    The walls stop the flow curving as much as it would in free air, which makes
    the section behave as if it had less camber — so the measured lift and
    nose-down moment are both too small.
Horizontal buoyancy
    A real tunnel has a slight streamwise static-pressure gradient, usually from
    boundary-layer growth on the walls. A body sitting in a pressure gradient
    feels a force, exactly as it would in a fluid under gravity.

Sign convention
---------------
Everything here takes **uncorrected** (measured) quantities and returns
**corrected** (free-air) ones. Blockage always makes the true dynamic pressure
higher than the reference one, so corrected coefficients are always *smaller*
than measured. Getting this backwards is silent, so the direction is asserted in
the tests rather than only stated here.

Conventions
-----------
Angles in **radians**. ``chord`` and ``height`` in the same length unit; only
their ratio matters. ``Cm`` is about the quarter chord, positive nose-up.

References
----------
Barlow, J. B., Rae, W. H. and Pope, A., *Low-Speed Wind Tunnel Testing*,
3rd ed., Wiley, 1999, chapter 10.
Allen, H. J. and Vincenti, W. G., "Wall interference in a two-dimensional-flow
wind tunnel, with consideration of the effect of compressibility",
NACA Report 782, 1944.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
from numpy.typing import ArrayLike, NDArray

from aerolab.exceptions import ValidityRangeError

FloatArray = NDArray[np.float64]

__all__ = [
    "TunnelSection",
    "WallCorrection",
    "sigma",
    "solid_blockage_factor",
    "correct_two_dimensional",
    "uncorrect_two_dimensional",
]

#: Chord-to-height ratio above which the corrections are refused.
#:
#: The theory is a small-perturbation expansion in ``c/h``. Beyond about 0.4 the
#: corrections exceed 10% and the linearisation they rest on is no longer
#: defensible; a model that large needs a different tunnel, not a bigger
#: correction.
MAX_CHORD_TO_HEIGHT = 0.4


def sigma(chord: float, height: float) -> float:
    """The tunnel geometry parameter ``sigma = (pi^2/48)(c/h)^2``.

    Parameters
    ----------
    chord : float
        Model chord.
    height : float
        Test-section height, in the same units.

    Returns
    -------
    float
        Dimensionless. Every wall correction here scales with it, so it is the
        single number that says how intrusive a given model is.
    """
    if height <= 0.0:
        raise ValidityRangeError(f"tunnel height must be positive, got {height}")
    if chord <= 0.0:
        raise ValidityRangeError(f"chord must be positive, got {chord}")
    ratio = chord / height
    if ratio > MAX_CHORD_TO_HEIGHT:
        raise ValidityRangeError(
            f"chord-to-height ratio {ratio:.3f} exceeds {MAX_CHORD_TO_HEIGHT}. "
            "These corrections are a small-perturbation expansion in c/h; past "
            "this the corrections themselves exceed 10% and the linearisation "
            "is no longer defensible. Use a smaller model."
        )
    return float(np.pi**2 / 48.0 * ratio**2)


def solid_blockage_factor(thickness_ratio: float) -> float:
    """Body shape factor ``Lambda`` for solid blockage.

    Parameters
    ----------
    thickness_ratio : float
        Maximum thickness over chord.

    Returns
    -------
    float
        The factor multiplying :func:`sigma` to give solid blockage.

    Notes
    -----
    Solid blockage scales with the model's cross-sectional area, so ``Lambda``
    is proportional to thickness ratio for a family of similar sections. The
    constant here reproduces the commonly quoted ``Lambda = 0.40`` at
    ``t/c = 0.12``.

    **This is the one coefficient in this module taken from a remembered value
    rather than derived or verified against the primary source.** Barlow, Rae
    and Pope tabulate ``Lambda`` per section family, and those tabulated values
    should be used in preference whenever the book is to hand — pass them
    directly as ``shape_factor``. The structure of the correction, and every
    other coefficient here, does not depend on this choice. See NOTES.md, L7.1.
    """
    if not 0.0 < thickness_ratio < 0.5:
        raise ValidityRangeError(
            f"thickness ratio must lie in (0, 0.5), got {thickness_ratio}"
        )
    return float(10.0 / 3.0 * thickness_ratio)


@dataclass(frozen=True)
class TunnelSection:
    """The test section and the model in it.

    Attributes
    ----------
    height : float
        Test-section height, the dimension the walls constrain.
    chord : float
        Model chord, in the same units.
    thickness_ratio : float
        Model maximum thickness over chord.
    area_ratio : float
        Model cross-sectional area over chord squared, used for buoyancy. For a
        NACA 4-digit section this is about ``0.685 * t/c``.
    pressure_gradient : float
        Empty-tunnel streamwise static-pressure gradient, as ``dCp/dx`` per unit
        chord. Zero for an ideal tunnel; a real open-circuit tunnel typically
        shows a small negative value from wall boundary-layer growth.
    shape_factor : float or None
        Solid-blockage ``Lambda``. Computed from the thickness ratio if omitted.
    """

    height: float
    chord: float
    thickness_ratio: float
    area_ratio: float = 0.0
    pressure_gradient: float = 0.0
    shape_factor: float | None = None

    @cached_property
    def sigma(self) -> float:
        """The geometry parameter for this installation."""
        return sigma(self.chord, self.height)

    @cached_property
    def solid_blockage(self) -> float:
        """Solid blockage ``epsilon_sb``, independent of angle of attack."""
        factor = (
            self.shape_factor
            if self.shape_factor is not None
            else solid_blockage_factor(self.thickness_ratio)
        )
        return float(factor * self.sigma)

    def wake_blockage(self, cd_uncorrected: ArrayLike) -> FloatArray:
        """Wake blockage ``epsilon_wb = (c / 2h) Cd``.

        Parameters
        ----------
        cd_uncorrected : array_like
            Measured drag coefficient.

        Returns
        -------
        ndarray
            Dimensionless. Unlike solid blockage this grows with drag, so it
            dominates near stall and is negligible at the drag bucket.
        """
        return (self.chord / (2.0 * self.height)) * np.asarray(
            cd_uncorrected, dtype=np.float64
        )

    def __repr__(self) -> str:
        return (
            f"<TunnelSection c/h={self.chord / self.height:.3f}, "
            f"sigma={self.sigma:.5f}, solid blockage={self.solid_blockage:.5f}>"
        )


@dataclass(frozen=True)
class WallCorrection:
    """Corrected coefficients and the size of each correction applied.

    Attributes
    ----------
    alpha, cl, cd, cm : ndarray
        Free-air values. ``alpha`` in **radians**.
    solid_blockage, wake_blockage : ndarray
        The two blockage terms, for reporting how intrusive the model was.
    buoyancy_drag : ndarray
        Drag removed as horizontal buoyancy.
    alpha_shift : ndarray
        Angle-of-attack correction applied, in radians.
    """

    alpha: FloatArray
    cl: FloatArray
    cd: FloatArray
    cm: FloatArray
    solid_blockage: FloatArray
    wake_blockage: FloatArray
    buoyancy_drag: FloatArray
    alpha_shift: FloatArray

    @property
    def total_blockage(self) -> FloatArray:
        """``epsilon = epsilon_sb + epsilon_wb``."""
        return self.solid_blockage + self.wake_blockage

    @property
    def dynamic_pressure_ratio(self) -> FloatArray:
        """True dynamic pressure over reference, ``(1 + epsilon)**2``."""
        return (1.0 + self.total_blockage) ** 2

    def summary(self) -> str:
        """One line naming the largest correction, for a run log."""
        return (
            f"blockage {100 * float(np.max(self.total_blockage)):.2f}% max, "
            f"alpha shifted up to "
            f"{np.rad2deg(float(np.max(np.abs(self.alpha_shift)))):.3f} deg, "
            f"Cl reduced by up to "
            f"{100 * float(np.max(np.abs(1 - self.cl / np.where(self.cl == 0, 1, self.cl)))):.2f}%"
        )


def correct_two_dimensional(
    section: TunnelSection,
    alpha: ArrayLike,
    cl: ArrayLike,
    cd: ArrayLike,
    cm: ArrayLike,
) -> WallCorrection:
    """Correct measured two-dimensional data to free-air conditions.

    Parameters
    ----------
    section : TunnelSection
        Test section and model.
    alpha : array_like
        Measured (geometric) angle of attack, in **radians**.
    cl, cd, cm : array_like
        Measured coefficients, on the reference dynamic pressure. ``cm`` about
        the quarter chord, positive nose-up.

    Returns
    -------
    WallCorrection

    Notes
    -----
    Allen and Vincenti's relations, with ``epsilon = epsilon_sb + epsilon_wb``:

    .. math::
        \\alpha = \\alpha_u + \\frac{\\sigma}{2\\pi}(C_{l_u} + 4C_{m_u})

        C_l = C_{l_u}(1 - \\sigma - 2\\varepsilon)

        C_m = C_{m_u}(1 - 2\\varepsilon) + \\tfrac{1}{4}\\sigma C_{l_u}

        C_d = C_{d_u}(1 - 3\\varepsilon_{sb} - 2\\varepsilon_{wb}) - C_{d_B}

    Every correction reduces the coefficient, because blockage means the model
    saw a higher dynamic pressure than the reference probe recorded. The angle
    correction goes the other way: the walls suppress streamline curvature, so
    the model behaved as though at a *higher* angle than the balance recorded,
    and the corrected angle is larger.

    Horizontal buoyancy is subtracted from drag rather than scaled, because it
    is a force the model would not feel in free air at all, not a
    mis-referenced one.
    """
    alpha = np.atleast_1d(np.asarray(alpha, dtype=np.float64))
    cl = np.atleast_1d(np.asarray(cl, dtype=np.float64))
    cd = np.atleast_1d(np.asarray(cd, dtype=np.float64))
    cm = np.atleast_1d(np.asarray(cm, dtype=np.float64))
    if not (alpha.shape == cl.shape == cd.shape == cm.shape):
        raise ValidityRangeError(
            f"alpha, cl, cd and cm must have the same shape; got "
            f"{alpha.shape}, {cl.shape}, {cd.shape}, {cm.shape}"
        )

    s = section.sigma
    solid = np.full_like(alpha, section.solid_blockage)
    wake = section.wake_blockage(cd)
    total = solid + wake

    alpha_shift = (s / (2.0 * np.pi)) * (cl + 4.0 * cm)
    buoyancy = -section.area_ratio * section.pressure_gradient

    return WallCorrection(
        alpha=alpha + alpha_shift,
        cl=cl * (1.0 - s - 2.0 * total),
        cd=cd * (1.0 - 3.0 * solid - 2.0 * wake) - buoyancy,
        cm=cm * (1.0 - 2.0 * total) + 0.25 * s * cl,
        solid_blockage=solid,
        wake_blockage=wake,
        buoyancy_drag=np.full_like(alpha, buoyancy),
        alpha_shift=alpha_shift,
    )


def uncorrect_two_dimensional(
    section: TunnelSection,
    alpha: ArrayLike,
    cl: ArrayLike,
    cd: ArrayLike,
    cm: ArrayLike,
    *,
    iterations: int = 12,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Synthesise what a tunnel would measure, given free-air data.

    Parameters
    ----------
    section : TunnelSection
        Test section and model.
    alpha, cl, cd, cm : array_like
        Free-air values, ``alpha`` in **radians**.
    iterations : int, optional
        Fixed-point iterations. The corrections are a percent or so, so this
        converges in a handful; the default is generous.

    Returns
    -------
    tuple of ndarray
        ``(alpha, cl, cd, cm)`` as the tunnel would report them.

    Notes
    -----
    This exists to test the forward correction. Applying it and then correcting
    must return the original data, which checks the whole chain for
    self-consistency and for algebraic slips that a one-way calculation would
    hide. It is a genuine inverse rather than a re-derivation: the forward
    relations are simply iterated to a fixed point.
    """
    alpha = np.atleast_1d(np.asarray(alpha, dtype=np.float64))
    cl = np.atleast_1d(np.asarray(cl, dtype=np.float64))
    cd = np.atleast_1d(np.asarray(cd, dtype=np.float64))
    cm = np.atleast_1d(np.asarray(cm, dtype=np.float64))

    guess_alpha, guess_cl, guess_cd, guess_cm = alpha.copy(), cl.copy(), cd.copy(), cm.copy()
    for _ in range(iterations):
        forward = correct_two_dimensional(
            section, guess_alpha, guess_cl, guess_cd, guess_cm
        )
        guess_alpha = guess_alpha + (alpha - forward.alpha)
        guess_cl = guess_cl + (cl - forward.cl)
        guess_cd = guess_cd + (cd - forward.cd)
        guess_cm = guess_cm + (cm - forward.cm)
    return guess_alpha, guess_cl, guess_cd, guess_cm
