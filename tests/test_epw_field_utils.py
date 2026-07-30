# -*- coding: utf-8 -*-
"""
tests/test_epw_field_utils.py
================================

Unit tests for :mod:`pyweatherfiles.epw_field_utils`, the module extracted
in Fase 1 of ``INFORME_REVISION_GENERAL.md`` §3.1 to remove the duplicated
EPW-handling logic that used to live independently in
``hourly_epw_converter.py`` and ``met_epw_converter.py``.
"""

import pytest

from pyweatherfiles.epw_field_utils import (
    UNUSED_EPW_FIELDS,
    calculate_atmos_pressure,
    get_epw_values,
    neutralize_unused_epw_fields,
    set_epw_values,
)


# =============================================================================
# calculate_atmos_pressure
# =============================================================================

class TestCalculateAtmosPressure:
    def test_sea_level_matches_standard_pressure(self):
        # Matches the docstring example and the ISA standard sea-level pressure.
        assert calculate_atmos_pressure(0) == pytest.approx(101325.0, abs=1.0)

    def test_decreases_with_elevation(self):
        p_sea_level = calculate_atmos_pressure(0)
        p_1000m = calculate_atmos_pressure(1000)
        p_2000m = calculate_atmos_pressure(2000)
        assert p_sea_level > p_1000m > p_2000m

    def test_known_value_at_15m(self):
        # Regression value captured from the pre-refactor implementations in
        # both hourly_epw_converter.py and met_epw_converter.py (they were
        # bit-for-bit identical formulas before Fase 1).
        assert calculate_atmos_pressure(15) == pytest.approx(101144.94, abs=0.05)


# =============================================================================
# set_epw_values / get_epw_values (Ladybug point-in-time offset compensation)
# =============================================================================

class TestSetGetEpwValues:
    def test_point_in_time_field_is_shifted_on_set(self, fake_epw):
        fake_epw.add_field("dry_bulb_temperature", [0.0] * 5, point_in_time=True)
        new_vals = [10, 11, 12, 13, 14]

        set_epw_values(fake_epw, "dry_bulb_temperature", new_vals)

        # [last] + values[:-1]
        assert list(fake_epw.dry_bulb_temperature.values) == [14, 10, 11, 12, 13]

    def test_non_point_in_time_field_is_not_shifted_on_set(self, fake_epw):
        fake_epw.add_field("liquid_precipitation_depth", [0.0] * 5, point_in_time=False)
        new_vals = [10, 11, 12, 13, 14]

        set_epw_values(fake_epw, "liquid_precipitation_depth", new_vals)

        assert list(fake_epw.liquid_precipitation_depth.values) == new_vals

    def test_set_preserves_tuple_type(self, fake_epw):
        fake_epw.add_field("dry_bulb_temperature", (0.0,) * 5, point_in_time=True)
        set_epw_values(fake_epw, "dry_bulb_temperature", [10, 11, 12, 13, 14])
        assert isinstance(fake_epw.dry_bulb_temperature.values, tuple)

    def test_get_reverses_set_for_point_in_time_field(self, fake_epw):
        """Round-trip: get_epw_values(set_epw_values(x)) == x for point-in-time fields."""
        fake_epw.add_field("dry_bulb_temperature", [0.0] * 5, point_in_time=True)
        original = [10, 11, 12, 13, 14]

        set_epw_values(fake_epw, "dry_bulb_temperature", original)
        recovered = get_epw_values(fake_epw, "dry_bulb_temperature")

        assert recovered == original

    def test_get_is_identity_for_non_point_in_time_field(self, fake_epw):
        fake_epw.add_field("liquid_precipitation_depth", [1, 2, 3], point_in_time=False)
        assert get_epw_values(fake_epw, "liquid_precipitation_depth") == [1, 2, 3]


# =============================================================================
# UNUSED_EPW_FIELDS / neutralize_unused_epw_fields
# =============================================================================

class TestUnusedEpwFields:
    def test_has_exactly_15_fields(self):
        # The EPW data-dictionary marks exactly 15 hourly fields as unused by
        # EnergyPlus (see README.md §4.4 item 5 / §5.2).
        assert len(UNUSED_EPW_FIELDS) == 15

    def test_known_missing_value_codes(self):
        assert UNUSED_EPW_FIELDS["global_horizontal_illuminance"] == 999999
        assert UNUSED_EPW_FIELDS["total_sky_cover"] == 99
        assert UNUSED_EPW_FIELDS["aerosol_optical_depth"] == 0.999

    def test_neutralize_fills_present_fields(self, fake_epw):
        fake_epw.add_field("total_sky_cover", [0] * 4, point_in_time=True)
        fake_epw.add_field("global_horizontal_illuminance", [0] * 4, point_in_time=True)
        # A field NOT in UNUSED_EPW_FIELDS, must stay untouched.
        fake_epw.add_field("dry_bulb_temperature", [20, 21, 22, 23], point_in_time=True)

        neutralize_unused_epw_fields(fake_epw, num_rows=4)

        assert list(fake_epw.total_sky_cover.values) == [99, 99, 99, 99]
        assert list(fake_epw.global_horizontal_illuminance.values) == [999999] * 4
        assert list(fake_epw.dry_bulb_temperature.values) == [20, 21, 22, 23]

    def test_neutralize_respects_skip_fields(self, fake_epw):
        fake_epw.add_field("total_sky_cover", [5, 5, 5], point_in_time=True)

        neutralize_unused_epw_fields(fake_epw, num_rows=3, skip_fields={"total_sky_cover"})

        # Untouched, because it was explicitly preserved (e.g. real cloud-cover data).
        assert list(fake_epw.total_sky_cover.values) == [5, 5, 5]

    def test_neutralize_ignores_missing_fields(self, fake_epw):
        # No fields defined at all: must not raise.
        neutralize_unused_epw_fields(fake_epw, num_rows=3)

