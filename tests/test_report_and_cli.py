"""Tests for the PDF report and the command-line interface.

The report's assumptions page is read from ``NOTES.md`` at generation time, and
that is tested as behaviour rather than treated as an implementation detail: a
report whose caveats were transcribed by hand would drift away from the code
within a phase, and the whole point of reading the file is that it cannot.

The CLI is checked mainly at its boundaries — that degrees stay in degrees, that
a run with flagged points exits differently from a clean one, and that a bad
input produces a message rather than a traceback.
"""

from __future__ import annotations

import re

import numpy as np
import pytest
from typer.testing import CliRunner

from aerolab.cli import EXIT_FLAGGED, app
from aerolab.geometry.naca import naca
from aerolab.polar import Polar, compute_polar
from aerolab.report import ReportSpec, extract_notes, find_notes, write_report

pytestmark = pytest.mark.validation

runner = CliRunner()


@pytest.fixture(scope="module")
def polar() -> Polar:
    return compute_polar(naca("2412", 201), np.arange(-4.0, 8.1, 2.0), 5e5)


class TestNotesExtraction:
    def test_notes_are_found_from_the_package(self) -> None:
        notes = find_notes()
        assert notes is not None
        assert notes.name == "NOTES.md"

    def test_entries_are_tagged_and_non_empty(self) -> None:
        entries = extract_notes(find_notes())
        assert len(entries) > 20
        for tag, heading in entries:
            assert tag[0] in "ACDLV"
            assert "." in tag
            assert heading

    def test_markdown_emphasis_is_stripped(self) -> None:
        """The page is plain text; stray asterisks would be visible."""
        for _, heading in extract_notes(find_notes()):
            assert "**" not in heading
            assert "`" not in heading

    def test_limitations_are_included(self) -> None:
        tags = [tag for tag, _ in extract_notes(find_notes())]
        assert any(tag.startswith("L") for tag in tags)
        assert any(tag.startswith("A") for tag in tags)

    def test_only_the_requested_phases_are_quoted(self) -> None:
        """A report should not carry caveats about machinery it never used."""
        only_geometry = extract_notes(find_notes(), phases=("Phase 1",))
        assert all(tag[1] == "1" for tag, _ in only_geometry)
        assert len(only_geometry) < len(extract_notes(find_notes()))


