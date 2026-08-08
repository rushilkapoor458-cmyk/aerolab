"""Integral boundary-layer methods, transition prediction, and profile drag.

Laminar run by Thwaites' method from the stagnation point; transition by
Michel's criterion or an e^N envelope method; turbulent run by Head's
entrainment method with Ludwieg-Tillmann skin friction; profile drag by
Squire-Young.

Streamwise distance ``s`` is measured along the surface from the stagnation
point and non-dimensionalised by chord. Boundary-layer thicknesses (delta*,
theta) are likewise non-dimensionalised by chord. Reynolds numbers are based
on chord unless the name says ``Re_theta``.
"""
