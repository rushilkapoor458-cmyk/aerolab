"""Import and export of airfoil coordinate files, with format auto-detection.

Two orderings are in common use and they are not distinguishable from the
numbers alone without looking at the structure of the sequence:

Selig
    One loop. Starts at the trailing edge, runs forward over the **upper**
    surface to the leading edge, then aft over the lower surface back to the
    trailing edge. ``x`` starts near 1, falls to 0, and rises to 1.

Lednicer
    Two groups, each running **leading edge to trailing edge**: upper surface
    first, then lower. ``x`` starts near 0, rises to 1, drops back to 0, and
    rises to 1 again. Often preceded by a line giving the two point counts,
    e.g. ``61. 61.``

Detection is structural rather than heuristic where possible: the two formats
differ in whether the file begins at the trailing edge or the leading edge, and
that is checked against the number of monotone runs in ``x``. When the two
signals disagree the file is rejected rather than guessed at — a mis-detected
ordering produces an airfoil that is upside down or inside out, which the panel
methods will happily solve and quietly get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from aerolab.exceptions import GeometryError
from aerolab.geometry.airfoil import Airfoil

FloatArray = NDArray[np.float64]

DatFormat = Literal["selig", "lednicer"]

__all__ = ["read_dat", "write_dat", "parse_dat", "DatFile"]

#: Values above this in a leading two-number line mean point counts, not
#: coordinates: airfoil x never exceeds about 1 and |z| never exceeds about 0.5.
_COUNT_THRESHOLD = 1.2


@dataclass(frozen=True)
class DatFile:
    """The parsed contents of an airfoil coordinate file.

    Attributes
    ----------
    airfoil : Airfoil
        The contour, converted to Selig order.
    detected_format : {"selig", "lednicer"}
        Ordering detected in the source file.
    name : str
        Name read from the file header, or the filename stem if absent.
    had_count_header : bool
        Whether a Lednicer point-count line was present.
    surfaces_swapped : bool
        True if the file's first group was the *lower* surface, contrary to the
        Lednicer convention, and the two were exchanged on import.
    """

    airfoil: Airfoil
    detected_format: DatFormat
    name: str
    had_count_header: bool = False
    surfaces_swapped: bool = False


def _tokenise(text: str) -> tuple[str | None, list[tuple[float, float]]]:
    """Split file text into an optional name line and a list of number pairs."""
    name: str | None = None
    pairs: list[tuple[float, float]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!", "%")):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) >= 2:
            try:
                pairs.append((float(parts[0]), float(parts[1])))
                continue
            except ValueError:
                pass
        if name is None and not pairs:
            name = line
            continue
        # A non-numeric line after coordinates have started means a multi-element
        # file or a corrupt one; either way it is not a single airfoil.
        raise GeometryError(
            f"unexpected non-numeric line after coordinate data began: {line!r}. "
            "Multi-element and multi-section files are not supported."
        )

    return name, pairs


#: Fractional-span tolerance below which a step in x is ignored when counting
#: monotone runs. The perpendicular-offset construction of a cambered section
#: puts the first point or two of a surface at slightly negative x, giving a
#: real but meaningless wobble of order 1e-4 chords at the nose; genuine
#: structural problems produce steps two orders of magnitude larger.
_RUN_TOL_FRACTION = 1e-3


def _monotone_runs(x: FloatArray, tol: float) -> int:
    """Number of maximal monotone runs in ``x``, ignoring wobbles below ``tol``.

    Filtering can only remove sign changes, never create them, so a small
    tolerance cannot manufacture a spurious pass.
    """
    diffs = np.diff(x)
    significant = diffs[np.abs(diffs) > tol]
    if significant.size == 0:
        return 0
    signs = np.sign(significant)
    return int(1 + np.count_nonzero(np.diff(signs) != 0))


def _detect_format(x: FloatArray, has_count_header: bool) -> tuple[DatFormat, int | None]:
    """Classify the coordinate ordering, or raise if the file is ambiguous.

    Two independent signals must agree:

    1. **Where the listing starts.** Selig begins at the trailing edge,
       Lednicer at the leading edge.
    2. **Whether x jumps backwards.** Lednicer finishes the upper surface at the
       trailing edge and restarts the lower surface at the leading edge, which
       shows up as exactly one step of nearly the full chord in the negative
       direction. A Selig loop walks continuously and never does this.

    Requiring both to agree is what makes this detection rather than guessing.
    A file that satisfies one and not the other is reported, not resolved: a
    mis-detected ordering produces an airfoil that is inside out, and the panel
    methods would solve it without complaint.

    Returns
    -------
    fmt : {"selig", "lednicer"}
        Detected ordering.
    split : int or None
        For Lednicer, the index at which the second surface begins; None for Selig.
    """
    x_min, x_max = float(np.min(x)), float(np.max(x))
    span = x_max - x_min
    if span <= 0.0:
        raise GeometryError("all x coordinates are identical; this is not an airfoil")
    tol = _RUN_TOL_FRACTION * span

    starts_at_te = abs(x[0] - x_max) < abs(x[0] - x_min)
    backward = np.nonzero(np.diff(x) < -0.5 * span)[0]

    if starts_at_te and backward.size == 0:
        detected: DatFormat = "selig"
        split: int | None = None
    elif not starts_at_te and backward.size == 1:
        detected = "lednicer"
        split = int(backward[0]) + 1
    else:
        raise GeometryError(
            "could not identify the coordinate ordering: the listing starts at "
            f"the {'trailing' if starts_at_te else 'leading'} edge "
            f"(x = {x[0]:.4f} in [{x_min:.4f}, {x_max:.4f}]) but contains "
            f"{backward.size} large backward jump(s) in x. Selig ordering starts "
            "at the trailing edge with no jump; Lednicer starts at the leading "
            "edge with exactly one. The file may be multi-element, corrupt, or "
            "may begin part way along a surface."
        )

    if has_count_header and detected != "lednicer":
        raise GeometryError(
            "the file has a Lednicer point-count header but its coordinates are "
            "in Selig order. The file is internally inconsistent."
        )

    # Structural corroboration: a Selig loop is down-then-up, and each Lednicer
    # group runs monotonically from leading edge to trailing edge.
    if detected == "selig":
        runs = _monotone_runs(x, tol)
        if runs != 2:
            raise GeometryError(
                f"expected x to fall then rise exactly once for a Selig loop, "
                f"found {runs} monotone runs. The file may be multi-element, "
                "corrupt, or may begin part way along a surface."
            )
    else:
        assert split is not None
        for label, part in (("first", x[:split]), ("second", x[split:])):
            runs = _monotone_runs(part, tol)
            if runs != 1:
                raise GeometryError(
                    f"the {label} surface group of this Lednicer file is not "
                    f"monotone in x ({runs} runs); each group must run once from "
                    "the leading edge to the trailing edge."
                )

    return detected, split


def _lednicer_to_selig(
    x: FloatArray, z: FloatArray, split: int | None
) -> tuple[FloatArray, FloatArray, bool]:
    """Convert two leading-edge-first surfaces into a single Selig loop."""
    if split is None:
        # The split is where x jumps back towards the leading edge.
        split = int(np.argmin(np.diff(x))) + 1
    if not 2 < split < x.size - 2:
        raise GeometryError(
            f"implausible surface split at index {split} of {x.size} points"
        )

    first_x, first_z = x[:split], z[:split]
    second_x, second_z = x[split:], z[split:]

    # Convention is upper surface first. Verify rather than assume: a file that
    # lists the lower surface first would otherwise import upside down.
    swapped = float(np.mean(first_z)) < float(np.mean(second_z))
    if swapped:
        first_x, first_z, second_x, second_z = second_x, second_z, first_x, first_z

    # Upper surface reversed gives trailing edge -> leading edge; the lower
    # surface then continues leading edge -> trailing edge. Its first point is
    # the shared leading edge, so it is dropped.
    x_selig = np.concatenate([first_x[::-1], second_x[1:]])
    z_selig = np.concatenate([first_z[::-1], second_z[1:]])
    return x_selig, z_selig, swapped


def parse_dat(text: str, name: str | None = None) -> DatFile:
    """Parse airfoil coordinate text, detecting Selig or Lednicer ordering.

    Parameters
    ----------
    text : str
        Contents of a ``.dat`` coordinate file.
    name : str, optional
        Fallback name if the file has no header line.

    Returns
    -------
    DatFile
        The parsed airfoil in Selig order, plus what was detected about the
        source.

    Raises
    ------
    GeometryError
        If the file is empty, malformed, internally inconsistent, or of an
        ordering that cannot be identified with confidence.
    """
    header_name, pairs = _tokenise(text)
    if len(pairs) < 7:
        raise GeometryError(
            f"found only {len(pairs)} coordinate pairs; an airfoil needs at least 7"
        )

    had_count_header = False
    split: int | None = None
    first_x, first_z = pairs[0]
    if first_x > _COUNT_THRESHOLD and first_z > _COUNT_THRESHOLD:
        # Lednicer count header, e.g. "61. 61."
        n_upper, n_lower = int(round(first_x)), int(round(first_z))
        pairs = pairs[1:]
        had_count_header = True
        if n_upper + n_lower != len(pairs):
            raise GeometryError(
                f"the point-count header says {n_upper} + {n_lower} = "
                f"{n_upper + n_lower} points, but the file contains {len(pairs)}"
            )
        split = n_upper

    coords = np.asarray(pairs, dtype=np.float64)
    x, z = coords[:, 0].copy(), coords[:, 1].copy()
    if not np.all(np.isfinite(coords)):
        raise GeometryError("coordinate file contains a non-finite value")

    detected, detected_split = _detect_format(x, had_count_header)
    swapped = False
    if detected == "lednicer":
        if split is not None and detected_split is not None and split != detected_split:
            raise GeometryError(
                f"the point-count header puts the surface split at index {split}, "
                f"but the coordinates jump back to the leading edge at index "
                f"{detected_split}. The header and the data disagree."
            )
        x, z, swapped = _lednicer_to_selig(x, z, split or detected_split)

    resolved_name = header_name or name or "unnamed"
    airfoil = Airfoil.from_points(x, z, name=resolved_name)
    return DatFile(
        airfoil=airfoil,
        detected_format=detected,
        name=resolved_name,
        had_count_header=had_count_header,
        surfaces_swapped=swapped,
    )


def read_dat(path: str | Path) -> DatFile:
    """Read an airfoil coordinate file from disk.

    Parameters
    ----------
    path : str or Path
        Path to a ``.dat`` file in Selig or Lednicer ordering.

    Returns
    -------
    DatFile
        The parsed airfoil in Selig order, plus what was detected about the
        source file.

    Raises
    ------
    GeometryError
        If the file cannot be parsed as a single-element airfoil.

    Notes
    -----
    Coordinates are used as they appear in the file; no normalisation is
    applied. Published files are often a fraction of a percent off unit chord.
    Call :meth:`~aerolab.geometry.airfoil.Airfoil.normalize` if that matters.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GeometryError(f"could not read {p}: {exc}") from exc
    return parse_dat(text, name=p.stem)


