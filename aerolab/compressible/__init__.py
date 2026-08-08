"""Compressibility corrections and quasi-1D duct flow.

Prandtl-Glauert and Karman-Tsien corrections to incompressible pressure
coefficients, plus isentropic quasi-1D relations for tunnel contraction and
diffuser sizing.

Both corrections lose validity as the local Mach number approaches unity;
the implementations warn above a local Mach of roughly 0.7 and refuse to
extrapolate into the transonic range.
"""
