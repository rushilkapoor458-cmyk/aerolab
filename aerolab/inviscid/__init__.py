"""Potential-flow solvers.

2D: the Hess-Smith panel method — constant-strength source panels for thickness,
one constant-strength vortex sheet for circulation, closed by the Kutta
condition at the trailing edge.

3D: the vortex lattice method for planar and dihedral wings (Phase 6).

Angles of attack are in **radians**. Velocities are non-dimensionalised by the
freestream speed ``V_inf``, so a returned field is ``V / V_inf``. ``Cm`` is
positive **nose-up** about the quarter chord.
"""

from aerolab.inviscid.hess_smith import (
    HessSmithSystem,
    PanelSolution,
    solve_panel_method,
)
from aerolab.inviscid.influence import panel_frames, panel_influence, self_influence

__all__ = [
    "HessSmithSystem",
    "PanelSolution",
    "solve_panel_method",
    "panel_influence",
    "panel_frames",
    "self_influence",
]
