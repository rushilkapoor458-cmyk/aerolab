"""Tests for the panel-independence study.

The study's job is to report how the solver converges, so what matters is that
its extrapolation and order estimation are themselves correct. Both are checked
against synthetic sequences with a known limit and a known order, where the
right answer is not in doubt.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.validation.panel_independence import (
    PanelStudy,
    _richardson,
    plot_panel_study,
    run_panel_study,
)


def synthetic(limit: float, coefficient: float, order: float, counts) -> PanelStudy:
    """A study whose values follow ``limit + coefficient * N**-order`` exactly."""
    n = np.asarray(counts, dtype=np.float64)
    values = limit + coefficient * n**-order
    return PanelStudy(
        section="synthetic",
        alpha=0.0,
        n_panels=n,
        cl_pressure=values,
        cl_kutta_joukowski=values,
        cm_quarter_chord=values,
        cd_pressure=np.zeros_like(n),
        lift_disagreement=np.zeros_like(n),
        condition_number=np.ones_like(n),
    )


class TestRichardson:
    """First-order extrapolation, including the non-doubling case."""

    def test_recovers_the_limit_of_a_first_order_sequence(self) -> None:
        limit, coefficient = 1.234, 5.0
        for n_coarse, n_fine in ((100.0, 200.0), (320.0, 400.0), (60.0, 61.0)):
            coarse = limit + coefficient / n_coarse
            fine = limit + coefficient / n_fine
            assert _richardson(coarse, fine, n_coarse, n_fine) == pytest.approx(
                limit, rel=1e-12
            )

    def test_doubling_reduces_to_the_familiar_formula(self) -> None:
        assert _richardson(0.9, 0.95, 100.0, 200.0) == pytest.approx(
            2 * 0.95 - 0.9, rel=1e-12
        )

    def test_non_doubling_is_not_the_doubling_formula(self) -> None:
        """At a ratio of 1.25 the naive formula under-corrects fourfold.

        This is the mistake the general form exists to avoid, and the default
        sweep ends on exactly that ratio.
        """
        coarse, fine = 0.90, 0.95
        general = _richardson(coarse, fine, 320.0, 400.0)
        naive = 2 * fine - coarse
        assert general == pytest.approx(fine + 4 * (fine - coarse), rel=1e-12)
        assert abs(general - naive) > 0.1

    def test_equal_counts_return_the_finer_value(self) -> None:
        assert _richardson(0.9, 0.95, 200.0, 200.0) == 0.95


class TestConvergenceOrder:
    """The order estimator, against sequences of known order."""

    @pytest.mark.parametrize("order", [0.5, 0.8, 1.0, 1.5, 2.0])
    def test_recovers_a_known_order(self, order: float) -> None:
        study = synthetic(1.0, 3.0, order, (100, 200, 400))
        assert study.convergence_order() == pytest.approx(order, rel=1e-4)

    @pytest.mark.parametrize("order", [0.8, 1.0, 2.0])
    def test_works_without_a_constant_refinement_ratio(self, order: float) -> None:
        """The default sweep refines by 1.33 then 1.25, not by 2."""
        study = synthetic(1.0, 3.0, order, (240, 320, 400))
        assert study.convergence_order() == pytest.approx(order, rel=1e-4)

    def test_converged_sequence_reports_nan_rather_than_a_number(self) -> None:
        study = synthetic(1.0, 0.0, 1.0, (100, 200, 400))
        assert np.isnan(study.convergence_order())

    def test_too_few_points_is_an_error(self) -> None:
        study = synthetic(1.0, 3.0, 1.0, (100, 200))
        with pytest.raises(ValueError, match="at least three"):
            study.convergence_order()


class TestStudy:
    """The study itself, run on a real section."""

    @pytest.fixture(scope="module")
    def study(self) -> PanelStudy:
        return run_panel_study("2412", 5.0, point_counts=(81, 121, 161, 241, 321))

    def test_panel_counts_are_one_less_than_point_counts(self, study) -> None:
        assert list(study.n_panels) == [80, 120, 160, 240, 320]

    def test_alpha_is_stored_in_radians(self, study) -> None:
        assert study.alpha == pytest.approx(np.deg2rad(5.0))

    def test_observed_order_is_first(self, study) -> None:
        """The headline result: constant-strength panels converge at order one."""
        assert study.convergence_order() == pytest.approx(1.0, abs=0.35)

    def test_lift_converges_monotonically_towards_the_limit(self, study) -> None:
        error = np.abs(study.cl_pressure - study.cl_converged)
        assert all(a > b for a, b in zip(error, error[1:]))

    def test_dalembert_residual_shrinks(self, study) -> None:
        assert all(
            a > b
            for a, b in zip(np.abs(study.cd_pressure), np.abs(study.cd_pressure[1:]))
        )

    def test_lift_disagreement_shrinks(self, study) -> None:
        assert all(
            a > b for a, b in zip(study.lift_disagreement, study.lift_disagreement[1:])
        )

    def test_condition_number_stays_workable(self, study) -> None:
        assert np.all(study.condition_number < 1e8)

    def test_extrapolated_lift_is_beyond_the_finest_value(self, study) -> None:
        """Lift is still rising with panel count, so the limit must exceed it."""
        assert study.cl_converged > study.cl_pressure[-1]


class TestFigure:
    def test_writes_a_file(self, tmp_path) -> None:
        studies = [run_panel_study("0012", 5.0, point_counts=(61, 121, 241))]
        out = plot_panel_study(studies, tmp_path / "sub" / "study.png")
        assert out.exists()
        assert out.stat().st_size > 10_000
