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

Two coupled solvers live here. :func:`solve_coupled` iterates the inviscid and
viscous problems in sequence and does not converge, for reasons diagnosed in
NOTES.md (L4.5); it is kept because that diagnosis is part of the record.
:func:`solve_newton` solves them **simultaneously** and does converge.
"""

from aerolab.viscous.boundary_layer import (
    BoundaryLayerSolution,
    EdgeDistribution,
    SurfaceBoundaryLayer,
    edge_distributions,
    solve_boundary_layer,
)
from aerolab.viscous.coupling import (
    CoupledSolution,
    coupled_polar,
    solve_coupled,
    transpiration_velocity,
)
from aerolab.viscous.closure import (
    HEAD_H_MAX,
    H_SEPARATION_LAMINAR,
    LAMBDA_SEPARATION,
    laminar_cf_reynolds_theta,
    laminar_dissipation_reynolds_theta,
    laminar_h_star,
    TURBULENT_SEPARATION_H,
    head_entrainment,
    head_h1_from_h,
    head_h_from_h1,
    ludwieg_tillmann_cf,
    thwaites_shape_factor,
    thwaites_shear,
)
from aerolab.viscous.falkner_skan import (
    BETA_SEPARATION,
    FalknerSkanSolution,
    falkner_skan_family,
    solve_falkner_skan,
)
from aerolab.viscous.newton import (
    NewtonSolution,
    PrescribedLayer,
    newton_polar,
    solve_newton,
    solve_prescribed,
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
    "solve_coupled",
    "coupled_polar",
    "CoupledSolution",
    "transpiration_velocity",
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
    "solve_newton",
    "newton_polar",
    "NewtonSolution",
    "solve_prescribed",
    "PrescribedLayer",
    "solve_falkner_skan",
    "falkner_skan_family",
    "FalknerSkanSolution",
    "BETA_SEPARATION",
    "laminar_h_star",
    "laminar_cf_reynolds_theta",
    "laminar_dissipation_reynolds_theta",
    "H_SEPARATION_LAMINAR",
    "HEAD_H_MAX",
    "LAMBDA_SEPARATION",
    "TURBULENT_SEPARATION_H",
    "predict_transition",
    "michel_criterion",
    "critical_reynolds_theta",
    "amplification_rate",
    "TransitionResult",
    "DEFAULT_N_CRIT",
]
