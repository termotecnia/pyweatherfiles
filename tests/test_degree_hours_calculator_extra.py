# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_calculator_extra.py
==============================================

Further tests for :mod:`pyweatherfiles.degree_hours.calculator`
(``DegreeHoursCalculator``), 61% covered before this file per
``INFORME_REVISION_GENERAL.md``'s coverage analysis (after
``tests/test_degree_hours_calculator_idf.py`` already covered the
``SCHEDULE:COMPACT``/``ZoneControl:Thermostat``/``IdealLoadsAirSystem``
availability path against the repo's real IDF). This file adds:

- ``calculate()``'s early validation branches (default/string ``frequency``,
  invalid ``frequency``/``mode``) and its session-save failure branch.
- ``_setpoints_from_dict()``'s ``'weekly'``/``'hourly_weekly'`` day-name-keyed
  pattern (e.g. ``'monday'``, not just ``'weekday'``/``'weekend'``/``'alldays'``)
  and its fallback date-parsing branch (a full ``'YYYY-MM-DD'`` period
  boundary instead of ``'MM-DD'``).
- ``plot()`` (0% previous coverage): every ``period`` value against a plain
  dict ``setpoint_source`` (``show_air_temp``, ``show_heating``/
  ``show_cooling`` toggles), its ``ValueError``/``TypeError`` guards, and —
  against the repo's real IDF (reusing the pattern of
  ``test_degree_hours_calculator_idf.py``) — the ``zone_name`` branch and the
  "mean across every zone, availability gaps become NaN" branch.
- ``SCHEDULE:YEAR`` -> ``SCHEDULE:WEEK:DAILY`` -> ``SCHEDULE:DAY:HOURLY`` /
  ``SCHEDULE:DAY:INTERVAL`` parsing (``_parse_year_schedule``,
  ``_parse_day_schedule``, both 0% previous coverage — the real IDF fixture
  only exercises ``SCHEDULE:COMPACT``), via a small synthetic IDF built here,
  including the weekday/weekend ``SCHEDULE:WEEK:DAILY`` field mapping.
- ``_schedule_to_series()``'s documented ``ValueError`` when a schedule name
  matches neither ``SCHEDULE:COMPACT`` nor ``SCHEDULE:YEAR``, and the "thermostat
  with no matching DualSetpoint at all" -> "no setpoints found" path.

Requires the optional ``besos``/``eppy`` dependencies (extra ``energyplus``)
for every IDF-based test; skipped automatically otherwise.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.degree_hours import DegreeHoursCalculator

besos = pytest.importorskip("besos")
pytest.importorskip("eppy")

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_IDF_PATH = REPO_ROOT / "SF_Detached_D_min_South.idf"

SETPOINTS = {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}

# A minimal, hand-built IDF exercising SCHEDULE:YEAR -> SCHEDULE:WEEK:DAILY ->
# SCHEDULE:DAY:HOURLY/SCHEDULE:DAY:INTERVAL, which the repo's real IDF fixture
# (SF_Detached_D_min_South.idf) never uses (it only has SCHEDULE:COMPACT).
# Heating (Schedule:Day:Hourly): weekdays 18 degC (00-07h) / 21 degC (07-24h);
# weekends 16 degC (00-09h) / 19 degC (09-24h) - deliberately different, to
# verify the SCHEDULE:WEEK:DAILY weekday/weekend field mapping.
# Cooling (Schedule:Day:Interval): 26 degC (00-16h) / 24 degC (16-24h), every day.
_SYNTHETIC_YEAR_SCHEDULE_IDF = """\
Version,
    9.6;

Building,
    TestBuilding,
    0.0,
    Suburbs,
    0.04,
    0.4,
    FullExterior,
    25,
    6;

Timestep,
    4;

ScheduleTypeLimits,
    Control Type,
    0,
    4,
    DISCRETE;

ScheduleTypeLimits,
    Temperature,
    -60,
    200,
    CONTINUOUS;

Zone,
    TestZone,
    0.0,
    0.0,
    0.0,
    0.0,
    ,
    1;

ZoneControl:Thermostat,
    TestZone Thermostat,
    TestZone,
    Always4CtrlType,
    ThermostatSetpoint:DualSetpoint,
    Dual SP;

Schedule:Compact,
    Always4CtrlType,
    Control Type,
    Through: 12/31,
    For: AllDays,
    Until: 24:00,
    4;

ThermostatSetpoint:DualSetpoint,
    Dual SP,
    Heating Setpoint Year,
    Cooling Setpoint Year;

Schedule:Year,
    Heating Setpoint Year,
    Temperature,
    HeatingWeek,
    1,
    1,
    12,
    31;

Schedule:Week:Daily,
    HeatingWeek,
    HeatingWeekend,
    HeatingWeekday,
    HeatingWeekday,
    HeatingWeekday,
    HeatingWeekday,
    HeatingWeekday,
    HeatingWeekend,
    HeatingWeekday,
    HeatingWeekday,
    HeatingWeekday;

Schedule:Day:Hourly,
    HeatingWeekday,
    Temperature,
    18,18,18,18,18,18,18,
    21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21;

Schedule:Day:Hourly,
    HeatingWeekend,
    Temperature,
    16,16,16,16,16,16,16,16,16,
    19,19,19,19,19,19,19,19,19,19,19,19,19,19,19;

Schedule:Year,
    Cooling Setpoint Year,
    Temperature,
    CoolingWeek,
    1,
    1,
    12,
    31;

Schedule:Week:Daily,
    CoolingWeek,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay,
    CoolingDay;

Schedule:Day:Interval,
    CoolingDay,
    Temperature,
    No,
    16:00,
    26,
    24:00,
    24;
"""

