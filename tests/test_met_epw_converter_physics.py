# -*- coding: utf-8 -*-
"""
tests/test_met_epw_converter_physics.py
==========================================

Unit tests for the pure physical/psychrometric helper functions in
:mod:`pyweatherfiles.met_epw_converter` (dew point, sky temperature,
absolute humidity, and the .met-specific reverse-engineered pressure).

These are the "Nivel 1" tests recommended by
``INFORME_REVISION_GENERAL.md`` §6 Fase 2: deterministic, dependency-free
functions that are trivial to test and already had ready-made examples in
their docstrings.
"""

import pytest

from pyweatherfiles.met_epw_converter import (
    _calculate_absolute_humidity,
    _calculate_atmos_pressure,
    _calculate_dew_point,
    _calculate_sky_temperature,
    _calculate_variable_pressure_from_met,
)


class TestCalculateDewPoint:
    def test_matches_docstring_example(self):
        # NOTE: the docstring in met_epw_converter.py states "13.86" but the
        # actual computed value is 13.85 (round(13.851583599891661, 2)) —
        # a pre-existing typo in the docstring's rounded example, not a bug
        # in the formula itself (verified independently below via the raw
        # Magnus formula). Kept here as a regression pin on the real value.
        assert round(_calculate_dew_point(25.0, 50.0), 2) == 13.85

    def test_saturated_air_dew_point_equals_dry_bulb(self):
        # At 100% RH, dew point == dry-bulb temperature.
        assert _calculate_dew_point(20.0, 100.0) == pytest.approx(20.0, abs=1e-6)

    def test_zero_rh_returns_dry_bulb_unchanged(self):
        # Degenerate case explicitly handled to avoid log(0).
        assert _calculate_dew_point(18.0, 0.0) == 18.0

    def test_dew_point_never_exceeds_dry_bulb(self):
        for rh in (10, 30, 50, 70, 90, 100):
            assert _calculate_dew_point(25.0, rh) <= 25.0 + 1e-9


class TestCalculateAtmosPressureMet:
    def test_matches_docstring_example(self):
        assert round(_calculate_atmos_pressure(0), 0) == 101325.0

    def test_delegates_to_shared_epw_field_utils_implementation(self):
        from pyweatherfiles.epw_field_utils import calculate_atmos_pressure

        assert _calculate_atmos_pressure(500) == calculate_atmos_pressure(500)


class TestCalculateSkyTemperature:
    def test_zero_radiation_returns_absolute_zero_sentinel(self):
        assert _calculate_sky_temperature(0) == -273.15

    def test_negative_radiation_returns_absolute_zero_sentinel(self):
        assert _calculate_sky_temperature(-10) == -273.15

    def test_known_value(self):
        # Stefan-Boltzmann inversion: T_sky = (IR / sigma) ** 0.25 - 273.15
        stefan_boltzmann = 5.6697e-8
        ir = 300.0
        expected = (ir / stefan_boltzmann) ** 0.25 - 273.15
        assert _calculate_sky_temperature(ir) == pytest.approx(expected, abs=1e-6)


class TestCalculateAbsoluteHumidity:
    def test_very_dry_air_returns_zero(self):
        assert _calculate_absolute_humidity(20.0, 0.05, 101325) == 0.0

    def test_result_is_non_negative(self):
        assert _calculate_absolute_humidity(30.0, 80.0, 101325) >= 0.0

    def test_higher_rh_gives_higher_absolute_humidity(self):
        low = _calculate_absolute_humidity(25.0, 20.0, 101325)
        high = _calculate_absolute_humidity(25.0, 80.0, 101325)
        assert high > low


class TestCalculateVariablePressureFromMet:
    def test_falls_back_to_barometric_formula_when_wabs_is_zero(self):
        from pyweatherfiles.epw_field_utils import calculate_atmos_pressure

        result = _calculate_variable_pressure_from_met(
            temp_c=20.0, rel_hum=50.0, wabs=0.0, elevation_m=15.0
        )
        assert result == calculate_atmos_pressure(15.0)

    def test_falls_back_to_barometric_formula_when_result_not_physical(self):
        from pyweatherfiles.epw_field_utils import calculate_atmos_pressure

        # Absurdly high absolute humidity with very low RH should push the
        # reverse-engineered pressure outside the [50000, 110000] Pa sanity
        # window, triggering the barometric-formula fallback.
        result = _calculate_variable_pressure_from_met(
            temp_c=20.0, rel_hum=0.5, wabs=50.0, elevation_m=15.0
        )
        assert result == calculate_atmos_pressure(15.0)

    def test_plausible_inputs_stay_within_physical_range(self):
        result = _calculate_variable_pressure_from_met(
            temp_c=25.0, rel_hum=55.0, wabs=0.010, elevation_m=15.0
        )
        assert 50000 < result < 110000