class TestReport:
    def test_a_pdf_is_written(self, polar: Polar, tmp_path) -> None:
        path = write_report(
            ReportSpec(airfoil=naca("2412", 201), polar=polar), tmp_path / "r.pdf"
        )
        assert path.exists()
        assert path.stat().st_size > 20_000
        assert path.read_bytes()[:4] == b"%PDF"

    def test_it_has_six_pages(self, polar: Polar, tmp_path) -> None:
        path = write_report(
            ReportSpec(airfoil=naca("2412", 201), polar=polar), tmp_path / "r.pdf"
        )
        # "/Type /Pages" is the page tree, not a page; exclude it.
        pages = re.findall(rb"/Type\s*/Page(?![s])", path.read_bytes())
        assert len(pages) == 6

    def test_nested_directories_are_created(self, polar: Polar, tmp_path) -> None:
        path = write_report(
            ReportSpec(airfoil=naca("2412", 201), polar=polar),
            tmp_path / "a" / "b" / "r.pdf",
        )
        assert path.exists()

    def test_a_single_pressure_angle_works(self, polar: Polar, tmp_path) -> None:
        """The pressure page must not assume more than one subplot."""
        path = write_report(
            ReportSpec(
                airfoil=naca("2412", 201), polar=polar, cp_angles_deg=(3.0,)
            ),
            tmp_path / "r.pdf",
        )
        assert path.exists()

    def test_missing_notes_produce_a_visible_placeholder(self, tmp_path) -> None:
        """A missing caveats page is worse than an obviously broken one."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from aerolab.report import _page_assumptions

        figure = plt.figure()
        _page_assumptions(figure, None)
        texts = [t.get_text() for t in figure.texts]
        plt.close(figure)
        assert any("could not be found" in t for t in texts)
        assert any("Do not use these results" in t for t in texts)


class TestCli:
    def test_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "aerolab" in result.stdout

    def test_geometry_reports_measured_properties(self) -> None:
        result = runner.invoke(app, ["geometry", "--airfoil", "naca0012"])
        assert result.exit_code == 0
        assert "max thickness" in result.stdout
        assert "0.12" in result.stdout

    def test_geometry_refuses_a_bad_designation(self) -> None:
        result = runner.invoke(app, ["geometry", "--airfoil", "naca999999"])
        assert result.exit_code == 1
        assert "error:" in result.stderr

    def test_polar_writes_a_csv(self, tmp_path) -> None:
        out = tmp_path / "p.csv"
        result = runner.invoke(
            app,
            ["polar", "--airfoil", "naca0012", "--re", "1e6",
             "--alpha", "-2:2:2", "--out", str(out), "--panels", "201"],
        )
        assert result.exit_code == 0
        assert out.exists()
        assert "lift slope" in result.stdout
        assert len(Polar.from_csv(out)) == 3

    def test_polar_exits_flagged_when_points_are_suspect(self, tmp_path) -> None:
        """A script must be able to tell a clean run from one with caveats."""
        out = tmp_path / "p.csv"
        result = runner.invoke(
            app,
            ["polar", "--airfoil", "naca2412", "--re", "5e5",
             "--alpha", "10:14:2", "--out", str(out), "--panels", "201"],
        )
        assert result.exit_code == EXIT_FLAGGED
        assert out.exists()
        assert "flagged" in result.stderr

    def test_polar_angles_are_degrees_at_the_boundary(self, tmp_path) -> None:
        out = tmp_path / "p.csv"
        runner.invoke(
            app,
            ["polar", "--airfoil", "naca0012", "--re", "1e6",
             "--alpha", "0:8:4", "--out", str(out), "--panels", "201"],
        )
        assert np.allclose(Polar.from_csv(out).alpha_deg, [0.0, 4.0, 8.0])

    def test_polar_refuses_a_bad_angle_specification(self, tmp_path) -> None:
        result = runner.invoke(
            app,
            ["polar", "--airfoil", "naca0012", "--re", "1e6",
             "--alpha", "0:8", "--out", str(tmp_path / "p.csv")],
        )
        assert result.exit_code == 1
        assert "error:" in result.stderr

    def test_batch_writes_one_file_per_case(self, tmp_path) -> None:
        result = runner.invoke(
            app,
            ["batch", "--airfoils", "naca0012,naca2412", "--re", "5e5,1e6",
             "--alpha", "0:4:4", "--out", str(tmp_path), "--panels", "161",
             "--workers", "1"],
        )
        assert result.exit_code in (0, EXIT_FLAGGED)
        assert len(list(tmp_path.glob("*.csv"))) == 4

    def test_batch_filenames_carry_the_conditions(self, tmp_path) -> None:
        runner.invoke(
            app,
            ["batch", "--airfoils", "naca0012", "--re", "5e5",
             "--alpha", "0:0:1", "--out", str(tmp_path), "--panels", "161",
             "--workers", "1"],
        )
        names = [p.name for p in tmp_path.glob("*.csv")]
        assert len(names) == 1
        assert "naca0012" in names[0]
        assert "Re5e05" in names[0]

    def test_report_writes_a_pdf(self, tmp_path) -> None:
        out = tmp_path / "r.pdf"
        result = runner.invoke(
            app,
            ["report", "--airfoil", "naca2412", "--re", "5e5",
             "--alpha", "-2:4:2", "--cp-at", "0,3", "--out", str(out),
             "--panels", "201"],
        )
        assert result.exit_code == 0
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_help_lists_every_command(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("polar", "batch", "report", "geometry", "version"):
            assert command in result.stdout

    def test_n_crit_is_exposed_and_changes_the_answer(self, tmp_path) -> None:
        """The parameter that matters most must be reachable from the CLI."""
        drags = []
        for n_crit in ("4", "11"):
            out = tmp_path / f"p{n_crit}.csv"
            runner.invoke(
                app,
                ["polar", "--airfoil", "naca0012", "--re", "3e6",
                 "--alpha", "0:0:1", "--out", str(out), "--panels", "201",
                 "--n-crit", n_crit],
            )
            drags.append(Polar.from_csv(out).cd[0])
        assert drags[0] > drags[1]
        assert (drags[0] - drags[1]) / drags[1] > 0.15
