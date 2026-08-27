"""Tests for polar computation, CSV interchange, and batch runs.

Two things get particular attention. First, that a failed angle is **recorded
as failed** rather than dropped — a polar with a hole in it is far easier to
interpret than one that silently stops where the physics got hard. Second, that
a CSV round trip is lossless to its written precision, since that file is how
results leave the package.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.geometry.naca import naca
from aerolab.polar import (
    Polar,
    PolarRequest,
    batch_polars,
    compute_polar,
    load_airfoil,
    parse_alpha_range,
    run_request,
)

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def polar() -> Polar:
    return compute_polar(naca("2412", 301), np.arange(-4.0, 8.1, 2.0), 5e5)


class TestAlphaParsing:
    def test_range_with_a_negative_start(self) -> None:
        """The minus sign never appears as a separator, so no special casing."""
        angles = parse_alpha_range("-6:16:0.5")
        assert angles[0] == pytest.approx(-6.0)
        assert angles[-1] == pytest.approx(16.0)
        assert len(angles) == 45

    def test_the_stop_value_is_included_when_it_lands_on_a_step(self) -> None:
        assert parse_alpha_range("0:10:2")[-1] == pytest.approx(10.0)

    def test_a_stop_between_steps_is_not_overshot(self) -> None:
        angles = parse_alpha_range("0:9:2")
        assert angles[-1] == pytest.approx(8.0)

    def test_a_single_number(self) -> None:
        assert np.allclose(parse_alpha_range("5"), [5.0])

    def test_an_explicit_list(self) -> None:
        assert np.allclose(parse_alpha_range("-2,0,3.5"), [-2.0, 0.0, 3.5])

    def test_a_descending_range(self) -> None:
        angles = parse_alpha_range("10:0:-2")
        assert angles[0] == pytest.approx(10.0)
        assert angles[-1] == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "spec,message",
        [
            ("", "empty"),
            ("1:2", "start:stop:step"),
            ("0:10:0", "cannot be zero"),
            ("0:10:-1", "points away"),
            ("a:b:c", "could not read"),
        ],
    )
    def test_malformed_specifications_are_refused(self, spec, message) -> None:
        with pytest.raises(ValidityRangeError, match=message):
            parse_alpha_range(spec)


class TestLoadAirfoil:
    def test_a_naca_designation(self) -> None:
        assert load_airfoil("naca2412", 201).n_points == 201

    def test_a_bare_designation(self) -> None:
        assert load_airfoil("0012", 201).n_points == 201

    def test_a_coordinate_file_is_repanelled_to_the_requested_count(
        self, tmp_path
    ) -> None:
        """A polar's resolution must not depend on how finely a file was sampled."""
        from aerolab.geometry.dat_io import write_dat

        path = tmp_path / "section.dat"
        write_dat(naca("4412", 81), path)
        assert load_airfoil(str(path), 201).n_points == 201


class TestPolarComputation:
    def test_shapes_and_ordering(self, polar: Polar) -> None:
        assert len(polar) == 7
        assert np.allclose(polar.alpha_deg, np.arange(-4.0, 8.1, 2.0))
        assert np.allclose(polar.alpha, np.deg2rad(polar.alpha_deg))

    def test_lift_slope_and_zero_lift_angle_match_the_panel_method(
        self, polar: Polar
    ) -> None:
        """The Phase 2 numbers must survive the trip through the polar layer."""
        assert polar.lift_slope == pytest.approx(6.91, abs=0.05)
        assert np.rad2deg(polar.zero_lift_angle) == pytest.approx(-2.14, abs=0.1)

    def test_drag_is_positive_and_of_the_right_order(self, polar: Polar) -> None:
        usable = polar.converged & np.isfinite(polar.cd)
        assert usable.any()
        assert np.all(polar.cd[usable] > 0.0)
        assert 0.004 < polar.cd_min < 0.02

    def test_drag_has_a_minimum_inside_the_sweep(self, polar: Polar) -> None:
        usable = np.isfinite(polar.cd)
        assert polar.cd_min < polar.cd[usable][0]
        assert polar.cd_min < polar.cd[usable][-1]

    def test_best_lift_to_drag_is_at_positive_incidence(self, polar: Polar) -> None:
        ratio, alpha = polar.best_lift_to_drag
        assert ratio > 20.0
        assert alpha > 0.0

    def test_moment_is_nose_down_for_a_cambered_section(self, polar: Polar) -> None:
        assert np.all(polar.cm[polar.converged] < 0.0)

    def test_a_negative_reynolds_number_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="must be positive"):
            compute_polar(naca("0012", 121), np.array([0.0]), -1.0)


class TestFailuresAreRecordedNotDropped:
    """A polar with a hole in it beats one that silently stops."""

    def test_every_requested_angle_appears(self) -> None:
        angles = np.arange(-4.0, 21.0, 4.0)
        result = compute_polar(naca("0012", 201), angles, 3e6)
        assert len(result) == len(angles)
        assert np.allclose(result.alpha_deg, angles)

    def test_separated_points_are_flagged_with_a_reason(self) -> None:
        result = compute_polar(naca("2412", 201), np.array([2.0, 12.0]), 5e5)
        flagged = [p for p in result.points if not p.converged]
        assert flagged
        assert all(p.note for p in flagged)
        assert any("lower bound" in p.note for p in flagged)

    def test_supercritical_points_are_flagged(self) -> None:
        result = compute_polar(
            naca("0012", 201), np.array([0.0]), 3e6, mach=0.75
        )
        point = result.points[0]
        assert not point.converged
        assert point.max_local_mach > 0.7

    def test_warnings_are_collected_for_reporting(self) -> None:
        result = compute_polar(naca("2412", 201), np.array([2.0, 12.0]), 5e5)
        assert result.warnings
        assert all("alpha" in message for message in result.warnings)


