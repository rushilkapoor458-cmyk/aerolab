"""Ingest measured tunnel data, correct it, and compare it with a prediction.

This is the bridge between the two halves of the facility. It reads a CSV off
the balance, applies the wall corrections, interpolates the predicted polar onto
the measured angles, and reports how far apart they are — separating **bias**
(the prediction is consistently high or low) from **scatter** (it is noisy about
the right answer), because those two failures have entirely different causes.

A bias in lift usually means a geometry or angle-datum error. A bias in drag
usually means the transition parameter is wrong for the tunnel. Scatter usually
means the measurement, not the prediction.

Uncertainty
-----------
Measured uncertainties, where the file supplies them, are carried through the
corrections and reported alongside the deviations, so that "the prediction is 8%
low" can be read next to "the measurement is good to 5%" and judged.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from aerolab.exceptions import ValidityRangeError
from aerolab.polar import Polar
from aerolab.tunnel.corrections import TunnelSection, correct_two_dimensional

FloatArray = NDArray[np.float64]

__all__ = [
    "Measurements",
    "Comparison",
    "read_measurements",
    "write_template",
    "compare_with_polar",
]

#: Columns a measurement file must supply.
REQUIRED_COLUMNS = ("alpha_deg", "cl", "cd")

#: Columns that are used when present.
OPTIONAL_COLUMNS = ("cm", "cl_uncertainty", "cd_uncertainty", "cm_uncertainty")


@dataclass(frozen=True)
class Measurements:
    """Tunnel data as measured, before any correction.

    Attributes
    ----------
    alpha : ndarray
        Geometric angle of attack in **radians**, converted on read from the
        file's degrees.
    cl, cd, cm : ndarray
        Measured coefficients on the reference dynamic pressure.
    cl_uncertainty, cd_uncertainty, cm_uncertainty : ndarray
        One-sigma uncertainties, zero where the file did not give them.
    reynolds : float
        Chord Reynolds number of the run, from the file header.
    source : str
        Where the data came from.
    """

    alpha: FloatArray
    cl: FloatArray
    cd: FloatArray
    cm: FloatArray
    cl_uncertainty: FloatArray
    cd_uncertainty: FloatArray
    cm_uncertainty: FloatArray
    reynolds: float = float("nan")
    source: str = "measurements"

    def __len__(self) -> int:
        return int(self.alpha.size)

    @property
    def alpha_deg(self) -> FloatArray:
        """Angles in degrees, for reporting."""
        return np.rad2deg(self.alpha)

    @property
    def has_uncertainty(self) -> bool:
        """Whether any uncertainty column carried real values."""
        return bool(
            np.any(self.cl_uncertainty) or np.any(self.cd_uncertainty)
        )

    def corrected(self, section: TunnelSection):
        """Apply wall corrections, returning a :class:`WallCorrection`."""
        return correct_two_dimensional(section, self.alpha, self.cl, self.cd, self.cm)


def read_measurements(path: str | Path) -> Measurements:
    """Read a measurement CSV.

    Parameters
    ----------
    path : str or Path
        File with a header row naming at least ``alpha_deg``, ``cl`` and ``cd``.
        Lines beginning ``#`` are metadata of the form ``# key = value``;
        ``reynolds`` is picked up from there.

    Returns
    -------
    Measurements

    Raises
    ------
    ValidityRangeError
        If the file is missing a required column, has no rows, or contains a
        value that cannot be read as a number. A silently dropped row is worse
        than a refused file.

    Notes
    -----
    Angles are read in **degrees**, matching how a test matrix is written, and
    converted immediately.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise ValidityRangeError(f"could not read {source}: {error}") from error

    meta: dict[str, str] = {}
    data_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if "=" in stripped:
                key, _, value = stripped[1:].partition("=")
                meta[key.strip().lower()] = value.strip()
            continue
        data_lines.append(line)

    if not data_lines:
        raise ValidityRangeError(f"{source} contains no data rows")

    reader = csv.DictReader(data_lines)
    fields = [f.strip() for f in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in fields]
    if missing:
        raise ValidityRangeError(
            f"{source} is missing required column(s) {missing}. A measurement "
            f"file needs at least {list(REQUIRED_COLUMNS)}; optional columns are "
            f"{list(OPTIONAL_COLUMNS)}."
        )

    rows = list(reader)
    if not rows:
        raise ValidityRangeError(f"{source} has a header but no rows")

    def column(name: str, required: bool) -> FloatArray:
        if name not in fields:
            return np.zeros(len(rows))
        values = []
        for index, row in enumerate(rows, start=1):
            raw = (row.get(name) or "").strip()
            if not raw:
                if required:
                    raise ValidityRangeError(
                        f"{source} row {index}: column {name!r} is empty"
                    )
                values.append(0.0)
                continue
            try:
                values.append(float(raw))
            except ValueError as error:
                raise ValidityRangeError(
                    f"{source} row {index}: could not read {name!r} value "
                    f"{raw!r} as a number"
                ) from error
        return np.array(values, dtype=np.float64)

    return Measurements(
        alpha=np.deg2rad(column("alpha_deg", True)),
        cl=column("cl", True),
        cd=column("cd", True),
        cm=column("cm", False),
        cl_uncertainty=np.abs(column("cl_uncertainty", False)),
        cd_uncertainty=np.abs(column("cd_uncertainty", False)),
        cm_uncertainty=np.abs(column("cm_uncertainty", False)),
        reynolds=float(meta.get("reynolds", "nan")),
        source=str(source),
    )


