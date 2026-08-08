"""Wind-tunnel wall corrections and experimental data import.

Solid blockage, wake blockage, streamline curvature, and horizontal buoyancy
for closed and open test sections, following the formulations in Barlow, Rae
and Pope, *Low-Speed Wind Tunnel Testing*, 3rd ed.

Corrections are applied to *measured* coefficients to yield *corrected*
free-air coefficients; the direction of every correction is stated in the
function docstring, because sign errors here are silent and fatal.
"""
