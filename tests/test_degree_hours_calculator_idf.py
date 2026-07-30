# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_calculator_idf.py
============================================

Integration tests for ``DegreeHoursCalculator``'s real-IDF setpoint/
availability parsing (``extract_setpoints_from_idf``, ``_parse_compact``,
``_schedule_to_series``, ``_extract_availability_from_idf``), using the real
IDF already tracked in the repo root (``SF_Detached_D_min_South.idf``)
rather than a hand-built synthetic one, since it already exercises
``SCHEDULE:COMPACT`` with nested date ranges, ``ZoneControl:Thermostat`` +
``ThermostatSetpoint:DualSetpoint``, and ``ZoneHVAC:IdealLoadsAirSystem``
availability schedules (``degree_hours/calculator.py`` had only 24%
coverage before this file per ``INFORME_REVISION_GENERAL.md``'s Fase 2
coverage analysis, almost none of it from the IDF-parsing code paths).

Also covers the ``DegreeHoursCalculator`` dict-based setpoint types
(``'daily'``, ``'weekly'``, ``'hourly_weekly'``) not previously exercised by
any test (only ``'constant'`` was, in ``test_degree_hours_package.py``).

Requires the optional ``besos``/``eppy`` dependencies (extra
``energyplus``); the IDF-dependent classes are skipped automatically if the
fixture file or the optional dependencies are not available.
"""

from pathlib import Path

import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.degree_hours import DegreeHoursCalculator

besos = pytest.importorskip("besos")
pytest.importorskip("eppy")

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_IDF_PATH = REPO_ROOT / "SF_Detached_D_min_South.idf"

# Known, deterministic values hard-coded in SF_Detached_D_min_South.idf's
# SCHEDULE:COMPACT objects ('Heating/Cooling Set-point Schedule'):
#   Heating: 17 degC from 00:00-08:00, 20 degC from 08:00-24:00, every day.
#   Cooling: 27 degC from 00:00-08:00, 25 degC from 08:00-24:00, every day.
# Availability (ZoneHVAC:IdealLoadsAirSystem, 'Heating/Cooling Availability
# Schedule'): heating is OFF for May-September, cooling is OFF for Jan-April.


def _write_constant_temp_epw(path, temp, year=2021):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city="Test", latitude=37.0, longitude=-5.0, time_zone=1.0, elevation=10.0)
    epw.dry_bulb_temperature.values = [temp] * 8760
    epw.save(str(path))
    return str(path)


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestExtractSetpointsFromRealIdf:
    def test_heating_and_cooling_setpoints_match_known_schedule(self, tmp_path):
        epw_path = _write_constant_temp_epw(tmp_path / "const.epw", temp=10.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        setpoints = calc.extract_setpoints_from_idf(str(REAL_IDF_PATH), zone_name="LivingRoom")
        h = setpoints["LivingRoom"]

        # 00:00-08:00 -> 17 degC heating / 27 degC cooling.
        assert h["heating"].iloc[0] == pytest.approx(17.0)
        assert h["heating"].iloc[7] == pytest.approx(17.0)
        assert h["cooling"].iloc[0] == pytest.approx(27.0)
        # 08:00-24:00 -> 20 degC heating / 25 degC cooling.
        assert h["heating"].iloc[8] == pytest.approx(20.0)
        assert h["heating"].iloc[23] == pytest.approx(20.0)
        assert h["cooling"].iloc[8] == pytest.approx(25.0)

    def test_availability_schedules_vary_across_the_year(self, tmp_path):
        epw_path = _write_constant_temp_epw(tmp_path / "const.epw", temp=10.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        setpoints = calc.extract_setpoints_from_idf(str(REAL_IDF_PATH), zone_name="LivingRoom")
        h = setpoints["LivingRoom"]

        # Heating available in January, off in July (per the IDF's
        # seasonal 'Heating Availability Schedule').
        jan_val = h["heating_avail"][h["heating_avail"].index.month == 1].iloc[0]
        jul_val = h["heating_avail"][h["heating_avail"].index.month == 7].iloc[0]
        assert jan_val == 1.0
        assert jul_val == 0.0

    def test_all_zones_share_the_same_setpoints(self, tmp_path):
        epw_path = _write_constant_temp_epw(tmp_path / "const.epw", temp=10.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        setpoints = calc.extract_setpoints_from_idf(str(REAL_IDF_PATH))
        assert "LivingRoom" in setpoints
        assert "Kitchen" in setpoints
        # Every zone is driven by the exact same ThermostatSetpoint:DualSetpoint.
        pd.testing.assert_series_equal(
            setpoints["LivingRoom"]["heating"], setpoints["Kitchen"]["heating"],
            check_names=False,
        )

    def test_unknown_zone_name_raises_value_error_listing_available_zones(self, tmp_path):
        epw_path = _write_constant_temp_epw(tmp_path / "const.epw", temp=10.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        with pytest.raises(ValueError, match="not found in the IDF"):
            calc.extract_setpoints_from_idf(str(REAL_IDF_PATH), zone_name="NoSuchZone")


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestCalculateWithRealIdfAvailabilityMask:
    def test_heating_degree_hours_are_zero_when_unavailable(self, tmp_path):
        # Deliberately very cold constant temperature: without the
        # availability mask, heating degree-hours would be > 0 every month.
        epw_path = _write_constant_temp_epw(tmp_path / "cold.epw", temp=-5.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        results = calc.calculate(
            str(REAL_IDF_PATH), frequency=["monthly"], mode="heating",
            zone_name="LivingRoom", save_session=False,
        )
        monthly = results["monthly"]

        # January: heating available all month -> large positive HDH.
        assert monthly["heating_dh"].iloc[0] > 0
        # July: heating unavailable all month -> HDH must be exactly zero
        # despite the very cold constant temperature.
        assert monthly["heating_dh"].iloc[6] == pytest.approx(0.0)

    def test_cooling_degree_hours_are_zero_when_unavailable(self, tmp_path):
        # Deliberately very hot constant temperature.
        epw_path = _write_constant_temp_epw(tmp_path / "hot.epw", temp=40.0)
        calc = DegreeHoursCalculator(epw_path, year=2021)

        results = calc.calculate(
            str(REAL_IDF_PATH), frequency=["monthly"], mode="cooling",
            zone_name="LivingRoom", save_session=False,
        )
        monthly = results["monthly"]

        # January: cooling unavailable all month -> CDH must be exactly zero.
        assert monthly["cooling_dh"].iloc[0] == pytest.approx(0.0)


class TestSetpointsFromDictAdditionalTypes:
    """Covers the 'daily', 'weekly' and 'hourly_weekly' dict configuration
    types of ``_setpoints_from_dict()``, not exercised by any prior test
    (only 'constant' was, in ``test_degree_hours_package.py``)."""

    @staticmethod
    def _calc(tmp_path, temp=15.0, year=2021):
        epw_path = _write_constant_temp_epw(tmp_path / "t.epw", temp=temp, year=year)
        return DegreeHoursCalculator(epw_path, year=year)

    def test_daily_type_requires_one_value_per_day(self, tmp_path):
        calc = self._calc(tmp_path)
        config = {"type": "daily", "heating": [20.0] * 365, "cooling": [26.0] * 365}

        results = calc.calculate(config, frequency=["yearly"], save_session=False)
        assert "yearly" in results
        assert not results["yearly"].empty

    def test_daily_type_wrong_length_raises(self, tmp_path):
        calc = self._calc(tmp_path)
        config = {"type": "daily", "heating": [20.0] * 10, "cooling": [26.0] * 10}

        with pytest.raises(ValueError, match="expected 365 values"):
            calc.calculate(config, frequency=["yearly"], save_session=False)

    def test_weekly_type_with_weekday_weekend_pattern(self, tmp_path):
        calc = self._calc(tmp_path, temp=10.0)
        config = {
            "type": "weekly",
            "periods": {"winter": ("01-01", "12-31")},
            "patterns": {
                "winter": {
                    "weekday": {"heating": 21.0, "cooling": 26.0},
                    "weekend": {"heating": 18.0, "cooling": 27.0},
                }
            },
        }
        results = calc.calculate(config, frequency=["daily"], save_session=False)
        assert "daily" in results
        assert not results["daily"].empty

    def test_hourly_weekly_type_with_24_value_lists(self, tmp_path):
        calc = self._calc(tmp_path, temp=10.0)
        heating_profile = [16.0] * 8 + [21.0] * 16  # cooler at night, warmer by day
        config = {
            "type": "hourly_weekly",
            "periods": {"all_year": ("01-01", "12-31")},
            "patterns": {
                "all_year": {
                    "alldays": {"heating": heating_profile, "cooling": [26.0] * 24},
                }
            },
        }
        results = calc.calculate(config, frequency=["hourly"], mode="heating", save_session=False)
        hourly = results["hourly"]

        # Night hours (setpoint 16, T=10) -> HDH = 6; day hours (setpoint 21) -> HDH = 11.
        assert hourly["heating_dh"].iloc[0] == pytest.approx(6.0)
        assert hourly["heating_dh"].iloc[10] == pytest.approx(11.0)

    def test_unknown_type_raises_value_error(self, tmp_path):
        calc = self._calc(tmp_path)
        with pytest.raises(ValueError, match="Unknown configuration type"):
            calc.calculate({"type": "bogus"}, frequency=["yearly"], save_session=False)