class TestCompressibilityInThePolar:
    def test_zero_mach_leaves_lift_unchanged(self) -> None:
        angles = np.array([0.0, 4.0])
        plain = compute_polar(naca("2412", 201), angles, 5e5, mach=0.0)
        assert np.all(plain.converged)
        assert np.all(plain._column("max_local_mach") == 0.0)

    def test_local_mach_rises_with_freestream_mach(self) -> None:
        peaks = [
            compute_polar(
                naca("0012", 201), np.array([2.0]), 3e6, mach=m
            ).points[0].max_local_mach
            for m in (0.1, 0.3, 0.5)
        ]
        assert all(a < b for a, b in zip(peaks, peaks[1:]))

    def test_critical_mach_is_reported(self, polar: Polar) -> None:
        assert 0.2 < polar.critical_mach < 0.9


class TestCsvRoundTrip:
    def test_values_survive_to_written_precision(self, polar: Polar, tmp_path) -> None:
        path = polar.to_csv(tmp_path / "p.csv")
        reloaded = Polar.from_csv(path)
        assert np.allclose(reloaded.alpha_deg, polar.alpha_deg, atol=1e-6)
        assert np.allclose(reloaded.cl, polar.cl, atol=1e-6)
        assert np.allclose(reloaded.cd, polar.cd, atol=1e-7, equal_nan=True)
        assert np.allclose(reloaded.cm, polar.cm, atol=1e-6)

    def test_conditions_survive(self, polar: Polar, tmp_path) -> None:
        """A polar file must be self-describing, or it cannot be reused."""
        reloaded = Polar.from_csv(polar.to_csv(tmp_path / "p.csv"))
        assert reloaded.name == polar.name
        assert reloaded.reynolds == pytest.approx(polar.reynolds)
        assert reloaded.mach == pytest.approx(polar.mach)
        assert reloaded.n_crit == pytest.approx(polar.n_crit)
        assert reloaded.method == polar.method
        assert reloaded.correction == polar.correction
        assert reloaded.coupled == polar.coupled

    def test_flags_and_notes_survive(self, tmp_path) -> None:
        original = compute_polar(naca("2412", 201), np.array([2.0, 12.0]), 5e5)
        reloaded = Polar.from_csv(original.to_csv(tmp_path / "p.csv"))
        assert list(reloaded.converged) == list(original.converged)
        assert [p.note for p in reloaded.points] == [p.note for p in original.points]

    def test_angles_are_written_in_degrees(self, polar: Polar, tmp_path) -> None:
        """Degrees at the file boundary, radians everywhere inside."""
        text = (polar.to_csv(tmp_path / "p.csv")).read_text()
        assert "alpha_deg" in text
        first = text.strip().splitlines()[-len(polar)].split(",")[0]
        assert float(first) == pytest.approx(polar.alpha_deg[0], abs=1e-6)

    def test_the_directory_is_created(self, polar: Polar, tmp_path) -> None:
        path = polar.to_csv(tmp_path / "nested" / "deeper" / "p.csv")
        assert path.exists()


class TestBatch:
    def test_serial_and_parallel_agree(self) -> None:
        """Two workers must not change the answer."""
        requests = [
            PolarRequest(airfoil=name, reynolds=5e5,
                         alphas_deg=(0.0, 4.0), n_points=201)
            for name in ("naca0012", "naca2412")
        ]
        serial = batch_polars(requests, workers=1)
        parallel = batch_polars(requests, workers=2)
        for a, b in zip(serial, parallel):
            assert np.allclose(a.cl, b.cl)
            assert np.allclose(a.cd, b.cd, equal_nan=True)

    def test_results_come_back_in_request_order(self) -> None:
        requests = [
            PolarRequest(airfoil="naca0012", reynolds=r,
                         alphas_deg=(0.0,), n_points=201)
            for r in (2e5, 1e6, 5e6)
        ]
        results = batch_polars(requests, workers=1)
        assert [r.reynolds for r in results] == [2e5, 1e6, 5e6]

    def test_an_empty_batch_is_not_an_error(self) -> None:
        assert batch_polars([]) == []

    def test_a_request_is_picklable(self) -> None:
        """It must survive being sent to a subprocess."""
        import pickle

        request = PolarRequest(
            airfoil="naca2412", reynolds=5e5, alphas_deg=(0.0, 2.0)
        )
        assert pickle.loads(pickle.dumps(request)) == request

    def test_labels_are_usable_as_filenames(self) -> None:
        label = PolarRequest(
            airfoil="naca2412", reynolds=5e5, alphas_deg=(0.0,)
        ).label
        assert "/" not in label
        assert "+" not in label
        assert "naca2412" in label

    def test_running_a_request_matches_computing_directly(self) -> None:
        request = PolarRequest(
            airfoil="naca0012", reynolds=1e6, alphas_deg=(0.0, 3.0), n_points=201
        )
        direct = compute_polar(
            naca("0012", 201), np.array([0.0, 3.0]), 1e6, name="NACA 0012"
        )
        assert np.allclose(run_request(request).cl, direct.cl)
