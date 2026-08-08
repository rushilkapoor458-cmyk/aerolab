"""aerolab — a subsonic aerodynamics toolkit.

Subpackages
-----------
geometry
    Airfoil generation (NACA series), ``.dat`` coordinate import, and repaneling.
inviscid
    Potential-flow solvers: 2D panel methods and 3D vortex lattice.
viscous
    Integral boundary-layer methods, transition prediction, and profile drag.
compressible
    Compressibility corrections and quasi-1D duct flow.
tunnel
    Wind-tunnel wall/blockage corrections and experimental data import.
validation
    Reference datasets and regeneration of the validation report.

Conventions
-----------
These hold at every public boundary of the package unless a docstring says
otherwise. They are repeated in each module's docstring so that no function
has to be read in isolation.

Angles
    All angles in function *signatures* and *return values* are in **radians**.
    Degrees appear only in the CLI, in file formats, and in plot labels; the
    conversion happens at those boundaries and nowhere else. Parameters that
    are an exception carry a ``_deg`` suffix in their name.
Coordinates
    Airfoil coordinates are non-dimensionalised by the chord ``c``, so ``x``
    runs from 0 at the leading edge to 1 at the trailing edge. ``x`` points
    aft along the chord line, ``z`` points up. The 3D wing frame adds ``y``
    to starboard, giving a right-handed set.
Force coefficients
    2D (sectional) coefficients are lowercase in the literature but written
    ``Cl``, ``Cd``, ``Cm`` here for typability; they are non-dimensionalised
    by ``q_inf * c`` per unit span, where ``q_inf = 0.5 * rho * V_inf**2``.
    3D coefficients are non-dimensionalised by ``q_inf * S_ref``.
    Pitching moment ``Cm`` is positive **nose-up**, taken about the quarter
    chord unless the argument name says otherwise.
Pressure coefficient
    ``Cp = (p - p_inf) / q_inf``. Incompressible and inviscid, ``Cp = 1 - (V/V_inf)**2``.
Reynolds number
    ``Re = rho * V_inf * c / mu``, always based on **chord**, never on
    momentum thickness, unless the name says ``Re_theta``.
"""

from __future__ import annotations

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
