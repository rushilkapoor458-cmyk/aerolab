"""Compressibility corrections and quasi-1D duct flow.

Prandtl-Glauert and Karman-Tsien corrections to incompressible pressure
coefficients, plus the local and critical Mach numbers they imply.

Both corrections lose validity as the local Mach number approaches unity. This
subpackage reports the peak local Mach number with every corrected field and
flags results above 0.7 rather than returning them silently; above Mach 0.95
freestream it refuses outright.
"""

from aerolab.compressible.corrections import (
    GAMMA_AIR,
    TRUSTWORTHY_LOCAL_MACH,
    CompressibleField,
    apply_correction,
    critical_mach_number,
    karman_tsien,
    local_mach_number,
    prandtl_glauert,
)

__all__ = [
    "apply_correction",
    "CompressibleField",
    "prandtl_glauert",
    "karman_tsien",
    "local_mach_number",
    "critical_mach_number",
    "GAMMA_AIR",
    "TRUSTWORTHY_LOCAL_MACH",
]
