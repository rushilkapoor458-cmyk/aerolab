"""Tests for the vortex lattice method.

The elliptic wing is the reference case and it is a strong one, because two
independent things must come out right at once: the span efficiency must be 1,
and the induced drag must equal ``CL^2/(pi AR)``. Those are different statements
— the first is about the *shape* of the loading, the second about its
*magnitude* — and a sign or factor error will generally break one without the
other.

Beyond that, the method is checked against classical results it was never told
about: the lift slope tending to ``2*pi`` as aspect ratio grows, span efficiency
peaking near a taper ratio of 0.4, and washout unloading the tips.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.exceptions import ValidityRangeError
from aerolab.inviscid.vlm import (
    Wing,
    WingSection,
    elliptic_wing,
    solve_vlm,
    tapered_wing,
)

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def elliptic():
    return elliptic_wing(span=8.0, root_chord=1.0)


class TestWingGeometry:
    def test_elliptic_area_matches_the_closed_form(self, elliptic) -> None:
        """``pi b c_root / 4`` for an ellipse."""
        assert elliptic.area == pytest.approx(np.pi * 8.0 * 1.0 / 4.0, rel=2e-3)

    def test_rectangular_area_and_aspect_ratio(self) -> None:
        wing = tapered_wing(span=10.0, root_chord=2.0, taper=1.0)
        assert wing.area == pytest.approx(20.0, rel=1e-9)
        assert wing.aspect_ratio == pytest.approx(5.0, rel=1e-9)

    def test_tapered_area(self) -> None:
        wing = tapered_wing(span=8.0, root_chord=1.0, taper=0.5)
        assert wing.area == pytest.approx(8.0 * 0.5 * (1.0 + 0.5), rel=1e-6)

    def test_chord_interpolates_between_sections(self) -> None:
        wing = tapered_wing(span=4.0, root_chord=1.0, taper=0.5)
        assert float(wing.chord_at(np.array([0.0]))[0]) == pytest.approx(1.0)
        assert float(wing.chord_at(np.array([2.0]))[0]) == pytest.approx(0.5)
        assert float(wing.chord_at(np.array([1.0]))[0]) == pytest.approx(0.75)

    def test_mirroring_makes_the_chord_symmetric(self) -> None:
        wing = tapered_wing(span=4.0, root_chord=1.0, taper=0.5)
        assert float(wing.chord_at(np.array([-1.0]))[0]) == pytest.approx(
            float(wing.chord_at(np.array([1.0]))[0])
        )

    def test_too_few_sections_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="at least 2 sections"):
            Wing(sections=(WingSection(y=0.0, chord=1.0),))

    def test_unordered_sections_are_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="increasing y"):
            Wing(sections=(WingSection(y=2.0, chord=1.0), WingSection(y=1.0, chord=1.0)))

    def test_zero_chord_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="chord must be positive"):
            Wing(sections=(WingSection(y=0.0, chord=1.0), WingSection(y=2.0, chord=0.0)))


class TestEllipticWingAcceptance:
    """The Phase 6 acceptance criteria."""

    def test_span_efficiency_is_one(self, elliptic) -> None:
        result = solve_vlm(elliptic, np.deg2rad(5.0), n_span=60, n_chord=4)
        assert result.span_efficiency == pytest.approx(1.0, abs=0.02)

    def test_induced_drag_matches_the_classical_formula(self, elliptic) -> None:
        """``CDi = CL^2 / (pi AR)`` to within 2%."""
        result = solve_vlm(elliptic, np.deg2rad(5.0), n_span=60, n_chord=4)
        assert result.cdi == pytest.approx(result.cdi_elliptic, rel=0.02)

    @pytest.mark.parametrize("alpha_deg", [2.0, 5.0, 8.0])
    def test_both_hold_across_incidence(self, elliptic, alpha_deg: float) -> None:
        result = solve_vlm(elliptic, np.deg2rad(alpha_deg), n_span=60, n_chord=4)
        assert result.span_efficiency == pytest.approx(1.0, abs=0.02)
        assert result.cdi == pytest.approx(result.cdi_elliptic, rel=0.02)

    def test_span_efficiency_does_not_vary_with_incidence(self, elliptic) -> None:
        """An untwisted wing keeps the same loading *shape* at every angle."""
        values = [
            solve_vlm(elliptic, np.deg2rad(a), n_span=50).span_efficiency
            for a in (2.0, 5.0, 9.0)
        ]
        assert np.ptp(values) < 1e-6

    def test_induced_drag_scales_with_lift_squared(self, elliptic) -> None:
        low = solve_vlm(elliptic, np.deg2rad(3.0), n_span=50)
        high = solve_vlm(elliptic, np.deg2rad(6.0), n_span=50)
        assert high.cdi / low.cdi == pytest.approx((high.cl / low.cl) ** 2, rel=1e-6)


class TestClassicalResults:
    """Behaviour the method was never told about."""

    def test_lift_slope_approaches_two_pi_with_aspect_ratio(self) -> None:
        slopes = []
        for span in (4.0, 8.0, 16.0, 32.0):
            wing = tapered_wing(span=span, root_chord=1.0, taper=1.0)
            low = solve_vlm(wing, np.deg2rad(1.0), n_span=50)
            high = solve_vlm(wing, np.deg2rad(5.0), n_span=50)
            slopes.append((high.cl - low.cl) / np.deg2rad(4.0))
        assert all(a < b for a, b in zip(slopes, slopes[1:]))
        assert slopes[-1] < 2.0 * np.pi
        assert slopes[-1] > 0.85 * 2.0 * np.pi

    def test_lift_slope_is_below_the_lifting_line_estimate(self) -> None:
        """``2 pi AR/(AR+2)`` is an upper bound the lattice should sit under."""
        wing = tapered_wing(span=8.0, root_chord=1.0, taper=1.0)
        low = solve_vlm(wing, np.deg2rad(1.0), n_span=50)
        high = solve_vlm(wing, np.deg2rad(5.0), n_span=50)
        slope = (high.cl - low.cl) / np.deg2rad(4.0)
        aspect = wing.aspect_ratio
        assert slope < 2.0 * np.pi * aspect / (aspect + 2.0)

    def test_a_rectangular_wing_is_less_efficient_than_elliptic(self) -> None:
        wing = tapered_wing(span=8.0, root_chord=1.0, taper=1.0)
        assert solve_vlm(wing, np.deg2rad(5.0), n_span=50).span_efficiency < 0.99

    def test_efficiency_peaks_near_a_taper_of_forty_percent(self) -> None:
        """The classical result, reproduced without being told it."""
        tapers = np.array([1.0, 0.7, 0.55, 0.45, 0.35, 0.2])
        efficiency = [
            solve_vlm(
                tapered_wing(span=8.0, root_chord=1.0, taper=float(t)),
                np.deg2rad(5.0), n_span=50,
            ).span_efficiency
            for t in tapers
        ]
        best = tapers[int(np.argmax(efficiency))]
        assert 0.3 <= best <= 0.6

    def test_washout_unloads_the_tips(self) -> None:
        clean = tapered_wing(span=8.0, root_chord=1.0, taper=0.5)
        twisted = tapered_wing(
            span=8.0, root_chord=1.0, taper=0.5, twist_tip=np.deg2rad(-4.0)
        )
        a = solve_vlm(clean, np.deg2rad(6.0), n_span=50)
        b = solve_vlm(twisted, np.deg2rad(6.0), n_span=50)
        tip = a.y > 0.8 * (clean.span / 2.0)
        assert np.mean(b.section_cl[tip]) < np.mean(a.section_cl[tip])
        assert b.cl < a.cl

    def test_sweep_reduces_lift_slope(self) -> None:
        straight = tapered_wing(span=8.0, root_chord=1.0, taper=0.5)
        swept = tapered_wing(
            span=8.0, root_chord=1.0, taper=0.5, sweep=np.deg2rad(30.0)
        )
        assert (
            solve_vlm(swept, np.deg2rad(5.0), n_span=50).cl
            < solve_vlm(straight, np.deg2rad(5.0), n_span=50).cl
        )


class TestStructure:
    def test_zero_incidence_on_an_untwisted_wing_gives_no_lift(self, elliptic) -> None:
        result = solve_vlm(elliptic, 0.0, n_span=40)
        assert abs(result.cl) < 1e-12
        assert result.cdi < 1e-14

    def test_loading_is_symmetric(self, elliptic) -> None:
        result = solve_vlm(elliptic, np.deg2rad(5.0), n_span=40)
        assert np.allclose(result.circulation, result.circulation[::-1], rtol=1e-8)

    def test_loading_falls_to_zero_at_the_tips(self, elliptic) -> None:
        result = solve_vlm(elliptic, np.deg2rad(5.0), n_span=60)
        assert result.circulation[0] < 0.1 * np.max(result.circulation)
        assert result.circulation[-1] < 0.1 * np.max(result.circulation)

    def test_lift_integrates_to_the_reported_coefficient(self, elliptic) -> None:
        """CL from the circulation integral must match the reported value."""
        result = solve_vlm(elliptic, np.deg2rad(5.0), n_span=50)
        edges = elliptic._span_edges(50)
        integral = 2.0 * np.sum(result.circulation * np.diff(edges)) / elliptic.area
        assert integral == pytest.approx(result.cl, rel=1e-12)

    def test_results_converge_with_spanwise_panels(self, elliptic) -> None:
        efficiency = [
            solve_vlm(elliptic, np.deg2rad(5.0), n_span=n).span_efficiency
            for n in (20, 40, 80)
        ]
        assert abs(efficiency[-1] - efficiency[-2]) < abs(
            efficiency[1] - efficiency[0]
        )

    def test_chordwise_panels_barely_move_the_answer(self, elliptic) -> None:
        """Lift and induced drag need few chordwise panels; this pins that."""
        values = [
            solve_vlm(elliptic, np.deg2rad(5.0), n_span=40, n_chord=n).cl
            for n in (1, 2, 4, 8)
        ]
        assert (max(values) - min(values)) / np.mean(values) < 0.05

    def test_too_few_panels_is_refused(self, elliptic) -> None:
        with pytest.raises(ValidityRangeError, match="at least 4 spanwise"):
            solve_vlm(elliptic, 0.0, n_span=2)


class TestStripTheoryWingPolar:
    """Combining induced drag with two-dimensional section drag."""

    @pytest.fixture
    def section_polar(self):
        from aerolab.geometry.naca import naca
        from aerolab.polar import compute_polar

        return compute_polar(naca("2412", 201), np.arange(-8.0, 13.0, 2.0), 5e5)

    def test_total_drag_is_the_sum_of_its_parts(self, section_polar) -> None:
        from aerolab.polar import wing_polar

        wing = tapered_wing(span=6.0, root_chord=1.0, taper=0.5)
        for point in wing_polar(wing, np.array([2.0, 6.0]), section_polar, n_span=30):
            assert point.cd == pytest.approx(point.cdi + point.cd_profile)

    def test_induced_drag_grows_faster_than_profile_drag(self, section_polar) -> None:
        """Induced drag goes as CL squared; profile drag barely moves."""
        from aerolab.polar import wing_polar

        wing = tapered_wing(span=6.0, root_chord=1.0, taper=0.5)
        low, high = wing_polar(wing, np.array([2.0, 8.0]), section_polar, n_span=30)
        assert high.cdi / low.cdi > 5.0
        assert high.cd_profile / low.cd_profile < 1.5

    def test_strips_outside_the_section_polar_are_counted(self, section_polar) -> None:
        """Clamping is acceptable; hiding it is not."""
        from aerolab.polar import wing_polar

        wing = tapered_wing(span=6.0, root_chord=1.0, taper=0.5)
        stranded = wing_polar(wing, np.array([16.0]), section_polar, n_span=30)[0]
        assert stranded.strips_outside_polar > 0

    def test_an_empty_section_polar_is_refused(self) -> None:
        from aerolab.polar import Polar, wing_polar

        wing = tapered_wing(span=6.0, root_chord=1.0, taper=0.5)
        empty = Polar(name="x", reynolds=1e5, mach=0.0, n_crit=9.0,
                      method="en", correction="none", coupled=False, points=())
        with pytest.raises(ValidityRangeError, match="fewer than two converged"):
            wing_polar(wing, np.array([2.0]), empty, n_span=30)
