"""Wind-tunnel wall corrections and experimental data import.

Solid blockage, wake blockage, streamline curvature and horizontal buoyancy for
a two-dimensional model in a closed test section, following Allen and Vincenti
as presented in Barlow, Rae and Pope, *Low-Speed Wind Tunnel Testing*, 3rd ed.

Corrections are applied to *measured* coefficients to yield *corrected* free-air
ones. Every blockage correction reduces the coefficient, because the model saw a
higher dynamic pressure than the reference probe recorded; the angle correction
goes the other way. The direction of every correction is stated in its docstring
and asserted in the tests, because a sign error here is silent.
"""

from aerolab.tunnel.corrections import (
    TunnelSection,
    WallCorrection,
    correct_two_dimensional,
    sigma,
    solid_blockage_factor,
    uncorrect_two_dimensional,
)
from aerolab.tunnel.experiment import (
    Comparison,
    Measurements,
    compare_with_polar,
    read_measurements,
    write_template,
)

__all__ = [
    "TunnelSection",
    "WallCorrection",
    "correct_two_dimensional",
    "uncorrect_two_dimensional",
    "sigma",
    "solid_blockage_factor",
    "Measurements",
    "Comparison",
    "read_measurements",
    "write_template",
    "compare_with_polar",
]
