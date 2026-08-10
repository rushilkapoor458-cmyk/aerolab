"""Vortex lattice method for finite wings.

Each panel carries a horseshoe vortex: a bound leg on the panel quarter-chord
line and two legs trailing downstream to infinity. Flow tangency is enforced at
the panel three-quarter-chord midpoint, which is the placement that makes a
single panel reproduce thin-airfoil theory exactly and is why the method works
as well as it does with few chordwise panels.

Induced drag by the Trefftz plane, not the near field
-----------------------------------------------------
Near-field induced drag — summing streamwise force on the bound legs — converges
slowly and is sensitive to how the wake leaves the trailing edge. The Trefftz
plane instead looks at the wake far downstream, where only the spanwise
circulation distribution survives. Decomposing that distribution into its
Fourier series gives Glauert's classical result directly:

.. math::
    C_L = \\pi\\,AR\\,A_1, \\qquad
    C_{D_i} = \\pi\\,AR \\sum_n n A_n^2, \\qquad
    e = \\frac{A_1^2}{\\sum_n n A_n^2}

An elliptic loading has only ``A_1``, so ``e = 1`` and
``CDi = CL^2/(pi AR)`` fall out of the definitions rather than being asserted.

Conventions
-----------
``x`` aft, ``y`` to starboard, ``z`` up — a right-handed set. Angles are in
**radians**. Lengths are in whatever unit the wing is defined in; only ratios
matter. Coefficients use the wing's own planform area as reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
from numpy.typing import NDArray

from aerolab.exceptions import SingularSystemError, ValidityRangeError

FloatArray = NDArray[np.float64]

__all__ = [
    "WingSection",
    "Wing",
    "VLMResult",
    "solve_vlm",
    "elliptic_wing",
    "tapered_wing",
]

#: How far downstream the trailing legs are treated as infinite, in spans.
_FAR = 1.0e4


@dataclass(frozen=True)
class WingSection:
    """One defining station of a wing.

    Attributes
    ----------
    y : float
        Spanwise station, positive to starboard.
    chord : float
        Chord length at this station.
    x_le, z_le : float
        Leading-edge position. ``z_le`` carries dihedral; ``x_le`` carries sweep.
    twist : float
        Geometric twist in **radians**, positive nose-up (washin).
    """

    y: float
    chord: float
    x_le: float = 0.0
    z_le: float = 0.0
    twist: float = 0.0


@dataclass(frozen=True)
class Wing:
    """A wing defined by spanwise sections, linearly interpolated between them.

    Parameters
    ----------
    sections : tuple of WingSection
        At least two, ordered by increasing ``y``. Give only the starboard half
        and leave ``mirror`` True for a symmetric wing.
    mirror : bool
        Reflect the given sections about ``y = 0``.
    name : str
        Label.
    """

    sections: tuple[WingSection, ...]
    mirror: bool = True
    name: str = "wing"

    def __post_init__(self) -> None:
        if len(self.sections) < 2:
            raise ValidityRangeError(
                f"a wing needs at least 2 sections, got {len(self.sections)}"
            )
        stations = [s.y for s in self.sections]
        if any(b <= a for a, b in zip(stations, stations[1:])):
            raise ValidityRangeError(
                "wing sections must be ordered by strictly increasing y; got "
                f"{stations}"
            )
        if any(s.chord <= 0.0 for s in self.sections):
            raise ValidityRangeError("every section chord must be positive")

    @cached_property
    def span(self) -> float:
        """Full span, doubled if the wing is mirrored."""
        half = self.sections[-1].y - (0.0 if self.mirror else self.sections[0].y)
        return 2.0 * half if self.mirror else half

    def chord_at(self, y: FloatArray) -> FloatArray:
        """Chord at spanwise stations, by linear interpolation."""
        stations = np.array([s.y for s in self.sections])
        chords = np.array([s.chord for s in self.sections])
        return np.interp(np.abs(y) if self.mirror else y, stations, chords)

    def _interpolate(self, attribute: str, y: FloatArray) -> FloatArray:
        stations = np.array([s.y for s in self.sections])
        values = np.array([getattr(s, attribute) for s in self.sections])
        return np.interp(np.abs(y) if self.mirror else y, stations, values)

    @cached_property
    def area(self) -> float:
        """Planform area, integrated from the interpolated chord distribution."""
        edges = self._span_edges(400)
        centres = 0.5 * (edges[:-1] + edges[1:])
        return float(np.sum(self.chord_at(centres) * np.diff(edges)))

    @cached_property
    def aspect_ratio(self) -> float:
        """``b**2 / S``."""
        return self.span**2 / self.area

    @cached_property
    def mean_chord(self) -> float:
        """Area divided by span."""
        return self.area / self.span

    def _span_edges(self, n_span: int) -> FloatArray:
        """Panel edges, cosine-clustered towards the tips.

        Clustering matters more here than anywhere else in the package: the
        spanwise loading has an infinite gradient at the tip of an elliptic
        wing, and uniform panels put the largest error exactly where the
        induced drag integral is most sensitive.
        """
        root = 0.0 if self.mirror else self.sections[0].y
        tip = self.sections[-1].y
        if self.mirror:
            beta = np.linspace(0.0, np.pi, 2 * n_span + 1)
            return -tip * np.cos(beta)
        beta = np.linspace(0.0, np.pi, n_span + 1)
        return root + (tip - root) * 0.5 * (1.0 - np.cos(beta))


@dataclass(frozen=True)
class VLMResult:
    """Converged vortex-lattice solution at one angle of attack.

    Attributes
    ----------
    wing : Wing
        The wing solved.
    alpha : float
        Angle of attack in **radians**.
    cl : float
        Wing lift coefficient on planform area.
    cdi : float
        Induced drag coefficient, from the Trefftz plane.
    span_efficiency : float
        Oswald-style efficiency ``e = A1**2 / sum(n An**2)``. One for an
        elliptic loading, less for anything else.
    y : ndarray
        Spanwise station of each strip centre.
    chord : ndarray
        Chord at each strip.
    circulation : ndarray
        Total bound circulation of each strip, per unit freestream speed.
    section_cl : ndarray
        Local section lift coefficient at each strip.
    fourier : ndarray
        Glauert coefficients ``A_n`` of the spanwise loading.
    """

    wing: Wing
    alpha: float
    cl: float
    cdi: float
    span_efficiency: float
    y: FloatArray
    chord: FloatArray
    circulation: FloatArray
    section_cl: FloatArray
    fourier: FloatArray

    @property
    def cdi_elliptic(self) -> float:
        """Induced drag the same lift would cost on an elliptic loading."""
        return self.cl**2 / (np.pi * self.wing.aspect_ratio)

    @property
    def lift_distribution(self) -> FloatArray:
        """Local ``c_l * c``, the quantity that integrates to the lift."""
        return self.section_cl * self.chord

    def __repr__(self) -> str:
        return (
            f"<VLMResult {self.wing.name!r} alpha={np.rad2deg(self.alpha):.2f} deg, "
            f"CL={self.cl:.4f}, CDi={self.cdi:.6f}, e={self.span_efficiency:.4f}>"
        )


# ---------------------------------------------------------------------------
# Biot-Savart
# ---------------------------------------------------------------------------


def _segment_velocity(
    points: FloatArray, start: FloatArray, end: FloatArray
) -> FloatArray:
    """Velocity induced by a unit-strength straight vortex filament.

    Parameters
    ----------
    points : ndarray
        ``(p, 3)`` field points.
    start, end : ndarray
        ``(m, 3)`` filament endpoints.

    Returns
    -------
    ndarray
        ``(p, m, 3)`` induced velocity.

    Notes
    -----
    The Biot-Savart result for a finite filament. Points lying on the filament
    are singular; the cross product vanishes there and the contribution is set
    to zero rather than allowed to become infinite, which is the standard
    treatment and is harmless because control points never sit on their own
    bound leg.
    """
    r1 = points[:, None, :] - start[None, :, :]
    r2 = points[:, None, :] - end[None, :, :]
    cross = np.cross(r1, r2)
    square = np.sum(cross * cross, axis=-1)

    norm1 = np.linalg.norm(r1, axis=-1)
    norm2 = np.linalg.norm(r2, axis=-1)
    r0 = (end - start)[None, :, :]

    with np.errstate(divide="ignore", invalid="ignore"):
        scalar = np.sum(r0 * (r1 / norm1[..., None] - r2 / norm2[..., None]), axis=-1)
        factor = scalar / square
    factor = np.where(square > 1e-12, factor, 0.0)
    return cross * factor[..., None] / (4.0 * np.pi)


def _horseshoe_velocity(
    points: FloatArray, left: FloatArray, right: FloatArray, stream: FloatArray
) -> FloatArray:
    """Velocity induced by unit-strength horseshoe vortices.

    The horseshoe runs from downstream infinity to ``left``, across the bound
    leg to ``right``, then back to downstream infinity. "Infinity" is a finite
    point far downstream; at 1e4 spans the remaining contribution is below
    round-off in the influence coefficients.
    """
    far_left = left + _FAR * stream[None, :]
    far_right = right + _FAR * stream[None, :]
    return (
        _segment_velocity(points, far_left, left)
        + _segment_velocity(points, left, right)
        + _segment_velocity(points, right, far_right)
    )


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


def solve_vlm(
    wing: Wing,
    alpha: float,
    *,
    n_span: int = 40,
    n_chord: int = 4,
    n_fourier: int = 20,
) -> VLMResult:
    """Solve a wing at one angle of attack.

    Parameters
    ----------
    wing : Wing
        Geometry.
    alpha : float
        Angle of attack in **radians**.
    n_span : int, optional
        Spanwise panels per semi-span (doubled for a mirrored wing).
    n_chord : int, optional
        Chordwise panels. Four is ample for lift and induced drag; more only
        refines the chordwise pressure distribution, which this method does not
        report.
    n_fourier : int, optional
        Glauert coefficients fitted to the spanwise loading.

    Returns
    -------
    VLMResult

    Raises
    ------
    SingularSystemError
        If the influence matrix is too ill-conditioned to solve.
    """
    if n_span < 4 or n_chord < 1:
        raise ValidityRangeError(
            f"need at least 4 spanwise and 1 chordwise panel, got "
            f"{n_span} and {n_chord}"
        )

    edges = wing._span_edges(n_span)
    strips = edges.size - 1
    y_centre = 0.5 * (edges[:-1] + edges[1:])
    width = np.diff(edges)

    chord = wing.chord_at(y_centre)
    x_le = wing._interpolate("x_le", y_centre)
    z_le = wing._interpolate("z_le", y_centre)
    twist = wing._interpolate("twist", y_centre)

    chord_edge = wing.chord_at(edges)
    x_le_edge = wing._interpolate("x_le", edges)
    z_le_edge = wing._interpolate("z_le", edges)

    # Chordwise panel boundaries as fractions of local chord.
    cuts = np.linspace(0.0, 1.0, n_chord + 1)

    bound_left = np.empty((strips * n_chord, 3))
    bound_right = np.empty((strips * n_chord, 3))
    control = np.empty((strips * n_chord, 3))
    normal = np.empty((strips * n_chord, 3))
    strip_of = np.empty(strips * n_chord, dtype=np.intp)

    for k in range(n_chord):
        lo, hi = cuts[k], cuts[k + 1]
        quarter = lo + 0.25 * (hi - lo)
        three_quarter = lo + 0.75 * (hi - lo)
        index = slice(k * strips, (k + 1) * strips)

        bound_left[index] = np.column_stack(
            [x_le_edge[:-1] + quarter * chord_edge[:-1], edges[:-1], z_le_edge[:-1]]
        )
        bound_right[index] = np.column_stack(
            [x_le_edge[1:] + quarter * chord_edge[1:], edges[1:], z_le_edge[1:]]
        )
        control[index] = np.column_stack(
            [x_le + three_quarter * chord, y_centre, z_le]
        )
        # Twist tilts the local surface, so it tilts the normal.
        normal[index] = np.column_stack(
            [np.sin(twist), np.zeros_like(twist), np.cos(twist)]
        )
        strip_of[index] = np.arange(strips)

    stream = np.array([1.0, 0.0, 0.0])
    influence = _horseshoe_velocity(control, bound_left, bound_right, stream)
    matrix = np.einsum("pmk,pk->pm", influence, normal)

    condition = float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition > 1e12:
        raise SingularSystemError(
            f"the vortex-lattice system is too ill-conditioned to solve "
            f"(condition number {condition:.3e}). This usually means panels of "
            "very unequal size, or two sections at nearly the same station."
        )

    freestream = np.array([np.cos(alpha), 0.0, np.sin(alpha)])
    rhs = -(normal @ freestream)
    gamma = np.linalg.solve(matrix, rhs)

    # Total bound circulation per strip: the chordwise panels of a strip act in
    # series, so their circulations add.
    strip_gamma = np.zeros(strips)
    np.add.at(strip_gamma, strip_of, gamma)

    area = wing.area
    lift_coefficient = float(2.0 * np.sum(strip_gamma * width) / area)
    section_cl = 2.0 * strip_gamma / chord

    fourier = _fit_fourier(y_centre, width, strip_gamma, wing.span, n_fourier)
    aspect = wing.aspect_ratio
    cl_fourier = np.pi * aspect * fourier[0]
    induced = float(np.pi * aspect * np.sum(np.arange(1, fourier.size + 1) * fourier**2))
    efficiency = (
        float(fourier[0] ** 2 / np.sum(np.arange(1, fourier.size + 1) * fourier**2))
        if np.any(fourier)
        else float("nan")
    )

    return VLMResult(
        wing=wing,
        alpha=float(alpha),
        cl=lift_coefficient,
        cdi=induced,
        span_efficiency=efficiency,
        y=y_centre,
        chord=chord,
        circulation=strip_gamma,
        section_cl=section_cl,
        fourier=fourier,
    )


def _fit_fourier(
    y: FloatArray,
    width: FloatArray,
    gamma: FloatArray,
    span: float,
    n_fourier: int,
) -> FloatArray:
    """Fit Glauert coefficients to the spanwise circulation.

    With ``y = -(b/2) cos(theta)`` the loading is written
    ``Gamma(theta) = 2 b V sum_n A_n sin(n theta)``. Fitting by least squares
    over the strips, weighted by strip width, keeps the tip strips from
    dominating simply because the cosine spacing makes them numerous.

    Only **odd** harmonics are kept for a symmetric wing? No — all are fitted.
    An asymmetric loading (from asymmetric twist, say) genuinely contains even
    harmonics, and dropping them would silently symmetrise the answer.
    """
    theta = np.arccos(np.clip(-2.0 * y / span, -1.0, 1.0))
    orders = np.arange(1, n_fourier + 1)
    basis = np.sin(np.outer(theta, orders))
    scale = np.sqrt(width)
    coefficients, *_ = np.linalg.lstsq(
        basis * scale[:, None], gamma * scale / (2.0 * span), rcond=None
    )
    return coefficients


# ---------------------------------------------------------------------------
# Convenience planforms
# ---------------------------------------------------------------------------


def elliptic_wing(
    span: float = 8.0, root_chord: float = 1.0, n_sections: int = 60
) -> Wing:
    """An elliptic planform, the reference case for span efficiency.

    Parameters
    ----------
    span : float
        Full span.
    root_chord : float
        Chord at the centreline.
    n_sections : int, optional
        Defining stations. The planform is exactly elliptic only in the limit;
        60 stations put the area within 0.01% of ``pi b c_root / 4``.

    Returns
    -------
    Wing
    """
    y = np.linspace(0.0, span / 2.0, n_sections)
    ratio = np.clip(1.0 - (2.0 * y / span) ** 2, 0.0, None)
    chord = root_chord * np.sqrt(ratio)
    # The tip chord is zero, which the constructor rejects; pull it just clear.
    chord[-1] = max(chord[-1], 1e-4 * root_chord)
    return Wing(
        sections=tuple(
            WingSection(y=float(yy), chord=float(cc)) for yy, cc in zip(y, chord)
        ),
        name="elliptic",
    )


def tapered_wing(
    span: float = 8.0,
    root_chord: float = 1.2,
    taper: float = 0.5,
    sweep: float = 0.0,
    dihedral: float = 0.0,
    twist_tip: float = 0.0,
) -> Wing:
    """A straight-tapered wing with optional sweep, dihedral and washout.

    Parameters
    ----------
    span : float
        Full span.
    root_chord : float
        Chord at the centreline.
    taper : float
        Tip chord divided by root chord.
    sweep : float
        Leading-edge sweep in **radians**, positive aft.
    dihedral : float
        Dihedral in **radians**, positive tip-up.
    twist_tip : float
        Tip twist in **radians**, negative for washout.

    Returns
    -------
    Wing
    """
    half = span / 2.0
    return Wing(
        sections=(
            WingSection(y=0.0, chord=root_chord),
            WingSection(
                y=half,
                chord=root_chord * taper,
                x_le=half * np.tan(sweep),
                z_le=half * np.tan(dihedral),
                twist=twist_tip,
            ),
        ),
        name="tapered",
    )
