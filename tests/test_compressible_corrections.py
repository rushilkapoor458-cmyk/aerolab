"""Tests for compressibility corrections.

The critical-Mach calculation is checked against an independent closed form: at
the critical Mach number the corrected peak suction must equal the *sonic*
pressure coefficient, which follows from the isentropic relations alone and
shares no code with the root finder. That is the classical graphical
construction — the correction curve crossing the sonic line — done numerically.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerolab.compressible import corrections as cc
from aerolab.exceptions import ValidityRangeError

pytestmark = pytest.mark.validation


def sonic_cp(mach: float, gamma: float = cc.GAMMA_AIR) -> float:
    """Pressure coefficient at which the local flow is exactly sonic.

    Derived from the isentropic relations with ``M_local = 1``, independent of
    everything in the module under test:

    ``Cp* = 2/(gamma M^2) [ ((1 + (gamma-1)/2 M^2)/((gamma+1)/2))^(gamma/(gamma-1)) - 1 ]``
    """
    stagnation = 1.0 + 0.5 * (gamma - 1.0) * mach**2
    ratio = (stagnation / ((gamma + 1.0) / 2.0)) ** (gamma / (gamma - 1.0))
    return (2.0 / (gamma * mach**2)) * (ratio - 1.0)


class TestPrandtlGlauert:
    def test_is_the_identity_at_zero_mach(self) -> None:
        cp = np.array([-2.0, -0.5, 0.0, 0.8])
        assert np.allclose(cc.prandtl_glauert(cp, 0.0), cp)

    @pytest.mark.parametrize("mach", [0.2, 0.4, 0.6])
    def test_matches_the_closed_form(self, mach: float) -> None:
        cp = np.array([-1.5, -0.3, 0.7])
        assert np.allclose(
            cc.prandtl_glauert(cp, mach), cp / np.sqrt(1.0 - mach**2)
        )

    def test_being_linear_it_scales_integrated_forces_exactly(self) -> None:
        """Cl is a linear functional of Cp, so PG scales it by the same 1/beta."""
        rng = np.random.default_rng(0)
        cp = rng.normal(size=64)
        weights = rng.normal(size=64)
        mach = 0.5
        beta = np.sqrt(1.0 - mach**2)
        incompressible = float(cp @ weights)
        compressible = float(cc.prandtl_glauert(cp, mach) @ weights)
        assert compressible == pytest.approx(incompressible / beta, rel=1e-12)

    def test_negative_mach_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="non-negative"):
            cc.prandtl_glauert(np.array([-1.0]), -0.1)

    def test_near_sonic_freestream_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="subcritical"):
            cc.prandtl_glauert(np.array([-1.0]), 0.99)


class TestKarmanTsien:
    def test_is_the_identity_at_zero_mach(self) -> None:
        cp = np.array([-2.0, -0.5, 0.0, 0.8])
        assert np.allclose(cc.karman_tsien(cp, 0.0), cp)

    def test_matches_the_closed_form(self) -> None:
        cp = np.array([-1.0])
        mach = 0.5
        beta = np.sqrt(1.0 - mach**2)
        expected = cp / (beta + (mach**2 / (1.0 + beta)) * cp / 2.0)
        assert np.allclose(cc.karman_tsien(cp, mach), expected)

    def test_amplifies_suction_more_than_prandtl_glauert(self) -> None:
        """The non-linearity is the point: a strong suction is corrected harder."""
        cp = np.array([-1.5])
        mach = 0.5
        assert cc.karman_tsien(cp, mach)[0] < cc.prandtl_glauert(cp, mach)[0]

    def test_softens_positive_pressure_relative_to_prandtl_glauert(self) -> None:
        """The same non-linearity works the other way on the pressure side."""
        cp = np.array([0.8])
        mach = 0.5
        assert cc.karman_tsien(cp, mach)[0] < cc.prandtl_glauert(cp, mach)[0]

    def test_the_correction_grows_with_mach(self) -> None:
        cp = np.array([-1.0])
        values = [float(cc.karman_tsien(cp, m)[0]) for m in (0.0, 0.2, 0.4, 0.6)]
        assert all(a > b for a, b in zip(values, values[1:]))

    def test_a_sign_flipping_denominator_is_refused(self) -> None:
        """At high Mach with a strong suction the denominator passes through zero.

        Beyond that point the correction would turn a suction peak into a
        pressure peak. It is refused rather than returned, because the number
        looks perfectly ordinary and is meaningless.
        """
        with pytest.raises(ValidityRangeError, match="denominator"):
            cc.karman_tsien(np.array([-2.0]), 0.9)


class TestLocalMachNumber:
    def test_is_zero_everywhere_at_zero_freestream_mach(self) -> None:
        assert np.allclose(cc.local_mach_number(np.array([-2.0, 0.5]), 0.0), 0.0)

    @pytest.mark.parametrize("mach", [0.2, 0.5, 0.8])
    def test_equals_the_freestream_where_cp_is_zero(self, mach: float) -> None:
        """Cp = 0 means local pressure equals freestream, so local Mach does too."""
        assert float(cc.local_mach_number(np.array([0.0]), mach)[0]) == pytest.approx(
            mach, rel=1e-12
        )

    def test_suction_raises_the_local_mach_number(self) -> None:
        values = cc.local_mach_number(np.array([0.0, -0.5, -1.0, -2.0]), 0.5)
        assert np.all(np.diff(values) > 0.0)

    def test_agrees_with_the_independent_sonic_relation(self) -> None:
        """Feeding Cp* back in must return exactly Mach 1."""
        for mach in (0.3, 0.5, 0.7):
            assert float(
                cc.local_mach_number(np.array([sonic_cp(mach)]), mach)[0]
            ) == pytest.approx(1.0, rel=1e-9)

    def test_impossible_pressure_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="negative absolute pressure"):
            cc.local_mach_number(np.array([-50.0]), 0.8)


class TestCompressibleField:
    def test_zero_mach_leaves_the_pressures_alone(self) -> None:
        cp = np.array([-1.0, 0.5])
        field = cc.apply_correction(cp, 0.0)
        assert np.allclose(field.cp, cp)
        assert field.max_local_mach == 0.0
        assert field.is_trustworthy
        assert field.warning is None

    def test_flags_rather_than_raises_outside_its_range(self) -> None:
        """The user may legitimately want to see how close to critical a section is."""
        field = cc.apply_correction(np.array([-1.0]), 0.5)
        assert not field.is_trustworthy
        assert not field.is_supercritical
        assert field.warning is not None
        assert "trustworthy" in field.warning

    def test_check_turns_the_flag_into_an_exception(self) -> None:
        field = cc.apply_correction(np.array([-1.0]), 0.5)
        with pytest.raises(ValidityRangeError):
            field.check()

    def test_check_passes_inside_the_range(self) -> None:
        field = cc.apply_correction(np.array([-0.3]), 0.3)
        assert field.check() is field

    def test_supercritical_is_reported_distinctly(self) -> None:
        field = cc.apply_correction(np.array([-1.0]), 0.75)
        assert field.is_supercritical
        assert "shock" in field.warning

    def test_unknown_method_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="correction must be"):
            cc.apply_correction(np.array([-1.0]), 0.3, method="glauert")


class TestCriticalMachNumber:
    @pytest.mark.parametrize("cp_min", [-0.4, -0.6, -1.0, -2.0])
    @pytest.mark.parametrize("method", ["karman-tsien", "prandtl-glauert"])
    def test_the_corrected_peak_equals_the_sonic_pressure_there(
        self, cp_min: float, method: str
    ) -> None:
        """The defining property, checked against a formula sharing no code.

        At the critical Mach number the corrected minimum pressure coefficient
        must coincide with Cp*, the value at which the local flow is sonic.
        """
        mach = cc.critical_mach_number(cp_min, method=method)
        corrected = float(
            cc.apply_correction(np.array([cp_min]), mach, method=method).cp[0]
        )
        assert corrected == pytest.approx(sonic_cp(mach), rel=1e-6)

    def test_falls_as_the_section_is_loaded_harder(self) -> None:
        machs = [cc.critical_mach_number(cp) for cp in (-0.3, -0.6, -1.0, -2.0)]
        assert all(a > b for a, b in zip(machs, machs[1:]))

    def test_karman_tsien_predicts_a_lower_critical_mach(self) -> None:
        """It amplifies the suction more, so the section goes sonic sooner."""
        for cp_min in (-0.5, -1.0, -2.0):
            assert cc.critical_mach_number(cp_min, "karman-tsien") < (
                cc.critical_mach_number(cp_min, "prandtl-glauert")
            )

    def test_a_thin_section_is_in_the_expected_range(self) -> None:
        """A peak suction near -0.4 gives a critical Mach in the low 0.7s."""
        assert 0.70 < cc.critical_mach_number(-0.4) < 0.76

    def test_a_positive_pressure_coefficient_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="must be a suction"):
            cc.critical_mach_number(0.2)

    def test_a_section_that_never_goes_critical_is_refused(self) -> None:
        with pytest.raises(ValidityRangeError, match="does not reach sonic"):
            cc.critical_mach_number(-1e-6)
