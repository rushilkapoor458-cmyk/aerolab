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


# ---------------------------------------------------------------------------
# Joukowski airfoil: a thick, cambered section with an exact solution
# ---------------------------------------------------------------------------
#
# A circle of radius R centred at zeta_c and passing through zeta = a is mapped
# by z = zeta + a**2/zeta. The circle passing exactly through the map's critical
# point is what produces a closed (cusped) trailing edge. Putting the rear
# stagnation point there is the Kutta condition, and it fixes the circulation:
#
#     Gamma = 4 * pi * R * V_inf * sin(alpha - beta),   beta = arg(a - zeta_c)
#
# with Gamma positive **clockwise**, matching the sign convention of
# aerolab.inviscid.influence. Lift follows from Kutta-Joukowski.
#
# This matters because it is the only reference in the suite that is
# simultaneously thick, cambered and exact. Symmetric NACA sections have
# closed-form *geometry* but no closed-form flow; the cylinder has an exact flow
# but no camber and no Kutta condition.

JOUKOWSKI_A = 1.0


class Joukowski:
    """A Joukowski airfoil together with its exact incompressible solution.

    Parameters
    ----------
    x_offset, z_offset : float
        Circle-centre offsets ``(-x_offset, z_offset)`` in the mapping plane.
        ``x_offset`` controls thickness, ``z_offset`` controls camber.

    Attributes
    ----------
    radius : float
        Radius of the circle in the mapping plane.
    beta : float
        ``arg(a - zeta_c)`` in radians; the mean-line angle at the trailing edge.
    """

    def __init__(self, x_offset: float = 0.10, z_offset: float = 0.08) -> None:
        self.centre = complex(-x_offset, z_offset)
        self.radius = abs(JOUKOWSKI_A - self.centre)
        self.beta = float(np.angle(JOUKOWSKI_A - self.centre))

    def circle(self, n: int) -> np.ndarray:
        """``n`` points on the mapping-plane circle, starting at the trailing edge."""
        theta = np.linspace(0.0, 2.0 * np.pi, n)
        return self.centre + self.radius * np.exp(1j * (theta + self.beta))

    def airfoil(self, n: int = 641) -> Airfoil:
        """The mapped section, in Selig order.

        Points are uniform in mapping-plane angle, which the transformation turns
        into extremely fine spacing at the cusped trailing edge (panel lengths
        there shrink quadratically) and coarser spacing elsewhere.
        """
        zeta = self.circle(n)
        z = zeta + JOUKOWSKI_A**2 / zeta
        return Airfoil.from_points(z.real, z.imag, name="Joukowski")

    def circulation(self, alpha: float) -> float:
        """Exact circulation, positive clockwise, for unit freestream speed.

        Parameters
        ----------
        alpha : float
            Angle of attack in **radians**.
        """
        return float(
            4.0 * np.pi * self.radius * np.sin(alpha - self.beta)
        )

    def cl(self, alpha: float, chord: float) -> float:
        """Exact lift coefficient, non-dimensionalised by ``chord``.

        Parameters
        ----------
        alpha : float
            Angle of attack in **radians**.
        chord : float
            Chord to divide by. Pass the panelled section's own
            :attr:`~aerolab.geometry.airfoil.Airfoil.chord` so the two
            coefficients share a reference length.
        """
        return 2.0 * self.circulation(alpha) / chord

    def surface_speed(self, zeta: np.ndarray, alpha: float) -> np.ndarray:
        """Exact speed on the surface, at mapping-plane points ``zeta``.

        Parameters
        ----------
        zeta : ndarray
            Complex points **on the circle**. Passing physical-plane points and
            inverting the map numerically is a trap: on the surface the two
            branches of the inverse coincide, and the branch test becomes a coin
            flip that silently returns interior values.
        alpha : float
            Angle of attack in radians.
        """
        gamma = self.circulation(alpha)
        offset = zeta - self.centre
        dw_dzeta = (
            np.exp(-1j * alpha)
            - self.radius**2 * np.exp(1j * alpha) / offset**2
            + 1j * gamma / (2.0 * np.pi * offset)
        )
        return np.abs(dw_dzeta / (1.0 - JOUKOWSKI_A**2 / zeta**2))

    def velocity(self, points: np.ndarray, alpha: float) -> np.ndarray:
        """Exact velocity at physical-plane points **outside** the section.

        Parameters
        ----------
        points : ndarray
            ``(p, 2)`` array of ``(x, z)`` positions. Must lie clear of the
            surface, where the inverse map is ambiguous.
        alpha : float
            Angle of attack in radians.

        Returns
        -------
        ndarray
            ``(p, 2)`` velocity vectors for unit freestream speed.
        """
        z = points[:, 0] + 1j * points[:, 1]
        root = np.sqrt((z / 2.0) ** 2 - JOUKOWSKI_A**2 + 0j)
        zeta = z / 2.0 + root
        inside = np.abs(zeta - self.centre) < self.radius
        zeta[inside] = z[inside] / 2.0 - root[inside]

        gamma = self.circulation(alpha)
        offset = zeta - self.centre
        dw_dzeta = (
            np.exp(-1j * alpha)
            - self.radius**2 * np.exp(1j * alpha) / offset**2
            + 1j * gamma / (2.0 * np.pi * offset)
        )
        w = dw_dzeta / (1.0 - JOUKOWSKI_A**2 / zeta**2)
        return np.column_stack([w.real, -w.imag])