# A minimal IDF whose heating setpoint Schedule:Compact uses weekday-specific
# 'For:' rules (instead of 'For: AllDays', which is all the repo's real IDF
# fixture ever uses) - exercises the "find the first explicit day-type rule
# that matches this weekday" branch of _compact_ranges_to_series().
_SYNTHETIC_WEEKDAY_SPECIFIC_COMPACT_IDF = """\
Version,
    9.6;

Building,
    TestBuilding,
    0.0,
    Suburbs,
    0.04,
    0.4,
    FullExterior,
    25,
    6;

Timestep,
    4;

ScheduleTypeLimits,
    Control Type,
    0,
    4,
    DISCRETE;

ScheduleTypeLimits,
    Temperature,
    -60,
    200,
    CONTINUOUS;

Zone,
    TestZone,
    0.0,
    0.0,
    0.0,
    0.0,
    ,
    1;

ZoneControl:Thermostat,
    TestZone Thermostat,
    TestZone,
    Always4CtrlType,
    ThermostatSetpoint:DualSetpoint,
    Dual SP;

Schedule:Compact,
    Always4CtrlType,
    Control Type,
    Through: 12/31,
    For: AllDays,
    Until: 24:00,
    4;

ThermostatSetpoint:DualSetpoint,
    Dual SP,
    Heating Setpoint Weekday Specific,
    Cooling Setpoint Weekday Specific;

Schedule:Compact,
    Heating Setpoint Weekday Specific,
    Temperature,
    Through: 12/31,
    For: Weekends,
    Until: 24:00,
    16,
    For: Weekdays,
    Until: 24:00,
    21;

Schedule:Compact,
    Cooling Setpoint Weekday Specific,
    Temperature,
    Through: 12/31,
    For: AllDays,
    Until: 24:00,
    26;
"""

# A minimal IDF with a ZoneControl:Thermostat but NO ThermostatSetpoint:DualSetpoint
# at all, to exercise the "no dual setpoint found anywhere" -> "No setpoints
# found in the IDF" path.
_SYNTHETIC_NO_DUALSETPOINT_IDF = """\
Version,
    9.6;

Building,
    TestBuilding,
    0.0,
    Suburbs,
    0.04,
    0.4,
    FullExterior,
    25,
    6;

Timestep,
    4;

ScheduleTypeLimits,
    Control Type,
    0,
    4,
    DISCRETE;

Zone,
    TestZone,
    0.0,
    0.0,
    0.0,
    0.0,
    ,
    1;

ZoneControl:Thermostat,
    TestZone Thermostat,
    TestZone,
    Always4CtrlType,
    ThermostatSetpoint:DualSetpoint,
    Nonexistent Dual SP;

Schedule:Compact,
    Always4CtrlType,
    Control Type,
    Through: 12/31,
    For: AllDays,
    Until: 24:00,
    4;
"""


def _write_constant_temp_epw(path, temp, year=2021):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city="Test", latitude=37.0, longitude=-5.0, time_zone=1.0, elevation=10.0)
    epw.dry_bulb_temperature.values = [temp] * 8760
    epw.save(str(path))
    return str(path)


