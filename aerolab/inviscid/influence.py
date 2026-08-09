"""Influence coefficients for constant-strength source and vortex panels.

A flat panel of length ``S`` carrying a uniform sheet strength induces a
velocity field that is known in closed form. Working in a frame aligned with the
panel, with ``xi`` along it from the start point and ``eta`` perpendicular:

.. math::
    r_1 = \\sqrt{\\xi^2 + \\eta^2}, \\qquad
    r_2 = \\sqrt{(\\xi - S)^2 + \\eta^2}

    \\Delta\\theta = \\operatorname{atan2}(\\eta,\\, \\xi - S)
                   - \\operatorname{atan2}(\\eta,\\, \\xi)

For a **source** sheet of unit strength per unit length,
``(u_xi, u_eta) = (ln(r1/r2), dtheta) / (2*pi)``; for a **vortex** sheet,
``(u_xi, u_eta) = (dtheta, -ln(r1/r2)) / (2*pi)``. The vortex field is the
source field rotated by ninety degrees, which is why one routine computes both.

Handedness
----------
The local frame used by these formulas is **right-handed**: tangent
``t = (cos, sin)`` and local normal ``n_loc = (-sin, cos)``, so ``t x n_loc = +1``.
That is *not* the outward normal of a counter-clockwise airfoil contour, which is
``(sin, -cos) = -n_loc``. The distinction is invisible everywhere except on the
sheet itself, where the field is discontinuous — and that is exactly where the
self-influence terms live. See :func:`self_influence`.

Sign of the vortex sheet
------------------------
With these formulas a positive ``gamma`` produces **clockwise** circulation.
Check it far above the panel: at ``xi = S/2`` and large ``eta``,
``dtheta -> S/eta``, so ``u_xi -> S/(2*pi*eta) > 0``. Fluid above the sheet moves
in ``+t``, which is a clockwise sense. Positive lift on an airfoil therefore
corresponds to positive ``gamma`` here.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from aerolab.exceptions import GeometryError

FloatArray = NDArray[np.float64]

__all__ = ["panel_influence", "self_influence", "panel_frames"]

TWO_PI = 2.0 * np.pi


def panel_frames(
    starts: FloatArray, ends: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Lengths, unit tangents and right-handed local normals of panels.

    Parameters
    ----------
    starts, ends : ndarray
        ``(m, 2)`` arrays of panel endpoints, in chords.

    Returns
    -------
    lengths : ndarray
        ``(m,)`` panel lengths, in chords.
    tangents : ndarray
        ``(m, 2)`` unit tangents from start to end.
    local_normals : ndarray
        ``(m, 2)`` unit normals ``(-t_z, t_x)``, forming a right-handed pair with
        the tangent. For a counter-clockwise airfoil contour these point
        **inward**; the outward normal is their negative.
    """
    delta = ends - starts
    lengths = np.hypot(delta[:, 0], delta[:, 1])
    if np.any(lengths <= 0.0):
        bad = int(np.argmin(lengths))
        raise GeometryError(
            f"panel {bad} has zero length; influence coefficients are undefined"
        )
    tangents = delta / lengths[:, None]
    local_normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
    return lengths, tangents, local_normals


def panel_influence(
    starts: FloatArray, ends: FloatArray, points: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Velocity induced at ``points`` by unit-strength source and vortex panels.

    Parameters
    ----------
    starts, ends : ndarray
        ``(m, 2)`` arrays of panel endpoints, in chords.
    points : ndarray
        ``(p, 2)`` array of field points, in chords.

    Returns
    -------
    source : ndarray
        ``(p, m, 2)`` velocity at each point due to each panel carrying unit
        source strength per unit length, non-dimensionalised the same way as the
        strengths themselves.
    vortex : ndarray
        ``(p, m, 2)`` the same for unit vortex strength per unit length.

    Notes
    -----
    A point lying exactly on a panel is a genuine singularity of the sheet: the
    tangential velocity jumps across it. This routine returns the limit
    approached from the ``n_loc`` side, which for a counter-clockwise airfoil is
    the **interior**. Callers that need the exterior limit — which is every
    caller solving a flow — must substitute :func:`self_influence` for the
    diagonal. :class:`~aerolab.inviscid.hess_smith.HessSmithSystem` does exactly
    that.
    """
    starts = np.atleast_2d(np.asarray(starts, dtype=np.float64))
    ends = np.atleast_2d(np.asarray(ends, dtype=np.float64))
    points = np.atleast_2d(np.asarray(points, dtype=np.float64))

    lengths, tangents, normals = panel_frames(starts, ends)

    # (p, m, 2) offsets from each panel start to each field point.
    offset = points[:, None, :] - starts[None, :, :]
    xi = np.einsum("pmk,mk->pm", offset, tangents)
    eta = np.einsum("pmk,mk->pm", offset, normals)

    xi_minus = xi - lengths[None, :]
    r1_sq = xi**2 + eta**2
    r2_sq = xi_minus**2 + eta**2

    with np.errstate(divide="ignore", invalid="ignore"):
        log_term = 0.5 * np.log(r1_sq / r2_sq)
    log_term = np.where(np.isfinite(log_term), log_term, 0.0)

    d_theta = np.arctan2(eta, xi_minus) - np.arctan2(eta, xi)

    source_xi = log_term / TWO_PI
    source_eta = d_theta / TWO_PI
    vortex_xi = d_theta / TWO_PI
    vortex_eta = -log_term / TWO_PI

    def to_global(comp_xi: FloatArray, comp_eta: FloatArray) -> FloatArray:
        return (
            comp_xi[:, :, None] * tangents[None, :, :]
            + comp_eta[:, :, None] * normals[None, :, :]
        )

    return to_global(source_xi, source_eta), to_global(vortex_xi, vortex_eta)


def self_influence(
    tangents: FloatArray, local_normals: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Velocity a panel induces at its own midpoint, on its **exterior** side.

    Parameters
    ----------
    tangents, local_normals : ndarray
        ``(m, 2)`` panel frames from :func:`panel_frames`.

    Returns
    -------
    source : ndarray
        ``(m, 2)`` self-induced velocity per unit source strength.
    vortex : ndarray
        ``(m, 2)`` self-induced velocity per unit vortex strength.

    Notes
    -----
    Taking the limit ``eta -> 0`` from the side the outward normal points to —
    which is ``eta -> 0^-`` in the right-handed local frame, since ``n_loc`` is
    the *inward* normal of a counter-clockwise contour — gives
    ``dtheta -> -pi`` and ``ln(r1/r2) -> 0`` at the midpoint. Hence

    - source: ``u_eta = -1/2`` along ``n_loc``, i.e. ``+1/2`` **outward**. A
      source sheet blows fluid away from itself at half its strength.
    - vortex: ``u_xi = -1/2`` along the tangent. A vortex sheet produces
      ``-gamma/2`` on one side and ``+gamma/2`` on the other.

    Getting this sign wrong is not a small error: it reverses the boundary
    condition on every panel simultaneously, and the solver would still converge,
    to a flow through the airfoil rather than around it. The exterior limit is
    verified in ``tests/test_inviscid_influence.py`` by approaching the panel
    from a measurable distance outside and extrapolating, rather than by
    restating the algebra above.
    """
    return -0.5 * local_normals, -0.5 * tangents