def write_template(path: str | Path, alphas_deg: FloatArray, reynolds: float) -> Path:
    """Write an empty measurement file for a planned run.

    Parameters
    ----------
    path : str or Path
        Destination.
    alphas_deg : ndarray
        Angles the run will sweep, in degrees.
    reynolds : float
        Intended chord Reynolds number.

    Returns
    -------
    Path
        The file written, with the angle column filled and everything else blank.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        handle.write("# aerolab tunnel measurement sheet\n")
        handle.write(f"# reynolds = {reynolds:.6g}\n")
        handle.write("# alpha_deg is the GEOMETRIC angle set on the model.\n")
        handle.write("# Leave uncertainty columns blank if not estimated.\n")
        writer = csv.writer(handle)
        writer.writerow(
            ["alpha_deg", "cl", "cd", "cm",
             "cl_uncertainty", "cd_uncertainty", "cm_uncertainty"]
        )
        for angle in np.atleast_1d(alphas_deg):
            writer.writerow([f"{float(angle):.2f}", "", "", "", "", "", ""])
    return out


@dataclass(frozen=True)
class Comparison:
    """Measured data against a prediction, on common angles.

    Attributes
    ----------
    alpha : ndarray
        Angles compared, in **radians**.
    measured_cl, measured_cd, measured_cm : ndarray
        Corrected measurements.
    predicted_cl, predicted_cd, predicted_cm : ndarray
        Prediction interpolated onto the same angles.
    cl_uncertainty, cd_uncertainty : ndarray
        Measurement uncertainties carried through.
    """

    alpha: FloatArray
    measured_cl: FloatArray
    measured_cd: FloatArray
    measured_cm: FloatArray
    predicted_cl: FloatArray
    predicted_cd: FloatArray
    predicted_cm: FloatArray
    cl_uncertainty: FloatArray
    cd_uncertainty: FloatArray

    def _statistics(self, measured: FloatArray, predicted: FloatArray) -> dict:
        residual = predicted - measured
        return {
            "bias": float(np.mean(residual)),
            "rms": float(np.sqrt(np.mean(residual**2))),
            "scatter": float(np.std(residual)),
            "max": float(np.max(np.abs(residual))),
        }

    @cached_property
    def lift(self) -> dict:
        """Bias, RMS, scatter and worst deviation in lift."""
        return self._statistics(self.measured_cl, self.predicted_cl)

    @cached_property
    def drag(self) -> dict:
        """The same for drag."""
        return self._statistics(self.measured_cd, self.predicted_cd)

    @cached_property
    def moment(self) -> dict:
        """The same for pitching moment."""
        return self._statistics(self.measured_cm, self.predicted_cm)

    @cached_property
    def within_uncertainty(self) -> float:
        """Fraction of points where the prediction sits inside the error bars.

        Returns NaN if the measurement file carried no uncertainties. A high
        fraction with a large bias is impossible; a low fraction with a small
        bias means the scatter is the problem.
        """
        if not np.any(self.cl_uncertainty):
            return float("nan")
        inside = np.abs(self.predicted_cl - self.measured_cl) <= np.maximum(
            self.cl_uncertainty, 1e-12
        )
        return float(np.mean(inside))

    def report(self) -> str:
        """A short text summary, suitable for a run log."""
        lines = [
            f"{len(self.alpha)} points compared, "
            f"{np.rad2deg(self.alpha[0]):+.2f} to "
            f"{np.rad2deg(self.alpha[-1]):+.2f} deg",
            f"{'':<8}{'bias':>11}{'rms':>11}{'scatter':>11}{'worst':>11}",
        ]
        for name, stats in (("Cl", self.lift), ("Cd", self.drag), ("Cm", self.moment)):
            lines.append(
                f"{name:<8}{stats['bias']:>+11.5f}{stats['rms']:>11.5f}"
                f"{stats['scatter']:>11.5f}{stats['max']:>11.5f}"
            )
        fraction = self.within_uncertainty
        if np.isfinite(fraction):
            lines.append(
                f"prediction inside the measured error bars at "
                f"{100 * fraction:.0f}% of points"
            )
        return "\n".join(lines)


def compare_with_polar(
    measurements: Measurements,
    section: TunnelSection,
    polar: Polar,
) -> Comparison:
    """Correct measurements and compare them with a predicted polar.

    Parameters
    ----------
    measurements : Measurements
        As read from the balance.
    section : TunnelSection
        Test section and model, for the wall corrections.
    polar : Polar
        Prediction. Only its converged points are used, because an unconverged
        point is not a prediction and comparing against one would flatter or
        damn the solver for no reason.

    Returns
    -------
    Comparison

    Raises
    ------
    ValidityRangeError
        If the two do not overlap in angle of attack.

    Notes
    -----
    The prediction is interpolated onto the measured angles rather than the
    other way round: the measurements are the fixed points of the exercise, and
    resampling them would smooth exactly the scatter being quantified.
    """
    corrected = measurements.corrected(section)

    usable = polar.converged
    if int(np.count_nonzero(usable)) < 2:
        raise ValidityRangeError(
            "the predicted polar has fewer than two converged points, so there "
            "is nothing to compare against"
        )
    predicted_alpha = polar.alpha[usable]
    order = np.argsort(predicted_alpha)
    predicted_alpha = predicted_alpha[order]

    inside = (corrected.alpha >= predicted_alpha[0]) & (
        corrected.alpha <= predicted_alpha[-1]
    )
    if not inside.any():
        raise ValidityRangeError(
            f"no overlap in angle of attack: measurements span "
            f"{np.rad2deg(corrected.alpha.min()):+.2f} to "
            f"{np.rad2deg(corrected.alpha.max()):+.2f} deg, the prediction "
            f"{np.rad2deg(predicted_alpha[0]):+.2f} to "
            f"{np.rad2deg(predicted_alpha[-1]):+.2f} deg"
        )

    alpha = corrected.alpha[inside]

    def interpolate(values: FloatArray) -> FloatArray:
        return np.interp(alpha, predicted_alpha, values[usable][order])

    return Comparison(
        alpha=alpha,
        measured_cl=corrected.cl[inside],
        measured_cd=corrected.cd[inside],
        measured_cm=corrected.cm[inside],
        predicted_cl=interpolate(polar.cl),
        predicted_cd=interpolate(polar.cd),
        predicted_cm=interpolate(polar.cm),
        cl_uncertainty=measurements.cl_uncertainty[inside],
        cd_uncertainty=measurements.cd_uncertainty[inside],
    )
