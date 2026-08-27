"""Panel-independence study for the 2D inviscid solver.

Sweeps panel count and reports how the integrated coefficients converge. This is
the study that establishes how many panels a result actually needs, and it is
run from source rather than transcribed, so the numbers in the report cannot
drift away from the code.

What it measures
----------------
The Hess-Smith method with constant-strength panels is **first order** in panel
count: halving the panel spacing halves the error, rather than quartering it as
a second-order scheme would. The study exploits that by Richardson-extrapolating
each quantity to its converged value, ``2*f(2N) - f(N)``, which is the number a
target should actually be judged against.

It also tracks the gap between the two independent lift calculations
(Kutta-Joukowski versus surface-pressure integration) and the residual pressure
drag, which is zero in exact inviscid flow by D'Alembert's paradox and is
therefore a pure error measure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from aerolab.geometry.naca import naca
from aerolab.inviscid.hess_smith import HessSmithSystem

FloatArray = NDArray[np.float64]

__all__ = ["PanelStudy", "run_panel_study", "plot_panel_study"]

#: Point counts swept by default. Odd, so the leading edge is a shared point;
#: the panel count is one less than each of these.
DEFAULT_POINT_COUNTS: tuple[int, ...] = (61, 81, 121, 161, 201, 241, 321, 401)


@dataclass
class PanelStudy:
    """Results of a panel-count sweep for one section at one angle of attack.

    Attributes
    ----------
    section : str
        NACA designation studied.
    alpha : float
        Angle of attack in **radians**.
    n_panels : ndarray
        Panel counts, ascending.
    cl_pressure, cl_kutta_joukowski : ndarray
        Lift coefficient by each of the two independent routes.
    cm_quarter_chord : ndarray
        Pitching moment coefficient, positive nose-up.
    cd_pressure : ndarray
        Residual pressure drag. Zero in exact inviscid flow, so this is an error
        measure rather than a physical drag.
    lift_disagreement : ndarray
        Relative gap between the two lift calculations.
    condition_number : ndarray
        Condition number of the panel system.
    """

    section: str
    alpha: float
    n_panels: FloatArray
    cl_pressure: FloatArray
    cl_kutta_joukowski: FloatArray
    cm_quarter_chord: FloatArray
    cd_pressure: FloatArray
    lift_disagreement: FloatArray
    condition_number: FloatArray
    _extrapolated: dict[str, float] = field(default_factory=dict)

    @property
    def cl_converged(self) -> float:
        """Richardson-extrapolated lift coefficient from the two finest grids."""
        return self._extrapolated["cl_pressure"]

    @property
    def cm_converged(self) -> float:
        """Richardson-extrapolated pitching moment from the two finest grids."""
        return self._extrapolated["cm_quarter_chord"]

    def convergence_order(self, quantity: str = "cl_pressure") -> float:
        """Observed order of convergence of ``quantity``.

        Assumes ``f(N) = f_inf + C * N**-p`` and solves the three-grid relation

        .. math::
            \\frac{f_1 - f_0}{f_2 - f_1}
            = \\frac{n_1^{-p} - n_0^{-p}}{n_2^{-p} - n_1^{-p}}

        for ``p`` using the last three panel counts. Solving numerically rather
        than assuming a constant refinement ratio matters here: the sweep does
        not refine by exactly two each step, and the usual
        ``log(d1/d2) / log(2)`` shortcut would report a meaningfully wrong order.

        Returns
        -------
        float
            Observed order, or NaN if the differences are too small to resolve
            one (which happens once the sequence has converged to round-off).
        """
        values = np.asarray(getattr(self, quantity), dtype=np.float64)
        if values.size < 3:
            raise ValueError("need at least three panel counts to estimate an order")
        f0, f1, f2 = values[-3:]
        n0, n1, n2 = self.n_panels[-3:]
        d1, d2 = f1 - f0, f2 - f1
        if abs(d1) < 1e-14 or abs(d2) < 1e-14 or d1 * d2 <= 0.0:
            return float("nan")

        target = d1 / d2

        def residual(p: float) -> float:
            return (n1**-p - n0**-p) / (n2**-p - n1**-p) - target

        grid = np.linspace(0.05, 5.0, 400)
        vals = np.array([residual(p) for p in grid])
        sign_change = np.nonzero(np.sign(vals[:-1]) * np.sign(vals[1:]) < 0)[0]
        if sign_change.size == 0:
            return float("nan")
        from scipy.optimize import brentq

        i = int(sign_change[0])
        return float(brentq(residual, grid[i], grid[i + 1]))


def _richardson(
    coarse: float, fine: float, n_coarse: float, n_fine: float
) -> float:
    """Limit of a first-order sequence sampled at two panel counts.

    For ``f(N) = f_inf + C/N`` the limit is
    ``f_fine - (f_fine - f_coarse) / (1 - n_fine/n_coarse)``. This reduces to the
    familiar ``2*f_fine - f_coarse`` only when the count exactly doubles, which
    the default sweep does not do — the last two counts differ by a factor of
    1.25, and using the doubling formula there would under-correct by a factor of
    four.
    """
    ratio = n_fine / n_coarse
    if abs(1.0 - ratio) < 1e-12:
        return fine
    return fine - (fine - coarse) / (1.0 - ratio)


def run_panel_study(
    section: str = "0012",
    alpha_deg: float = 5.0,
    point_counts: tuple[int, ...] = DEFAULT_POINT_COUNTS,
) -> PanelStudy:
    """Sweep panel count for one section.

    Parameters
    ----------
    section : str
        NACA designation.
    alpha_deg : float
        Angle of attack in **degrees** — this is a reporting entry point, and
        degrees are what a test matrix is written in. It is converted to radians
        immediately.
    point_counts : tuple of int
        Odd point counts to sweep. Panel count is one less than each.

    Returns
    -------
    PanelStudy
    """
    alpha = float(np.deg2rad(alpha_deg))
    rows = []
    for n in point_counts:
        system = HessSmithSystem(naca(section, n))
        solution = system.solve(alpha, validate=False)
        rows.append(
            (
                system.n_panels,
                solution.cl_pressure,
                solution.cl_kutta_joukowski,
                solution.cm_quarter_chord,
                solution.cd_pressure,
                solution.lift_disagreement,
                system.condition_number,
            )
        )
    data = np.array(rows, dtype=np.float64)

    study = PanelStudy(
        section=section,
        alpha=alpha,
        n_panels=data[:, 0],
        cl_pressure=data[:, 1],
        cl_kutta_joukowski=data[:, 2],
        cm_quarter_chord=data[:, 3],
        cd_pressure=data[:, 4],
        lift_disagreement=data[:, 5],
        condition_number=data[:, 6],
    )
    n_coarse, n_fine = study.n_panels[-2], study.n_panels[-1]
    study._extrapolated = {
        "cl_pressure": _richardson(
            study.cl_pressure[-2], study.cl_pressure[-1], n_coarse, n_fine
        ),
        "cm_quarter_chord": _richardson(
            study.cm_quarter_chord[-2], study.cm_quarter_chord[-1], n_coarse, n_fine
        ),
    }
    return study


def plot_panel_study(
    studies: list[PanelStudy], path: str | Path, dpi: int = 150
) -> Path:
    """Write the panel-independence convergence figure.

    Parameters
    ----------
    studies : list of PanelStudy
        One per section.
    path : str or Path
        Output image path.
    dpi : int, optional
        Raster resolution.

    Returns
    -------
    Path
        The file written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    ax = axes[0, 0]
    for study, colour in zip(studies, colours):
        ax.plot(study.n_panels, study.cl_pressure, "o-", color=colour,
                label=f"NACA {study.section}", markersize=4)
        ax.axhline(study.cl_converged, color=colour, ls=":", lw=1)
    ax.set_xlabel("panels")
    ax.set_ylabel(r"$C_l$ (pressure integration)")
    ax.set_title("Lift convergence\n(dotted: Richardson-extrapolated limit)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    for study, colour in zip(studies, colours):
        error = np.abs(study.cl_pressure - study.cl_converged)
        ax.loglog(study.n_panels, error, "o-", color=colour,
                  label=f"NACA {study.section}", markersize=4)
    reference = np.array([studies[0].n_panels[0], studies[0].n_panels[-1]])
    scale = np.abs(studies[0].cl_pressure[0] - studies[0].cl_converged)
    ax.loglog(reference, scale * reference[0] / reference, "k--", lw=1,
              label=r"first order, $1/N$")
    ax.set_xlabel("panels")
    ax.set_ylabel(r"$|C_l - C_{l,\infty}|$")
    ax.set_title("Error against the extrapolated limit", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")

    ax = axes[1, 0]
    for study, colour in zip(studies, colours):
        ax.loglog(study.n_panels, 100 * study.lift_disagreement, "o-",
                  color=colour, label=f"NACA {study.section}", markersize=4)
    ax.axhline(0.5, color="crimson", ls="--", lw=1, label="0.5% requirement")
    ax.set_xlabel("panels")
    ax.set_ylabel(r"$|C_{l,KJ} - C_{l,p}|$  (% )")
    ax.set_title("Agreement of the two lift calculations", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")

    ax = axes[1, 1]
    for study, colour in zip(studies, colours):
        ax.loglog(study.n_panels, np.abs(study.cd_pressure), "o-",
                  color=colour, label=f"NACA {study.section}", markersize=4)
    ax.set_xlabel("panels")
    ax.set_ylabel(r"$|C_{d,\mathrm{pressure}}|$")
    ax.set_title("D'Alembert residual\n(exactly zero in inviscid flow)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")

    alpha_deg = np.rad2deg(studies[0].alpha)
    fig.suptitle(
        f"Panel-independence study, Hess-Smith method, "
        f"$\\alpha = {alpha_deg:.0f}^\\circ$",
        fontsize=12,
    )
    fig.tight_layout()

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out
