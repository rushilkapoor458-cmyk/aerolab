"""PDF report generation.

Produces a self-contained document for one section at one condition: geometry
and its measured properties, pressure distributions, the lift curve and drag
polar, where transition and separation sit against incidence, and — last — the
assumptions and limitations under which every preceding number was computed.

That last page is pulled from ``NOTES.md`` at generation time rather than
written here. A report whose caveats are transcribed by hand drifts away from
the code within a phase or two; one that reads them from the file cannot. If
``NOTES.md`` cannot be found the report says so on the page instead of quietly
omitting it, because a missing caveats page is worse than an obviously broken
one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from aerolab.geometry.airfoil import Airfoil
from aerolab.inviscid.hess_smith import HessSmithSystem
from aerolab.polar import Polar

__all__ = ["ReportSpec", "find_notes", "extract_notes", "write_report"]

#: Phases whose notes are quoted. Sections of NOTES.md outside these are
#: skipped, so a report does not carry caveats about machinery it never used.
QUOTED_PHASES = ("Phase 1", "Phase 2", "Phase 3", "Phase 5")

#: Pattern matching a NOTES.md assumption or limitation bullet.
_NOTE_PATTERN = re.compile(r"^- \*\*([ACDLV]\d+\.\d+) — (.+?)\*\*", re.MULTILINE)


@dataclass(frozen=True)
class ReportSpec:
    """What to put in a report.

    Attributes
    ----------
    airfoil : Airfoil
        Section studied.
    polar : Polar
        Sweep to plot.
    cp_angles_deg : tuple of float
        Angles at which to draw pressure distributions.
    title : str
        Document title.
    """

    airfoil: Airfoil
    polar: Polar
    cp_angles_deg: tuple[float, ...] = (0.0, 5.0, 10.0)
    title: str = "aerolab section report"


def find_notes(start: Path | None = None) -> Path | None:
    """Locate ``NOTES.md`` by walking up from the package.

    Parameters
    ----------
    start : Path, optional
        Directory to start from; defaults to this module's location.

    Returns
    -------
    Path or None
        The file, or None if it is not above the package. An installed
        (non-editable) copy of the package will not have it, which is a real
        situation and is reported rather than treated as an error.
    """
    here = (start or Path(__file__).resolve().parent)
    for directory in [here, *here.parents]:
        candidate = directory / "NOTES.md"
        if candidate.is_file():
            return candidate
    return None


def extract_notes(
    path: Path, phases: tuple[str, ...] = QUOTED_PHASES
) -> list[tuple[str, str]]:
    """Pull the assumption and limitation headings out of ``NOTES.md``.

    Parameters
    ----------
    path : Path
        The notes file.
    phases : tuple of str, optional
        Phase headings to include.

    Returns
    -------
    list of (str, str)
        ``(tag, heading)`` pairs such as ``("A3.2", "Laminar separation at ...")``,
        in file order.

    Notes
    -----
    Only the **bold heading** of each bullet is taken, not its body. A report
    page has room for the claim, not the argument; the argument stays in
    ``NOTES.md``, which the report names so it can be followed up.
    """
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    collected: list[tuple[str, str]] = []
    for section in sections:
        if not any(section.startswith(phase) for phase in phases):
            continue
        for tag, heading in _NOTE_PATTERN.findall(section):
            clean = re.sub(r"[`*]", "", heading).strip().rstrip(".")
            collected.append((tag, clean))
    return collected


def _page_summary(fig, spec: ReportSpec) -> None:
    """Title page: what was run, and the headline numbers."""
    polar = spec.polar
    fig.text(0.5, 0.90, spec.title, ha="center", size=20, weight="bold")
    fig.text(0.5, 0.855, polar.name, ha="center", size=15)
    fig.text(
        0.5, 0.825,
        f"generated {date.today().isoformat()} by aerolab",
        ha="center", size=9, color="0.4",
    )

    slope = polar.lift_slope
    zero_lift = np.rad2deg(polar.zero_lift_angle)
    ratio, ratio_alpha = polar.best_lift_to_drag
    rows = [
        ("Reynolds number", f"{polar.reynolds:.3g}"),
        ("Mach number", f"{polar.mach:.3f}"),
        ("transition criterion", f"{polar.method}  (N_crit = {polar.n_crit:g})"),
        ("compressibility", polar.correction),
        ("viscous-inviscid coupling", "on" if polar.coupled else "off (uncoupled)"),
        ("", ""),
        ("lift-curve slope", f"{slope:.4f} /rad   ({np.deg2rad(1) * slope:.4f} /deg)"),
        ("zero-lift angle", f"{zero_lift:+.3f} deg"),
        ("minimum drag", f"{polar.cd_min:.5f}"),
        ("best lift-to-drag", f"{ratio:.1f} at {np.rad2deg(ratio_alpha):+.2f} deg"),
        ("highest lift (unflagged only)", f"{polar.cl_max:.4f}"),
        ("critical Mach number", f"{polar.critical_mach:.4f}"),
        ("", ""),
        ("points computed", f"{len(polar)}"),
        ("points flagged", f"{int(np.sum(~polar.converged))}"),
    ]
    y = 0.72
    for label, value in rows:
        if label:
            fig.text(0.16, y, label, size=10, color="0.25")
            fig.text(0.56, y, value, size=10, family="monospace")
        y -= 0.030

    if polar.warnings:
        fig.text(0.16, y - 0.02, "Flagged points", size=11, weight="bold")
        y -= 0.055
        for message in polar.warnings[:8]:
            fig.text(0.17, y, f"• {message[:96]}", size=7.5, color="0.3")
            y -= 0.020
        if len(polar.warnings) > 8:
            fig.text(
                0.17, y, f"… and {len(polar.warnings) - 8} more", size=7.5,
                color="0.3",
            )


def _page_geometry(fig, spec: ReportSpec) -> None:
    """Geometry, thickness and camber distributions, measured properties."""
    airfoil = spec.airfoil
    grid = fig.add_gridspec(3, 1, height_ratios=[1.1, 1.0, 0.9], hspace=0.45,
                            left=0.11, right=0.94, top=0.90, bottom=0.07)

    ax = fig.add_subplot(grid[0])
    ax.plot(airfoil.x, airfoil.z, "k-", lw=1.3)
    ax.fill(airfoil.x, airfoil.z, color="0.88")
    ax.set_aspect("equal")
    ax.set_title(f"{airfoil.name} — {airfoil.n_points} points", size=11)
    ax.set_xlabel("x/c")
    ax.grid(alpha=0.3)

    ax = fig.add_subplot(grid[1])
    stations, thickness = airfoil.thickness_distribution(201)
    _, camber = airfoil.camber_distribution(201)
    ax.plot(stations, thickness, label="thickness  $t/c$")
    ax.plot(stations, camber, label="camber  $z_c/c$")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("x/c")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_title("distributions (vertical cuts — see NOTES A1.4)", size=10)

    thickest = airfoil.max_thickness
    cambered = airfoil.max_camber
    lines = [
        f"maximum thickness      {thickest.value:.5f} c  at x/c = {thickest.x:.4f}",
        f"maximum camber         {cambered.value:+.5f} c  at x/c = {cambered.x:.4f}",
        f"leading-edge radius    {airfoil.le_radius:.6f} c",
        f"trailing-edge gap      {airfoil.te_gap:.6f} c",
        f"trailing-edge angle    {np.rad2deg(airfoil.te_included_angle):.3f} deg",
        f"enclosed area          {airfoil.area:.6f} c^2",
        f"perimeter              {airfoil.perimeter:.6f} c",
    ]
    ax = fig.add_subplot(grid[2])
    ax.axis("off")
    ax.set_title("measured geometric properties", size=10, loc="left")
    for index, line in enumerate(lines):
        ax.text(0.02, 0.86 - 0.13 * index, line, family="monospace", size=8.5,
                transform=ax.transAxes)


def _page_pressures(fig, spec: ReportSpec) -> None:
    """Pressure distributions at the requested angles."""
    system = HessSmithSystem(spec.airfoil)
    axes = fig.subplots(1, len(spec.cp_angles_deg), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, alpha_deg in zip(axes, spec.cp_angles_deg):
        solution = system.solve(float(np.deg2rad(alpha_deg)), validate=False)
        x = solution.control_points[:, 0]
        ax.plot(x, solution.cp, lw=1.2)
        ax.axhline(0, color="k", lw=0.5)
        ax.invert_yaxis()
        ax.set_title(
            rf"$\alpha$ = {alpha_deg:g}°" "\n"
            rf"$C_l$ = {solution.cl_pressure:.4f}", size=10
        )
        ax.set_xlabel("x/c")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("$C_p$")
    fig.suptitle(
        f"{spec.airfoil.name} — inviscid surface pressure", size=13, y=0.96
    )


def _page_polar(fig, spec: ReportSpec) -> None:
    """Lift curve, drag polar, moment, and lift-to-drag."""
    polar = spec.polar
    ok = polar.converged
    axes = fig.subplots(2, 2)
    fig.subplots_adjust(hspace=0.33, wspace=0.30, top=0.90, bottom=0.09,
                        left=0.10, right=0.95)

    ax = axes[0, 0]
    ax.plot(polar.alpha_deg[ok], polar.cl[ok], "o-", ms=3, lw=1.2)
    if (~ok).any():
        ax.plot(polar.alpha_deg[~ok], polar.cl[~ok], "x", ms=5, color="C3",
                label="flagged")
        ax.legend(fontsize=8)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel(r"$\alpha$ (deg)")
    ax.set_ylabel("$C_l$")
    ax.set_title("lift curve", size=10)
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    usable = ok & np.isfinite(polar.cd)
    ax.plot(polar.cd[usable], polar.cl[usable], "o-", ms=3, lw=1.2)
    ax.set_xlabel("$C_d$")
    ax.set_ylabel("$C_l$")
    ax.set_title("drag polar", size=10)
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    ax.plot(polar.alpha_deg[ok], polar.cm[ok], "o-", ms=3, lw=1.2, color="C2")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel(r"$\alpha$ (deg)")
    ax.set_ylabel("$C_m$ about c/4  (nose-up +)")
    ax.set_title("pitching moment", size=10)
    ax.grid(alpha=0.3)

    ax = axes[1, 1]
    ratio = np.where(usable, polar.cl / np.where(usable, polar.cd, 1.0), np.nan)
    ax.plot(polar.alpha_deg, ratio, "o-", ms=3, lw=1.2, color="C4")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel(r"$\alpha$ (deg)")
    ax.set_ylabel("$C_l / C_d$")
    ax.set_title("lift-to-drag ratio", size=10)
    ax.grid(alpha=0.3)

    fig.suptitle(
        f"{polar.name} — Re = {polar.reynolds:.3g}, "
        f"M = {polar.mach:.2f}, $N_{{crit}}$ = {polar.n_crit:g}",
        size=13,
    )


def _page_transition(fig, spec: ReportSpec) -> None:
    """Transition and separation stations against incidence."""
    polar = spec.polar
    axes = fig.subplots(2, 1, sharex=True)
    fig.subplots_adjust(hspace=0.22, top=0.90, bottom=0.09, left=0.12, right=0.95)

    ax = axes[0]
    for column, label, colour in (
        ("transition_upper", "upper surface", "C0"),
        ("transition_lower", "lower surface", "C1"),
    ):
        values = np.array([getattr(p, column) for p in polar.points])
        ax.plot(polar.alpha_deg, values, "o-", ms=3, lw=1.2, color=colour,
                label=label)
    ax.set_ylabel("transition  x/c")
    ax.set_ylim(0, 1)
    ax.set_title(
        f"transition ({polar.method}, $N_{{crit}}$ = {polar.n_crit:g})", size=10
    )
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1]
    for column, label, colour in (
        ("separation_upper", "upper surface", "C0"),
        ("separation_lower", "lower surface", "C1"),
    ):
        values = np.array([getattr(p, column) for p in polar.points])
        ax.plot(polar.alpha_deg, values, "o-", ms=3, lw=1.2, color=colour,
                label=label)
    ax.set_xlabel(r"$\alpha$ (deg)")
    ax.set_ylabel("turbulent separation  x/c")
    ax.set_ylim(0, 1.02)
    ax.set_title(
        "separation — points near x/c = 1 are the uncoupled trailing-edge "
        "artefact (NOTES L3.1)", size=9,
    )
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.suptitle(f"{polar.name} — boundary-layer state", size=13)


def _page_assumptions(fig, notes: Path | None) -> None:
    """The caveats page, read from NOTES.md rather than written here."""
    fig.text(0.5, 0.94, "Assumptions and limitations", ha="center", size=16,
             weight="bold")

    if notes is None:
        fig.text(
            0.5, 0.55,
            "NOTES.md could not be found.\n\n"
            "This report was generated from an installed copy of aerolab that\n"
            "does not carry the notes file, so the assumptions under which\n"
            "these numbers were computed are NOT reproduced here.\n\n"
            "Do not use these results without reading NOTES.md from the source\n"
            "repository.",
            ha="center", va="center", size=11, color="C3",
        )
        return

    entries = extract_notes(notes)
    fig.text(
        0.5, 0.905,
        f"read from {notes.name} at generation time — {len(entries)} entries",
        ha="center", size=8.5, color="0.4",
    )

    y = 0.865
    for tag, heading in entries:
        if y < 0.05:
            fig.text(0.5, 0.03, "… continues in NOTES.md", ha="center", size=8,
                     color="0.4")
            break
        colour = "C3" if tag.startswith("L") else "0.15"
        fig.text(0.07, y, tag, size=7.5, family="monospace", color=colour,
                 weight="bold")
        wrapped = heading if len(heading) <= 104 else heading[:101] + "…"
        fig.text(0.135, y, wrapped, size=7.5, color="0.15")
        y -= 0.0175


def write_report(spec: ReportSpec, path: str | Path) -> Path:
    """Write the report.

    Parameters
    ----------
    spec : ReportSpec
        What to include.
    path : str or Path
        Destination PDF.

    Returns
    -------
    Path
        The file written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    notes = find_notes()

    pages = (
        (_page_summary, (spec,)),
        (_page_geometry, (spec,)),
        (_page_pressures, (spec,)),
        (_page_polar, (spec,)),
        (_page_transition, (spec,)),
        (_page_assumptions, (notes,)),
    )

    with PdfPages(out) as pdf:
        for draw, arguments in pages:
            figure = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
            draw(figure, *arguments)
            pdf.savefig(figure)
            plt.close(figure)

        info = pdf.infodict()
        info["Title"] = f"{spec.title} — {spec.polar.name}"
        info["Author"] = "aerolab"
        info["Subject"] = (
            f"Re = {spec.polar.reynolds:.3g}, M = {spec.polar.mach:.2f}"
        )
        info["CreationDate"] = None

    return out
