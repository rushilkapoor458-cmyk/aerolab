"""Command-line interface for aerolab.

The CLI is the one place in the package where angles are expressed in
**degrees**, because that is what every wind-tunnel test matrix and every
published polar uses. Conversion to radians happens on entry to the solver
layer; nothing below this module sees a degree.

Commands
--------
``polar``
    One section, one condition, a sweep of incidence, out to CSV.
``batch``
    Many sections and Reynolds numbers, parallelised across cores.
``report``
    A PDF for one section: geometry, pressures, polar, transition, and the
    assumptions page read from ``NOTES.md``.
``geometry``
    Geometric properties of a section, with no flow solved.
``version``
    Print the version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import numpy as np
import typer

from aerolab import __version__
from aerolab.exceptions import AerolabError
from aerolab.polar import (
    DEFAULT_PANELS,
    PolarRequest,
    batch_polars,
    compute_polar,
    load_airfoil,
    parse_alpha_range,
)
from aerolab.viscous.transition import DEFAULT_N_CRIT

app = typer.Typer(
    name="aerolab",
    help="A 2D/3D subsonic aerodynamics toolkit.",
    add_completion=False,
    no_args_is_help=True,
)

#: Exit code used when a run completes but some points were flagged.
EXIT_FLAGGED = 2


@app.callback()
def main() -> None:
    """Entry point for the `aerolab` command group.

    This callback exists for a structural reason, not a functional one. Typer
    collapses an app holding exactly one command into a single-command CLI,
    which silently drops the subcommand name — `aerolab version` would fail
    until a second command happened to be added. Declaring a callback pins the
    app as a command group from the start, so subcommand names are stable no
    matter how many commands exist.
    """


@app.command()
def version() -> None:
    """Print the installed aerolab version and exit."""
    typer.echo(f"aerolab {__version__}")


@app.command()
def geometry(
    airfoil: Annotated[str, typer.Option("--airfoil", "-a",
                                         help="NACA designation or .dat path")],
    panels: Annotated[int, typer.Option("--panels", help="points on the contour")] = DEFAULT_PANELS,
) -> None:
    """Report the geometric properties of a section, solving no flow."""
    try:
        section = load_airfoil(airfoil, panels)
        thickest = section.max_thickness
        cambered = section.max_camber
        typer.echo(f"{section.name}   ({section.n_points} points)")
        typer.echo(f"  max thickness       {thickest.value:.5f} c at x/c = {thickest.x:.4f}")
        typer.echo(f"  max camber          {cambered.value:+.5f} c at x/c = {cambered.x:.4f}")
        typer.echo(f"  leading-edge radius {section.le_radius:.6f} c")
        typer.echo(f"  trailing-edge gap   {section.te_gap:.6f} c")
        typer.echo(f"  trailing-edge angle {np.rad2deg(section.te_included_angle):.3f} deg")
        typer.echo(f"  area                {section.area:.6f} c^2")
        typer.echo(f"  perimeter           {section.perimeter:.6f} c")
    except AerolabError as error:
        typer.secho(f"error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error


@app.command()
def polar(
    airfoil: Annotated[str, typer.Option("--airfoil", "-a",
                                         help="NACA designation or .dat path")],
    re: Annotated[float, typer.Option("--re", help="Reynolds number based on chord")],
    alpha: Annotated[str, typer.Option("--alpha",
                                       help="degrees, as start:stop:step or a,b,c")] = "-6:16:0.5",
    out: Annotated[Path, typer.Option("--out", "-o", help="CSV destination")] = Path("polar.csv"),
    mach: Annotated[float, typer.Option("--mach", help="freestream Mach number")] = 0.0,
    n_crit: Annotated[float, typer.Option("--n-crit",
                                          help="e^N amplification factor; 9 = free flight, 4-7 = small tunnel")] = DEFAULT_N_CRIT,
    method: Annotated[str, typer.Option("--transition", help="'en' or 'michel'")] = "en",
    correction: Annotated[str, typer.Option("--correction",
                                            help="'karman-tsien', 'prandtl-glauert' or 'none'")] = "karman-tsien",
    panels: Annotated[int, typer.Option("--panels", help="points on the contour")] = DEFAULT_PANELS,
    coupled: Annotated[bool, typer.Option("--coupled/--uncoupled",
                                          help="use the Phase 4 coupling (does not currently converge)")] = False,
) -> None:
    """Sweep angle of attack and write the polar as CSV.

    Exits with status 2 if the run completed but some points were flagged, so a
    script can tell "finished cleanly" from "finished with caveats" without
    parsing the output.
    """
    try:
        angles = parse_alpha_range(alpha)
        section = load_airfoil(airfoil, panels)
        result = compute_polar(
            section, angles, re, mach=mach, n_crit=n_crit,
            method=method, correction=correction, coupled=coupled,
        )
        written = result.to_csv(out)
    except AerolabError as error:
        typer.secho(f"error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error

    flagged = int(np.sum(~result.converged))
    typer.echo(f"{result.name}   Re = {re:.3g}   M = {mach:g}   N_crit = {n_crit:g}")
    typer.echo(f"  {len(result)} angles from {angles[0]:+.2f} to {angles[-1]:+.2f} deg")
    typer.echo(f"  lift slope    {result.lift_slope:.4f} /rad")
    typer.echo(f"  zero lift at  {np.rad2deg(result.zero_lift_angle):+.3f} deg")
    typer.echo(f"  minimum drag  {result.cd_min:.5f}")
    ratio, ratio_alpha = result.best_lift_to_drag
    typer.echo(f"  best L/D      {ratio:.1f} at {np.rad2deg(ratio_alpha):+.2f} deg")
    typer.echo(f"  written to    {written}")

    if flagged:
        typer.secho(
            f"  {flagged} of {len(result)} points flagged:",
            fg=typer.colors.YELLOW, err=True,
        )
        for message in result.warnings[:6]:
            typer.secho(f"    {message}", fg=typer.colors.YELLOW, err=True)
        if len(result.warnings) > 6:
            typer.secho(
                f"    ... and {len(result.warnings) - 6} more",
                fg=typer.colors.YELLOW, err=True,
            )
        raise typer.Exit(EXIT_FLAGGED)


@app.command()
def batch(
    airfoils: Annotated[str, typer.Option("--airfoils",
                                          help="comma-separated designations or paths")],
    re: Annotated[str, typer.Option("--re", help="comma-separated Reynolds numbers")],
    outdir: Annotated[Path, typer.Option("--out", "-o", help="output directory")] = Path("polars"),
    alpha: Annotated[str, typer.Option("--alpha", help="degrees, start:stop:step")] = "-6:16:0.5",
    mach: Annotated[float, typer.Option("--mach")] = 0.0,
    n_crit: Annotated[float, typer.Option("--n-crit")] = DEFAULT_N_CRIT,
    method: Annotated[str, typer.Option("--transition")] = "en",
    panels: Annotated[int, typer.Option("--panels")] = DEFAULT_PANELS,
    workers: Annotated[int, typer.Option("--workers",
                                         help="processes; 0 uses every core")] = 0,
) -> None:
    """Sweep every combination of section and Reynolds number, in parallel.

    Work is split across **polars**, not across angles: a single polar shares one
    factorised panel system between all its angles, and splitting it would throw
    that saving away.
    """
    try:
        angles = tuple(float(a) for a in parse_alpha_range(alpha))
        requests = [
            PolarRequest(
                airfoil=name.strip(), reynolds=float(reynolds),
                alphas_deg=angles, mach=mach, n_crit=n_crit,
                method=method, n_points=panels,
            )
            for name in airfoils.split(",")
            for reynolds in re.split(",")
        ]
    except (AerolabError, ValueError) as error:
        typer.secho(f"error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error

    typer.echo(f"{len(requests)} polars x {len(angles)} angles")
    results = batch_polars(requests, workers=workers or None)

    outdir.mkdir(parents=True, exist_ok=True)
    total_flagged = 0
    for request, result in zip(requests, results):
        destination = outdir / f"{request.label}.csv"
        result.to_csv(destination)
        flagged = int(np.sum(~result.converged))
        total_flagged += flagged
        note = f"  ({flagged} flagged)" if flagged else ""
        typer.echo(
            f"  {destination.name:<34} Cl_max {result.cl_max:6.3f}   "
            f"Cd_min {result.cd_min:.5f}{note}"
        )

    typer.echo(f"written to {outdir}")
    if total_flagged:
        typer.secho(
            f"{total_flagged} points flagged across the batch; see the CSV note "
            "column", fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(EXIT_FLAGGED)


@app.command()
def report(
    airfoil: Annotated[str, typer.Option("--airfoil", "-a")],
    re: Annotated[float, typer.Option("--re", help="Reynolds number based on chord")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("report.pdf"),
    alpha: Annotated[str, typer.Option("--alpha", help="degrees, start:stop:step")] = "-6:16:0.5",
    cp_at: Annotated[str, typer.Option("--cp-at",
                                       help="angles for pressure plots, in degrees")] = "0,5,10",
    mach: Annotated[float, typer.Option("--mach")] = 0.0,
    n_crit: Annotated[float, typer.Option("--n-crit")] = DEFAULT_N_CRIT,
    method: Annotated[str, typer.Option("--transition")] = "en",
    panels: Annotated[int, typer.Option("--panels")] = DEFAULT_PANELS,
) -> None:
    """Write a PDF report: geometry, pressures, polar, transition, assumptions.

    The assumptions page is read from ``NOTES.md`` at generation time, not
    transcribed, so it cannot drift away from the code.
    """
    from aerolab.report import ReportSpec, find_notes, write_report

    try:
        angles = parse_alpha_range(alpha)
        cp_angles = tuple(float(a) for a in parse_alpha_range(cp_at))
        section = load_airfoil(airfoil, panels)
        result = compute_polar(
            section, angles, re, mach=mach, n_crit=n_crit, method=method,
        )
        written = write_report(
            ReportSpec(airfoil=section, polar=result, cp_angles_deg=cp_angles),
            out,
        )
    except AerolabError as error:
        typer.secho(f"error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error

    typer.echo(f"report written to {written}")
    if find_notes() is None:
        typer.secho(
            "warning: NOTES.md was not found, so the assumptions page is a "
            "placeholder. Do not circulate this report.",
            fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(EXIT_FLAGGED)


if __name__ == "__main__":  # pragma: no cover - manual entry point
    app()