def _calc(tmp_path, temp=15.0, year=2021):
    epw_path = _write_constant_temp_epw(tmp_path / "t.epw", temp=temp, year=year)
    return DegreeHoursCalculator(epw_path, year=year)


class TestCalculateValidation:
    def test_default_frequency_computes_all_three(self, tmp_path):
        calc = _calc(tmp_path)
        results = calc.calculate(SETPOINTS, save_session=False)  # frequency=None
        assert set(results.keys()) == {"hourly", "daily", "monthly"}

    def test_string_frequency_is_wrapped_in_a_list(self, tmp_path):
        calc = _calc(tmp_path)
        results = calc.calculate(SETPOINTS, frequency="yearly", save_session=False)
        assert set(results.keys()) == {"yearly"}

    def test_invalid_frequency_raises_value_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(ValueError, match="Invalid frequencies"):
            calc.calculate(SETPOINTS, frequency=["bogus"], save_session=False)

    def test_invalid_mode_raises_value_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(ValueError, match="mode must be"):
            calc.calculate(SETPOINTS, frequency=["yearly"], mode="bogus", save_session=False)

    def test_invalid_setpoint_source_type_raises_type_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(TypeError, match="setpoint_source must be"):
            calc.calculate(12345, frequency=["yearly"], save_session=False)

    def test_session_save_failure_warns_but_does_not_raise(self, tmp_path, capsys):
        calc = _calc(tmp_path)
        not_a_dir = tmp_path / "not_a_directory.txt"
        not_a_dir.write_text("blocking file")

        calc.calculate(SETPOINTS, frequency=["yearly"], session_dir=str(not_a_dir))  # must not raise

        assert "Could not save the session" in capsys.readouterr().out

    def test_date_range_filtering_normal_and_wrapping(self, tmp_path):
        calc = _calc(tmp_path, temp=15.0)
        normal = calc.calculate(
            SETPOINTS, frequency=["yearly"], start_date="01/06", end_date="30/09", save_session=False,
        )
        assert "yearly" in normal

        # start_date > end_date -> wraps across year-end (e.g. a winter period).
        wrapping = calc.calculate(
            SETPOINTS, frequency=["yearly"], start_date="01/12", end_date="28/02", save_session=False,
        )
        assert "yearly" in wrapping

    def test_invalid_date_format_raises_value_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(ValueError, match="Invalid date format"):
            calc.calculate(SETPOINTS, frequency=["yearly"], start_date="not-a-date", save_session=False)


