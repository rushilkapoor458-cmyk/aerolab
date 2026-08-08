"""Potential-flow solvers.

2D: the Hess-Smith panel method (constant-strength source panels for
thickness, one constant-strength vortex sheet for circulation, closed by the
Kutta condition).

3D: the vortex lattice method for planar and dihedral wings.

Angles of attack are in radians. Velocities are non-dimensionalised by the
freestream speed ``V_inf``, so the returned field is ``V / V_inf``.
"""
