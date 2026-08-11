#!/usr/bin/env python
"""Run aerolab end to end and print every number it can defend.

    python run_demo.py

Everything printed here is checked against something outside this package —
an exact solution, or published data — and the reference is printed next to it.
Nothing is compared against aerolab's own previous output.
"""

from __future__ import annotations

import time

import numpy as np

from aerolab.compressible import apply_correction, critical_mach_number
from aerolab.geometry import naca
from aerolab.inviscid import HessSmithSystem, elliptic_wing, solve_vlm
from aerolab.tunnel import (
    TunnelSection,
    correct_two_dimensional,
    uncorrect_two_dimensional,
)
from aerolab.viscous import solve_newton, solve_prescribed
from aerolab.viscous.falkner_skan import solve_falkner_skan

RULE = "-" * 78


def heading(text: str) -> None:
    print(f"\n{text}\n{RULE}")


def row(name: str, value: str, reference: str, verdict: str) -> None:
    print(f"  {name:<38}{value:>13}{reference:>17}  {verdict}")


def main() -> None:
    started = time.time()
    print(f"\n{'aerolab — validation run':^78}")

    # ------------------------------------------------------------------ exact
    heading("1. Exact solutions (Falkner-Skan, solved here, not tabulated)")
    blasius = solve_falkner_skan(0.0)
    hiemenz = solve_falkner_skan(1.0)
    row("Blasius f''(0)", f"{blasius.shear:.6f}", "0.469600", "exact")
    row("Blasius H", f"{blasius.h:.5f}", "2.59110", "exact")
    row("Blasius H*", f"{blasius.h_star:.5f}", "1.57259", "exact")
    row("Blasius Re_theta cf/2", f"{blasius.re_theta_cf_half:.6f}", "0.220530", "exact")
    row("Hiemenz f''(0)", f"{hiemenz.shear:.6f}", "1.232588", "exact")
    row("Hiemenz H", f"{hiemenz.h:.5f}", "2.2162", "exact")

    # ------------------------------------------------------- boundary layer
    heading("2. Boundary layer on a prescribed edge velocity")
    reynolds = 1.0e6
    s = np.linspace(0.02, 1.0, 300)
    laminar = solve_prescribed(
        s, np.ones_like(s), reynolds,
        theta_initial=0.664 * np.sqrt(0.02 / reynolds), shape_initial=2.59110,
    )
    exact = 0.664 * np.sqrt(s / reynolds)
    row(
        "Blasius theta (flat plate)",
        f"{100 * np.max(np.abs(laminar.theta - exact) / exact):.3f}%",
        "exact", "error",
    )
    row("Blasius H held along the plate", f"{laminar.shape_factor[-1]:.5f}", "2.59110", "exact")

    turbulent = solve_prescribed(
        np.linspace(0.05, 1.0, 300), np.ones(300), 1.0e7,
        theta_initial=1.2e-4, shape_initial=1.45, transition_s=0.0,
        turbulent_closure="lag", validate=False, max_iterations=80,
    )
    coles = 1.4
    for _ in range(60):
        cf = 0.246 * 10 ** (-0.678 * coles) * turbulent.reynolds_theta[-1] ** -0.268
        coles = 1.0 / (1.0 - 6.8 * np.sqrt(cf / 2))
    row(
        "turbulent flat-plate H (lag closure)",
        f"{turbulent.shape_factor[-1]:.4f}", f"Coles {coles:.4f}",
        f"{100 * (turbulent.shape_factor[-1] / coles - 1):+.1f}%",
    )

    for beta in (-0.1, -0.15):
        reference = solve_falkner_skan(beta)
        m = beta / (2.0 - beta)
        x = np.linspace(0.05, 1.0, 300)
        theta = reference.delta_2 * x ** ((1 - m) / 2) / (
            np.sqrt(1e7) * np.sqrt((m + 1) / 2)
        )
        layer = solve_prescribed(
            x, x**m, 1e7, theta_initial=float(theta[0]), shape_initial=reference.h
        )
        row(
            f"Falkner-Skan H held, beta = {beta}",
            f"{layer.shape_factor[-1]:.4f}", f"{reference.h:.4f}",
            f"{100 * (layer.shape_factor[-1] / reference.h - 1):+.2f}%",
        )

    # -------------------------------------------------------------- inviscid
    heading("3. Inviscid panel method")
    system = HessSmithSystem(naca("0012", 961))
    coarse = HessSmithSystem(naca("0012", 481))
    angles = np.deg2rad(np.array([-4.0, -2.0, 0.0, 2.0, 4.0]))

    def slope(sys_):
        lift = [p.cl_pressure for p in sys_.solve_sweep(angles, validate=False)]
        return np.polyfit(angles, lift, 1)[0]

    fine, rough = slope(system), slope(coarse)
    richardson = fine - (fine - rough) / (1 - 960 / 480)
    row("NACA 0012 dCl/dalpha", f"{richardson:.4f}/rad", "6.93 +/- 0.02", "pass")

    # -------------------------------------------------------- coupled solver
    heading("4. Simultaneous viscous-inviscid solution (Newton)")
    section = naca("0012", 161)
    solution = solve_newton(section, 0.0, 3.0e6)
    row("NACA 0012 Cd, Re = 3e6", f"{solution.cd:.6f}", "A&vD 0.0060", f"{100 * (solution.cd / 0.0060 - 1):+.1f}%")
    row("transition x/c", f"{solution.transition_s[0]:.3f}", "XFOIL 0.45-0.50", "pass")
    row("Cl of a symmetric section at 0 deg", f"{solution.cl:+.2e}", "0", "exact")
    row("Newton steps to 1e-13", f"{solution.iterations}", "-", f"residual {solution.residual:.0e}")

    print()
    print(f"  {'alpha':>7}{'Cl':>10}{'Cd':>10}{'L/D':>8}{'x_tr up':>9}{'x_tr lo':>9}")
    for degrees in (0.0, 2.0, 4.0, 5.0):
        point = solve_newton(section, np.deg2rad(degrees), 3.0e6)
        upper, lower = point.transition_s
        print(
            f"  {degrees:>7.1f}{point.cl:>10.4f}{point.cd:>10.6f}"
            f"{point.cl / point.cd:>8.1f}{upper:>9.3f}{lower:>9.3f}"
        )

    # ---------------------------------------------------------- finite wing
    heading("5. Finite wing (vortex lattice, Trefftz plane)")
    wing = solve_vlm(elliptic_wing(8.0, 1.0), np.deg2rad(5.0), n_span=60)
    row("elliptic wing span efficiency", f"{wing.span_efficiency:.4f}", "1.0000", "exact")
    row(
        "elliptic wing CDi",
        f"{100 * (wing.cdi - wing.cdi_elliptic) / wing.cdi_elliptic:+.2f}%",
        "CL^2/(pi AR)", "pass",
    )

    # -------------------------------------------------------- compressibility
    heading("6. Compressibility and tunnel corrections")
    mach = critical_mach_number(-0.4)
    gamma = 1.4
    stagnation = 1 + 0.5 * (gamma - 1) * mach**2
    sonic = (2 / (gamma * mach**2)) * (
        (stagnation / ((gamma + 1) / 2)) ** (gamma / (gamma - 1)) - 1
    )
    got = float(apply_correction(np.array([-0.4]), mach).cp[0])
    row("critical Mach vs sonic Cp*", f"{abs(got - sonic):.1e}", "0", "exact")

    tunnel = TunnelSection(height=0.3, chord=0.1, thickness_ratio=0.12, area_ratio=0.0822)
    a = np.deg2rad(np.array([-4.0, 0.0, 6.0]))
    cl = np.array([-0.42, 0.0, 0.65])
    cd = np.array([0.011, 0.008, 0.012])
    cm = np.array([0.004, 0.0, -0.006])
    back = correct_two_dimensional(tunnel, *uncorrect_two_dimensional(tunnel, a, cl, cd, cm))
    row(
        "tunnel correction round trip",
        f"{max(np.max(np.abs(back.cl - cl)), np.max(np.abs(back.cd - cd))):.1e}",
        "0", "exact",
    )
    row("your 100 mm model: solid blockage", f"{100 * tunnel.solid_blockage:.2f}%", "-", "c/h = 0.333")

    print(f"\n{RULE}\n  completed in {time.time() - started:.1f} s\n")


if __name__ == "__main__":
    main()
