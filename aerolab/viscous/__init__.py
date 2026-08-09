"""Integral boundary-layer methods, transition prediction, and profile drag.

Laminar run by Thwaites' method from the stagnation point; transition by
Michel's criterion or an e^N envelope method; turbulent run by Head's
entrainment method with Ludwieg-Tillmann skin friction; profile drag by
Squire-Young.

Streamwise distance ``s`` is measured along the surface from the stagnation
point and non-dimensionalised by chord. Boundary-layer thicknesses (delta*,
theta) are likewise non-dimensionalised by chord. Reynolds numbers are based
on chord unless the name says ``Re_theta``. Skin friction ``cf`` uses the local
**edge** dynamic pressure, not the freestream.

This phase is **one-way**: the boundary layer reads the inviscid edge velocity
and does not feed back into it. Phase 4 adds the coupling.
"""

from aerolab.viscous.boundary_layer import (
    BoundaryLayerSolution,
    EdgeDistribution,
    SurfaceBoundaryLayer,
    edge_distributions,
    solve_boundary_layer,
)
from aerolab.viscous.closure import (
    LAMBDA_SEPARATION,
    TURBULENT_SEPARATION_H,
    head_entrainment,
    head_h1_from_h,
    head_h_from_h1,
    ludwieg_tillmann_cf,
    thwaites_shape_factor,
    thwaites_shear,
)
from aerolab.viscous.transition import (
    DEFAULT_N_CRIT,
    TransitionResult,
    amplification_rate,
    critical_reynolds_theta,
    michel_criterion,
    predict_transition,
)

__all__ = [
    "solve_boundary_layer",
    "BoundaryLayerSolution",
    "SurfaceBoundaryLayer",
    "EdgeDistribution",
    "edge_distributions",
    "thwaites_shape_factor",
    "thwaites_shear",
    "head_h1_from_h",
    "head_h_from_h1",
    "head_entrainment",
    "ludwieg_tillmann_cf",
    "LAMBDA_SEPARATION",
    "TURBULENT_SEPARATION_H",
    "predict_transition",
    "michel_criterion",
    "critical_reynolds_theta",
    "amplification_rate",
    "TransitionResult",
    "DEFAULT_N_CRIT",
]
