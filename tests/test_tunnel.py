"""Tests for wind-tunnel wall corrections and the experimental harness.

The strongest check available here is a **round trip**. Absolute correction
magnitudes depend on coefficients taken from the literature, but the algebra can
be verified independently: synthesise what a tunnel would measure from a known
free-air polar, then run that synthetic data through the correction chain and
require the original back. Any sign slip, transposed term or mismatched
convention breaks it, and it needs no external reference to be trusted.

Directions are asserted explicitly. Every blockage correction must *reduce* a
coefficient, because the model saw a higher dynamic pressure than the reference
probe recorded; the angle correction must *increase* the angle. Both are silent
if reversed, which is precisely why they are tested rather than commented.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.polar import compute_polar
from aerolab.tunnel import (
    TunnelSection,
    compare_with_polar,
    correct_two_dimensional,
    read_measurements,
    sigma,
    solid_blockage_factor,
    uncorrect_two_dimensional,
    write_template,
)

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def section() -> TunnelSection:
    return TunnelSection(
        height=0.30, chord=0.10, thickness_ratio=0.12,
        area_ratio=0.0822, pressure_gradient=-0.02,
    )


@pytest.fixture(scope="module")
def free_air():
    return compute_polar(naca("0012", 201), np.arange(-6.0, 9.0, 1.5), 2e5)


class TestGeometryParameter:
    def test_matches_the_closed_form(self) -> None:
        assert sigma(0.1, 0.3) == pytest.approx(np.pi**2 / 48.0 * (1 / 3) ** 2)

    def test_scales_with_the_square_of_chord_to_height(self) -> None:
        assert sigma(0.2, 1.0) / sigma(0.1, 1.0) == pytest.approx(4.0, rel=1e-12)

    def test_vanishes_for_a_small_model(self) -> None:
        assert sigma(0.001, 1.0) < 1e-6

    def test_an_oversized_model_is_refused(self) -> None:
        """Past c/h = 0.4 the corrections exceed 10% and the theory is spent."""
        with pytest.raises(ValidityRangeError, match="small-perturbation"):
            sigma(0.5, 1.0)

    @pytest.mark.parametrize("bad", [(0.0, 1.0), (0.1, 0.0), (0.1, -1.0)])
    def test_non_positive_dimensions_are_refused(self, bad) -> None:
        with pytest.raises(ValidityRangeError):
            sigma(*bad)

    def test_shape_factor_scales_with_thickness(self) -> None:
        assert solid_blockage_factor(0.24) == pytest.approx(
            2.0 * solid_blockage_factor(0.12)
        )

    def test_shape_factor_matches_the_quoted_value_at_twelve_percent(self) -> None:
        assert solid_blockage_factor(0.12) == pytest.approx(0.40, abs=0.005)


class TestCorrectionDirections:
    """Every sign, asserted. A reversed correction is otherwise invisible."""

    def test_blockage_reduces_lift(self, section) -> None:
        result = correct_two_dimensional(
            section, np.array([0.1]), np.array([0.6]), np.array([0.01]),
            np.array([-0.01]),
        )
        assert result.cl[0] < 0.6

    def test_blockage_reduces_drag(self, section) -> None:
        result = correct_two_dimensional(
            section, np.array([0.1]), np.array([0.6]), np.array([0.01]),
            np.array([0.0]),
        )
        assert result.cd[0] < 0.01

    def test_streamline_curvature_increases_the_angle(self, section) -> None:
        """Walls suppress curvature, so the model behaved as if at a higher angle."""
        result = correct_two_dimensional(
            section, np.array([0.1]), np.array([0.6]), np.array([0.01]),
            np.array([0.0]),
        )
        assert result.alpha[0] > 0.1

    def test_the_angle_correction_follows_the_lift(self, section) -> None:
        result = correct_two_dimensional(
            section, np.zeros(3), np.array([-0.5, 0.0, 0.5]), np.full(3, 0.01),
            np.zeros(3),
        )
        assert result.alpha_shift[0] < 0.0
        assert result.alpha_shift[1] == pytest.approx(0.0, abs=1e-15)
        assert result.alpha_shift[2] > 0.0

    def test_corrections_vanish_for_a_vanishingly_small_model(self) -> None:
        tiny = TunnelSection(height=100.0, chord=0.01, thickness_ratio=0.12)
        alpha, cl, cd, cm = (
            np.array([0.1]), np.array([0.6]), np.array([0.01]), np.array([-0.01])
        )
        result = correct_two_dimensional(tiny, alpha, cl, cd, cm)
        # Streamline curvature scales with sigma, so with (c/h)^2, and is gone
        # at 1e-8. Wake blockage scales only with c/h and so is the last term
        # standing: at c/h = 1e-4 it still moves lift and drag by about 1e-6.
        assert result.alpha[0] == pytest.approx(alpha[0], rel=1e-8)
        assert result.cl[0] == pytest.approx(cl[0], rel=1e-5)
        assert result.cd[0] == pytest.approx(cd[0], rel=1e-5)

    def test_corrections_grow_with_model_size(self) -> None:
        deltas = []
        for chord in (0.05, 0.10, 0.15):
            wall = TunnelSection(height=0.4, chord=chord, thickness_ratio=0.12)
            result = correct_two_dimensional(
                wall, np.array([0.1]), np.array([0.6]), np.array([0.01]),
                np.array([0.0]),
            )
            deltas.append(0.6 - result.cl[0])
        assert all(a < b for a, b in zip(deltas, deltas[1:]))

    def test_wake_blockage_grows_with_drag(self, section) -> None:
        low = section.wake_blockage(0.005)
        high = section.wake_blockage(0.05)
        assert float(high) > float(low)
        assert float(high) == pytest.approx(10.0 * float(low))

    def test_buoyancy_is_subtracted_not_scaled(self) -> None:
        """It is a force free air would not apply at all, not a mis-reference."""
        with_gradient = TunnelSection(
            height=0.3, chord=0.1, thickness_ratio=0.12,
            area_ratio=0.0822, pressure_gradient=-0.05,
        )
        without = TunnelSection(
            height=0.3, chord=0.1, thickness_ratio=0.12, area_ratio=0.0822,
        )
        arguments = (np.array([0.0]), np.array([0.0]), np.array([0.01]),
                     np.array([0.0]))
        difference = (
            correct_two_dimensional(with_gradient, *arguments).cd[0]
            - correct_two_dimensional(without, *arguments).cd[0]
        )
        assert difference == pytest.approx(
            with_gradient.area_ratio * with_gradient.pressure_gradient, abs=1e-12
        )

    def test_mismatched_input_lengths_are_refused(self, section) -> None:
        with pytest.raises(ValidityRangeError, match="same shape"):
            correct_two_dimensional(
                section, np.zeros(3), np.zeros(2), np.zeros(3), np.zeros(3)
            )


class TestRoundTrip:
    """Synthesise a tunnel run from known free-air data, then recover it."""

    def test_the_inverse_is_exact(self, section) -> None:
        alpha = np.deg2rad(np.array([-4.0, 0.0, 6.0, 10.0]))
        cl = np.array([-0.42, 0.0, 0.65, 1.05])
        cd = np.array([0.011, 0.008, 0.012, 0.020])
        cm = np.array([0.004, 0.0, -0.006, -0.010])

        measured = uncorrect_two_dimensional(section, alpha, cl, cd, cm)
        recovered = correct_two_dimensional(section, *measured)

        assert np.allclose(recovered.alpha, alpha, atol=1e-12)
        assert np.allclose(recovered.cl, cl, atol=1e-12)
        assert np.allclose(recovered.cd, cd, atol=1e-12)
        assert np.allclose(recovered.cm, cm, atol=1e-12)

    def test_the_synthetic_measurement_differs_from_free_air(self, section) -> None:
        """If it did not, the round trip would be proving nothing."""
        alpha = np.deg2rad(np.array([6.0]))
        cl, cd, cm = np.array([0.65]), np.array([0.012]), np.array([-0.006])
        measured = uncorrect_two_dimensional(section, alpha, cl, cd, cm)
        assert abs(measured[1][0] - cl[0]) > 0.01
        assert measured[1][0] > cl[0]

    def test_a_whole_polar_survives_the_round_trip(self, section, free_air) -> None:
        usable = free_air.converged
        measured = uncorrect_two_dimensional(
            section, free_air.alpha[usable], free_air.cl[usable],
            free_air.cd[usable], free_air.cm[usable],
        )
        recovered = correct_two_dimensional(section, *measured)
        assert np.allclose(recovered.cl, free_air.cl[usable], atol=1e-12)
        assert np.allclose(recovered.cd, free_air.cd[usable], atol=1e-12)


class TestMeasurementFiles:
    def test_a_template_round_trips(self, tmp_path) -> None:
        path = write_template(tmp_path / "run.csv", np.array([-2.0, 0.0, 2.0]), 2e5)
        assert path.exists()
        text = path.read_text()
        assert "alpha_deg" in text
        assert "reynolds = 2e+05" in text or "reynolds = 200000" in text

    def test_reading_a_populated_file(self, tmp_path) -> None:
        path = tmp_path / "run.csv"
        path.write_text(
            "# reynolds = 150000\n"
            "alpha_deg,cl,cd,cm,cl_uncertainty\n"
            "-2.0,-0.18,0.0135,0.001,0.02\n"
            "0.0,0.02,0.0121,0.000,0.02\n"
            "4.0,0.44,0.0148,-0.003,0.02\n"
        )
        data = read_measurements(path)
        assert len(data) == 3
        assert data.reynolds == pytest.approx(150000.0)
        assert np.allclose(data.alpha_deg, [-2.0, 0.0, 4.0])
        assert data.has_uncertainty

    def test_angles_are_read_as_degrees(self, tmp_path) -> None:
        path = tmp_path / "run.csv"
        path.write_text("alpha_deg,cl,cd\n90.0,0.1,0.01\n")
        assert read_measurements(path).alpha[0] == pytest.approx(np.pi / 2.0)

    def test_a_missing_column_is_refused(self, tmp_path) -> None:
        path = tmp_path / "run.csv"
        path.write_text("alpha_deg,cl\n0.0,0.1\n")
        with pytest.raises(ValidityRangeError, match="missing required column"):
            read_measurements(path)

    def test_an_unreadable_value_is_refused_not_skipped(self, tmp_path) -> None:
        """A silently dropped row is worse than a refused file."""
        path = tmp_path / "run.csv"
        path.write_text("alpha_deg,cl,cd\n0.0,0.1,0.01\n2.0,oops,0.01\n")
        with pytest.raises(ValidityRangeError, match="could not read"):
            read_measurements(path)

    def test_an_empty_file_is_refused(self, tmp_path) -> None:
        path = tmp_path / "run.csv"
        path.write_text("# reynolds = 1e5\n")
        with pytest.raises(ValidityRangeError, match="no data rows"):
            read_measurements(path)

    def test_a_missing_file_names_itself(self, tmp_path) -> None:
        with pytest.raises(ValidityRangeError, match="could not read"):
            read_measurements(tmp_path / "absent.csv")


class TestComparison:
    """The end-to-end harness."""

    def _synthetic_run(self, tmp_path, section, polar, bias=0.0, noise=0.0, seed=0):
        usable = polar.converged
        measured = uncorrect_two_dimensional(
            section, polar.alpha[usable], polar.cl[usable] + bias,
            polar.cd[usable], polar.cm[usable],
        )
        rng = np.random.default_rng(seed)
        cl = measured[1] + noise * rng.standard_normal(measured[1].size)
        path = tmp_path / "run.csv"
        lines = ["# reynolds = 2e5", "alpha_deg,cl,cd,cm,cl_uncertainty"]
        for i in range(measured[0].size):
            lines.append(
                f"{np.rad2deg(measured[0][i]):.5f},{cl[i]:.6f},"
                f"{measured[2][i]:.7f},{measured[3][i]:.6f},0.05"
            )
        path.write_text("\n".join(lines) + "\n")
        return read_measurements(path)

    def test_a_perfect_run_shows_no_deviation(self, tmp_path, section, free_air) -> None:
        """The whole chain, exercised end to end: correct, interpolate, compare."""
        data = self._synthetic_run(tmp_path, section, free_air)
        result = compare_with_polar(data, section, free_air)
        # The floor here is the six-decimal precision the synthetic CSV is
        # written with, not the correction chain, which round-trips to 1e-12.
        assert abs(result.lift["bias"]) < 1e-6
        assert result.lift["rms"] < 1e-6
        assert abs(result.drag["bias"]) < 1e-7

    def test_a_constant_offset_appears_as_bias_not_scatter(
        self, tmp_path, section, free_air
    ) -> None:
        data = self._synthetic_run(tmp_path, section, free_air, bias=0.05)
        result = compare_with_polar(data, section, free_air)
        assert result.lift["bias"] == pytest.approx(-0.05, abs=0.005)
        assert result.lift["scatter"] < 0.005

    def test_random_error_appears_as_scatter_not_bias(
        self, tmp_path, section, free_air
    ) -> None:
        """Separating these is the point of reporting both."""
        data = self._synthetic_run(tmp_path, section, free_air, noise=0.03, seed=3)
        result = compare_with_polar(data, section, free_air)
        assert abs(result.lift["bias"]) < 0.02
        assert result.lift["scatter"] > 0.01

    def test_uncertainty_coverage_is_reported(self, tmp_path, section, free_air) -> None:
        data = self._synthetic_run(tmp_path, section, free_air, noise=0.01, seed=1)
        result = compare_with_polar(data, section, free_air)
        assert 0.0 <= result.within_uncertainty <= 1.0

    def test_coverage_is_nan_without_uncertainties(self, tmp_path, section, free_air) -> None:
        path = tmp_path / "bare.csv"
        path.write_text("alpha_deg,cl,cd\n0.0,0.02,0.012\n2.0,0.24,0.013\n")
        result = compare_with_polar(read_measurements(path), section, free_air)
        assert np.isnan(result.within_uncertainty)

    def test_no_overlap_is_refused_with_both_ranges_named(
        self, tmp_path, section, free_air
    ) -> None:
        path = tmp_path / "far.csv"
        path.write_text("alpha_deg,cl,cd\n40.0,1.2,0.3\n45.0,1.1,0.4\n")
        with pytest.raises(ValidityRangeError, match="no overlap"):
            compare_with_polar(read_measurements(path), section, free_air)

    def test_the_report_names_every_quantity(self, tmp_path, section, free_air) -> None:
        data = self._synthetic_run(tmp_path, section, free_air, noise=0.01)
        text = compare_with_polar(data, section, free_air).report()
        for label in ("Cl", "Cd", "Cm", "bias", "rms", "scatter"):
            assert label in text