def write_dat(
    airfoil: Airfoil,
    path: str | Path,
    *,
    fmt: DatFormat = "selig",
    precision: int = 6,
) -> None:
    """Write an airfoil to a coordinate file.

    Parameters
    ----------
    airfoil : Airfoil
        Contour to write.
    path : str or Path
        Destination file.
    fmt : {"selig", "lednicer"}, optional
        Ordering to write. Default Selig.
    precision : int, optional
        Decimal places for the coordinates. Six is enough that a round trip
        through the file changes the enclosed area by less than one part in
        a million.
    """
    lines = [airfoil.name]
    fmt_str = f"{{:>12.{precision}f}} {{:>12.{precision}f}}"

    if fmt == "selig":
        for xi, zi in zip(airfoil.x, airfoil.z):
            lines.append(fmt_str.format(xi, zi))
    elif fmt == "lednicer":
        (xu, zu), (xl, zl) = airfoil.surfaces()
        lines.append(f"{xu.size:>12.1f} {xl.size:>12.1f}")
        lines.append("")
        for xi, zi in zip(xu, zu):
            lines.append(fmt_str.format(xi, zi))
        lines.append("")
        for xi, zi in zip(xl, zl):
            lines.append(fmt_str.format(xi, zi))
    else:
        raise GeometryError(f"fmt must be 'selig' or 'lednicer', got {fmt!r}")

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
