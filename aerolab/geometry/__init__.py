"""Airfoil geometry: generation, import, repaneling, and geometric properties.

Coordinates are non-dimensionalised by chord throughout: ``x`` in [0, 1] aft
from the leading edge, ``z`` positive up. Surface point ordering follows the
Selig convention internally — trailing edge, forward along the upper surface
to the leading edge, then aft along the lower surface back to the trailing
edge — regardless of the ordering of any imported file. Traversed that way the
contour is clockwise, which is what orients panel normals outward.

Angles are in **radians** at every boundary of this subpackage.
"""

from aerolab.geometry.airfoil import Airfoil, Extremum
from aerolab.geometry.dat_io import DatFile, parse_dat, read_dat, write_dat
from aerolab.geometry.naca import (
    FiveDigitCamber,
    camber_line_4digit,
    camber_line_5digit,
    naca,
    naca4,
    naca5,
    solve_five_digit_camber,
    thickness_distribution,
)
from aerolab.geometry.panels import Panels
from aerolab.geometry.repanel import COSINE, UNIFORM, clustered_fractions, repanel

__all__ = [
    "Airfoil",
    "Extremum",
    "Panels",
    "DatFile",
    "read_dat",
    "write_dat",
    "parse_dat",
    "naca",
    "naca4",
    "naca5",
    "thickness_distribution",
    "camber_line_4digit",
    "camber_line_5digit",
    "FiveDigitCamber",
    "solve_five_digit_camber",
    "repanel",
    "clustered_fractions",
    "COSINE",
    "UNIFORM",
]
