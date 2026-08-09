"""Laminar-to-turbulent transition prediction.

Two methods, selectable, because they answer different questions.

**Michel's criterion** is a single algebraic relation between ``Re_theta`` and
``Re_s`` fitted to low-turbulence wind-tunnel data on airfoils. It has no free
parameter, which makes it reproducible but also unable to represent a tunnel
that is noisier or quieter than the ones it was fitted to.

**The e^N envelope method** integrates a growth rate for the most amplified
Tollmien-Schlichting wave and declares transition when the amplification factor
reaches ``N``. That single parameter is the point: ``N = 9`` corresponds to a
low-turbulence tunnel or free flight, and a noisier tunnel is represented by a
lower value — ``N = 4`` to 7 for a typical small open-circuit tunnel. Since this
package exists to be compared against a tunnel that is being built, having that
knob is the whole reason the method is here.

Conventions
-----------
``s`` is surface distance from the stagnation point, non-dimensionalised by
chord. ``Ue`` is non-dimensionalised by freestream speed. Reynolds numbers with
no subscript are based on chord.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from aerolab.exceptions import ValidityRangeError

FloatArray = NDArray[np.float64]

TransitionMethod = Literal["en", "michel"]

__all__ = [
    "DEFAULT_N_CRIT",
    "TransitionResult",
    "michel_criterion",
    "critical_reynolds_theta",
    "amplification_rate",
    "predict_transition",
]

#: Amplification factor for a low-turbulence tunnel or free flight.
#:
#: Lower it for a noisier stream. Mack's correlation relates it to the
#: freestream turbulence level ``Tu`` by ``N = -8.43 - 2.4 ln(Tu)``, so
#: Tu = 0.1% gives N = 8.2 and Tu = 1% gives N = 2.6.
DEFAULT_N_CRIT = 9.0


@dataclass(frozen=True)
class TransitionResult:
    """Where transition was predicted, and by what.

    Attributes
    ----------
    occurred : bool
        Whether transition was predicted before the end of the laminar run.
    s : float or None
        Surface distance from the stagnation point, in chords.
    index : int or None
        Index into the supplied arrays of the first station past transition.
    method : {"en", "michel", "laminar-separation"}
        What triggered it. ``laminar-separation`` means the laminar layer
        separated before either transition criterion was met; see
        :mod:`aerolab.viscous.boundary_layer` for what is assumed then.
    n_factor : ndarray or None
        Amplification factor along the surface, for the e^N method only.
    """

    occurred: bool
    s: float | None
    index: int | None
    method: str
    n_factor: FloatArray | None = None


def michel_criterion(re_s: ArrayLike) -> FloatArray:
    """Momentum-thickness Reynolds number at transition, by Michel's criterion.

    Parameters
    ----------
    re_s : array_like
        Reynolds number based on surface distance from the stagnation point,
        ``Re_s = Ue * s / nu``. Must be positive.

    Returns
    -------
    ndarray
        The ``Re_theta`` at which transition is predicted. Transition occurs
        where the actual ``Re_theta`` first exceeds this.

    Notes
    -----
    ``Re_theta,tr = 1.174 (1 + 22400/Re_s) Re_s**0.46``, valid for
    ``1e5 < Re_s < 4e7``. The bracketed factor matters only at low ``Re_s``; by
    ``Re_s = 1e6`` it has fallen to 1.02.
    """
    rs = np.asarray(re_s, dtype=np.float64)
    if np.any(rs <= 0.0):
        raise ValidityRangeError("Re_s must be positive for Michel's criterion")
    return 1.174 * (1.0 + 22400.0 / rs) * rs**0.46


def critical_reynolds_theta(h: ArrayLike) -> FloatArray:
    """Momentum-thickness Reynolds number at which amplification begins.

    Parameters
    ----------
    h : array_like
        Laminar shape factor, greater than 1.

    Returns
    -------
    ndarray
        Critical ``Re_theta``. Below this the boundary layer is stable and the
        amplification factor does not grow.

    Notes
    -----
    Drela and Giles' fit to the Orr-Sommerfeld neutral curve for Falkner-Skan
    profiles:

    .. math::
        \\log_{10} Re_{\\theta,crit} =
            \\left(\\frac{1.415}{H-1} - 0.489\\right)
            \\tanh\\!\\left(\\frac{20}{H-1} - 12.9\\right)
            + \\frac{3.295}{H-1} + 0.44

    At the Blasius value ``H = 2.59`` this gives ``Re_theta,crit = 224``, which
    is the classical flat-plate neutral point.
    """
    hh = np.asarray(h, dtype=np.float64)
    if np.any(hh <= 1.0):
        raise ValidityRangeError(
            f"H = {float(np.min(hh)):.4f} is at or below 1; the stability "
            "correlation is singular there"
        )
    hm1 = hh - 1.0
    log_re = (
        (1.415 / hm1 - 0.489) * np.tanh(20.0 / hm1 - 12.9) + 3.295 / hm1 + 0.44
    )
    return 10.0**log_re


def amplification_rate(h: ArrayLike) -> FloatArray:
    """Envelope growth rate ``dn/dRe_theta`` as a function of shape factor.

    Parameters
    ----------
    h : array_like
        Laminar shape factor.

    Returns
    -------
    ndarray
        Growth of the amplification factor per unit ``Re_theta``.

    Notes
    -----
    ``dn/dRe_theta = 0.01 sqrt[(2.4H - 3.7 + 2.5 tanh(1.5H - 4.65))**2 + 0.25]``.

    At the Blasius value ``H = 2.59`` this gives 0.0107, so reaching ``N = 9``
    from the neutral point at ``Re_theta = 224`` takes another 840 in
    ``Re_theta`` — a flat-plate transition Reynolds number of about
    ``Re_x = 2.5e6``, which is the accepted figure for a quiet stream.
    """
    hh = np.asarray(h, dtype=np.float64)
    inner = 2.4 * hh - 3.7 + 2.5 * np.tanh(1.5 * hh - 4.65)
    return 0.01 * np.sqrt(inner**2 + 0.25)


def predict_transition(
    s: FloatArray,
    ue: FloatArray,
    theta: FloatArray,
    h: FloatArray,
    reynolds: float,
    *,
    method: TransitionMethod = "en",
    n_crit: float = DEFAULT_N_CRIT,
) -> TransitionResult:
    """Locate transition along one surface.

    Parameters
    ----------
    s : ndarray
        Surface distance from the stagnation point, in chords, increasing.
    ue : ndarray
        Edge velocity, non-dimensionalised by freestream speed.
    theta : ndarray
        Momentum thickness, in chords.
    h : ndarray
        Laminar shape factor.
    reynolds : float
        Reynolds number based on **chord**.
    method : {"en", "michel"}, optional
        Which criterion to apply.
    n_crit : float, optional
        Amplification factor at transition, for the e^N method.

    Returns
    -------
    TransitionResult

    Notes
    -----
    The e^N integration accumulates only positive increments of the
    amplification factor. Disturbances that have grown do not un-grow when the
    pressure gradient turns favourable again; allowing the factor to fall would
    let a mid-chord favourable stretch erase amplification that has physically
    already happened.
    """
    re_theta = reynolds * ue * theta

    if method == "michel":
        re_s = reynolds * ue * s
        valid = re_s > 0.0
        threshold = np.full_like(re_s, np.inf)
        threshold[valid] = michel_criterion(re_s[valid])
        crossed = np.nonzero(valid & (re_theta >= threshold))[0]
        if crossed.size == 0:
            return TransitionResult(False, None, None, "michel")
        index = int(crossed[0])
        return TransitionResult(True, float(s[index]), index, "michel")

    if method != "en":
        raise ValidityRangeError(
            f"transition method must be 'en' or 'michel', got {method!r}"
        )
    if n_crit <= 0.0:
        raise ValidityRangeError(f"n_crit must be positive, got {n_crit}")

    n_factor = np.zeros_like(s)
    critical = critical_reynolds_theta(np.clip(h, 1.0001, None))
    rate = amplification_rate(h)

    transition_index: int | None = None
    for i in range(1, s.size):
        growing = re_theta[i] > critical[i]
        step = re_theta[i] - re_theta[i - 1]
        increment = 0.0
        if growing and step > 0.0:
            increment = 0.5 * (rate[i] + rate[i - 1]) * step
        n_factor[i] = n_factor[i - 1] + increment
        if transition_index is None and n_factor[i] >= n_crit:
            transition_index = i

    if transition_index is None:
        return TransitionResult(False, None, None, "en", n_factor)
    return TransitionResult(
        True, float(s[transition_index]), transition_index, "en", n_factor
    )
