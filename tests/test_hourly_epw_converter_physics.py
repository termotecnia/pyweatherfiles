# -*- coding: utf-8 -*-
"""
tests/test_hourly_epw_converter_physics.py
=============================================

Unit tests for the pure physical helper methods of
:class:`pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`
(``_calculate_rh``, ``_calculate_atmos_pressure``).

These methods do not use any instance state (``self``) in their body, so
the tests build a "bare" instance via ``__new__`` to avoid needing a real
source file / EPW template on disk just to test pure math.
"""

import math

import pytest

from pyweatherfiles.hourly_epw_converter import HourlyEPWConverter


@pytest.fixture
def bare_converter() -> HourlyEPWConverter:
    """A HourlyEPWConverter instance that skips __init__ (no file I/O)."""
    return HourlyEPWConverter.__new__(HourlyEPWConverter)


class TestCalculateRh:
    def test_saturated_air_gives_100_percent(self, bare_converter):
        rh = bare_converter._calculate_rh(tdb=20.0, tdp=20.0)
        assert rh == pytest.approx(100.0, abs=1e-6)

    def test_dry_air_gives_low_rh(self, bare_converter):
        rh = bare_converter._calculate_rh(tdb=30.0, tdp=5.0)
        assert 0.0 <= rh < 40.0

    def test_result_is_clipped_to_0_100(self, bare_converter):
        rh = bare_converter._calculate_rh(tdb=10.0, tdp=-40.0)
        assert 0.0 <= rh <= 100.0

    def test_dew_point_above_dry_bulb_is_clipped(self, bare_converter):
        # Physically inconsistent input (Tdp > Tdb): implementation clips
        # Tdp down to Tdb, which must yield ~100% RH, not an error.
        rh = bare_converter._calculate_rh(tdb=15.0, tdp=25.0)
        assert rh == pytest.approx(100.0, abs=1e-6)

    def test_nan_inputs_return_default_50_percent(self, bare_converter):
        assert bare_converter._calculate_rh(tdb=float("nan"), tdp=10.0) == 50.0
        assert bare_converter._calculate_rh(tdb=10.0, tdp=float("nan")) == 50.0

    def test_matches_manual_magnus_formula(self, bare_converter):
        tdb, tdp = 25.0, 15.0
        es = 6.112 * math.exp((17.67 * tdb) / (tdb + 243.5))
        e = 6.112 * math.exp((17.67 * tdp) / (tdp + 243.5))
        expected = min(max((e / es) * 100.0, 0.0), 100.0)
        assert bare_converter._calculate_rh(tdb, tdp) == pytest.approx(expected)


class TestCalculateAtmosPressureInstanceWrapper:
    def test_delegates_to_shared_epw_field_utils_implementation(self, bare_converter):
        from pyweatherfiles.epw_field_utils import calculate_atmos_pressure

        bare_converter.elev = 200.0
        assert bare_converter._calculate_atmos_pressure() == calculate_atmos_pressure(200.0)

