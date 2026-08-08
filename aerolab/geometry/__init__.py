"""Airfoil geometry: generation, import, repaneling, and geometric properties.

Coordinates are non-dimensionalised by chord throughout: ``x`` in [0, 1] aft
from the leading edge, ``z`` positive up. Surface point ordering follows the
Selig convention internally — trailing edge, forward along the upper surface
to the leading edge, then aft along the lower surface back to the trailing
edge — regardless of the ordering of any imported file.
"""