class TestSetpointsFromDictExtra:
    def test_weekly_type_with_specific_day_name_key(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        config = {
            "type": "weekly",
            "periods": {"all_year": ("01-01", "12-31")},
            "patterns": {
                "all_year": {
                    "monday": {"heating": 22.0, "cooling": 26.0},
                    "weekday": {"heating": 20.0, "cooling": 26.0},
                    "weekend": {"heating": 18.0, "cooling": 27.0},
                }
            },
        }
        results = calc.calculate(config, frequency=["daily"], mode="heating", save_session=False)
        daily = results["daily"]
        # 2021-01-04 is a Monday -> the 'monday'-specific pattern (22 degC) wins
        # over the more generic 'weekday' one (20 degC): HDH = (22-10)*24 = 288.
        monday_val = daily.loc["2021-01-04", "heating_dh"]
        assert monday_val == pytest.approx((22.0 - 10.0) * 24)
        # 2021-01-05 is a Tuesday -> falls back to the 'weekday' pattern (20 degC).
        tuesday_val = daily.loc["2021-01-05", "heating_dh"]
        assert tuesday_val == pytest.approx((20.0 - 10.0) * 24)

    def test_weekly_type_with_full_date_period_boundaries(self, tmp_path):
        # 'YYYY-MM-DD' boundaries (instead of 'MM-DD') make the first
        # pd.Timestamp(f'{year}-{start_str}') parse attempt fail, exercising
        # the except-fallback branch (pd.Timestamp(start_str).replace(year=...)).
        calc = _calc(tmp_path, temp=10.0, year=2021)
        config = {
            "type": "weekly",
            "periods": {"all_year": ("2021-01-01", "2021-12-31")},
            "patterns": {"all_year": {"alldays": {"heating": 20.0, "cooling": 26.0}}},
        }
        results = calc.calculate(config, frequency=["yearly"], mode="heating", save_session=False)
        assert results["yearly"]["heating_dh"].iloc[0] == pytest.approx((20.0 - 10.0) * 8760)


class TestPlotWithDictSetpoints:
    """plot() had 0% previous coverage; a plain dict setpoint_source avoids
    needing an IDF for most of its branches."""

    def test_period_year(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="year", show_air_temp=True)

    def test_period_month_single_value(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="month", period_value=6)

    def test_period_month_list_of_values(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="month", period_value=[1, 2])

    def test_period_week(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="week", period_value=10)

    def test_period_day_short_date_format(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="day", period_value="06-10", show_air_temp=True)

    def test_period_day_full_date_format_list(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0, year=2021)
        calc.plot(SETPOINTS, period="day", period_value=["2021-06-10", "2021-06-11"])

    def test_show_heating_false_only_cooling_plotted(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0)
        calc.plot(SETPOINTS, period="year", show_heating=False, show_cooling=True)

    def test_invalid_period_raises_value_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(ValueError, match="period must be"):
            calc.plot(SETPOINTS, period="bogus")

    def test_invalid_setpoint_source_type_raises_type_error(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(TypeError, match="setpoint_source must be str or dict"):
            calc.plot(12345, period="year")


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestPlotWithRealIdf:
    def test_specific_zone_name(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0, year=2021)
        calc.plot(str(REAL_IDF_PATH), period="year", zone_name="LivingRoom")

    def test_mean_across_all_zones_with_availability_gaps(self, tmp_path):
        # zone_name=None -> averages every zone's setpoint and applies each
        # zone's own availability mask (off periods become NaN gaps).
        calc = _calc(tmp_path, temp=10.0, year=2021)
        calc.plot(str(REAL_IDF_PATH), period="month", period_value=[1, 7], show_air_temp=True)


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestScheduleToSeriesValueError:
    def test_unresolvable_schedule_name_raises_value_error(self, tmp_path):
        calc = _calc(tmp_path, temp=10.0, year=2021)
        idf = besos.eppy_funcs.get_building(str(REAL_IDF_PATH))
        with pytest.raises(ValueError, match="Could not parse schedule"):
            calc._schedule_to_series(idf, "Totally Nonexistent Schedule Name")


class TestNoDualSetpointFoundAtAll:
    def test_raises_no_setpoints_found(self, tmp_path):
        idf_path = tmp_path / "no_dualsetpoint.idf"
        idf_path.write_text(_SYNTHETIC_NO_DUALSETPOINT_IDF)
        calc = _calc(tmp_path, temp=10.0, year=2021)

        with pytest.raises(ValueError, match="No setpoints found in the IDF"):
            calc.extract_setpoints_from_idf(str(idf_path))


class TestScheduleYearAndDayParsing:
    """SCHEDULE:YEAR -> SCHEDULE:WEEK:DAILY -> SCHEDULE:DAY:HOURLY/INTERVAL,
    against a small hand-built synthetic IDF (the repo's real IDF fixture
    only ever uses SCHEDULE:COMPACT for setpoints)."""

    @pytest.fixture
    def synthetic_idf_path(self, tmp_path):
        idf_path = tmp_path / "synthetic_year_schedule.idf"
        idf_path.write_text(_SYNTHETIC_YEAR_SCHEDULE_IDF)
        return str(idf_path)

    def test_heating_schedule_day_hourly_weekday_vs_weekend(self, tmp_path, synthetic_idf_path):
        calc = _calc(tmp_path, temp=10.0, year=2021)
        setpoints = calc.extract_setpoints_from_idf(synthetic_idf_path, zone_name="TestZone")
        heating = setpoints["TestZone"]["heating"]

        # 2021-01-04 is a Monday (weekday) -> 18 (00-07h) / 21 (07-24h).
        monday = heating[heating.index.date == pd.Timestamp("2021-01-04").date()]
        assert monday.iloc[0] == pytest.approx(18.0)
        assert monday.iloc[10] == pytest.approx(21.0)

        # 2021-01-02 is a Saturday (weekend) -> 16 (00-09h) / 19 (09-24h).
        saturday = heating[heating.index.date == pd.Timestamp("2021-01-02").date()]
        assert saturday.iloc[0] == pytest.approx(16.0)
        assert saturday.iloc[10] == pytest.approx(19.0)

    def test_cooling_schedule_day_interval(self, tmp_path, synthetic_idf_path):
        calc = _calc(tmp_path, temp=10.0, year=2021)
        setpoints = calc.extract_setpoints_from_idf(synthetic_idf_path, zone_name="TestZone")
        cooling = setpoints["TestZone"]["cooling"]

        assert cooling.iloc[0] == pytest.approx(26.0)   # hour 0 -> before 16:00
        assert cooling.iloc[17] == pytest.approx(24.0)  # hour 17 -> after 16:00

    def test_calculate_end_to_end_with_year_schedule(self, tmp_path, synthetic_idf_path):
        calc = _calc(tmp_path, temp=0.0, year=2021)  # very cold -> always heating
        results = calc.calculate(
            synthetic_idf_path, frequency=["hourly"], mode="heating",
            zone_name="TestZone", save_session=False,
        )
        hourly = results["hourly"]
        monday = hourly[hourly.index.date == pd.Timestamp("2021-01-04").date()]
        assert monday["heating_dh"].iloc[0] == pytest.approx(18.0)   # setpoint 18, T=0
        assert monday["heating_dh"].iloc[10] == pytest.approx(21.0)  # setpoint 21, T=0


class TestScheduleCompactWeekdaySpecificRules:
    """Schedule:Compact with 'For: Weekdays'/'For: Weekends' (instead of the
    real IDF fixture's 'For: AllDays' only) - exercises the "find the first
    explicit day-type rule that matches this weekday" branch of
    _compact_ranges_to_series()."""

    def test_different_setpoint_on_weekday_vs_weekend(self, tmp_path):
        idf_path = tmp_path / "weekday_specific.idf"
        idf_path.write_text(_SYNTHETIC_WEEKDAY_SPECIFIC_COMPACT_IDF)
        calc = _calc(tmp_path, temp=10.0, year=2021)

        setpoints = calc.extract_setpoints_from_idf(str(idf_path), zone_name="TestZone")
        heating = setpoints["TestZone"]["heating"]

        # 2021-01-04 is a Monday (weekday) -> 21 degC.
        assert heating[heating.index.date == pd.Timestamp("2021-01-04").date()].iloc[0] == pytest.approx(21.0)
        # 2021-01-02 is a Saturday (weekend) -> 16 degC.
        assert heating[heating.index.date == pd.Timestamp("2021-01-02").date()].iloc[0] == pytest.approx(16.0)


class TestInitValidation:
    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="EPW file not found"):
            DegreeHoursCalculator("does_not_exist.epw")


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestLoadIdfDirect:
    """_load_idf() is currently unreachable from any public method
    (extract_setpoints_from_idf calls besos.get_building directly instead —
    see the commented-out call at its top), but it remains part of the
    class's public surface and is tested directly here."""

    def test_loads_idf_via_besos(self, tmp_path):
        calc = _calc(tmp_path)
        idf = calc._load_idf(str(REAL_IDF_PATH))
        assert idf is not None


@pytest.mark.skipif(not REAL_IDF_PATH.exists(), reason="Repo-root IDF fixture not found")
class TestCalculateWithMeanAcrossZones:
    def test_zone_name_none_averages_setpoints_and_ands_availability(self, tmp_path):
        # zone_name=None (the default) averages every zone's setpoint series
        # and combines their availability masks (mean > 0 => active).
        calc = _calc(tmp_path, temp=-5.0, year=2021)
        results = calc.calculate(
            str(REAL_IDF_PATH), frequency=["monthly"], mode="heating", save_session=False,
        )
        monthly = results["monthly"]
        assert monthly["heating_dh"].iloc[0] > 0     # January: heating available
        assert monthly["heating_dh"].iloc[6] == pytest.approx(0.0)  # July: unavailable


class TestExportResults:
    def test_raises_before_calculate(self, tmp_path):
        calc = _calc(tmp_path)
        with pytest.raises(ValueError, match="No results to export"):
            calc.export_results()

    def test_exports_only_computed_frequencies(self, tmp_path):
        calc = _calc(tmp_path, temp=15.0)
        calc.calculate(SETPOINTS, frequency=["monthly"], save_session=False)
        out_path = tmp_path / "dh_results.xlsx"

        result_path = calc.export_results(str(out_path))

        assert result_path == str(out_path.resolve()) or result_path == str(out_path)
        sheets = pd.read_excel(out_path, sheet_name=None)
        assert set(sheets.keys()) == {"monthly"}





