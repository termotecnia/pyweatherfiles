# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_batch_analyzer.py
============================================

Tests for :mod:`pyweatherfiles.degree_hours.batch_analyzer`
(``EpwBatchAnalyzer``), 59% covered before this file per
``INFORME_REVISION_GENERAL.md``'s coverage analysis.
``tests/test_degree_hours_package.py`` already smoke-tests the ``run()`` ->
``export()`` happy path with two EPWs and default ``hours``/``epw_variables``
(monthly frequency only); this file adds:

- The constructor's ``ValueError`` for an empty ``epw_paths``.
- ``_resolve_hours()`` (via ``run()``): every input shape (``None``, a plain
  list of ints, a list of lists — including one with an empty sub-list —,
  and the dict form) plus the documented ``TypeError``.
- ``_resolve_epw_variables()`` (via ``run()``): the default, list ("auto"
  aggregation, sum for radiation vars vs. mean otherwise) and dict (explicit
  aggregation(s), column-name suffixing) forms, plus the documented
  ``TypeError``.
- ``run()``: a missing EPW file (skipped with a warning, not fatal), the
  ``RuntimeError`` when nothing could be processed, an EPW variable absent
  from a specific file's data (warning), ``start_date``/``end_date``
  filtering (both a normal range and one that wraps across year-end) plus
  its ``ValueError`` on an invalid date, every ``frequencies`` value
  (``'hourly'``/``'daily'`` use a ``DatetimeIndex`` unlike ``'monthly'``/
  ``'yearly'``, already covered), multiple frequencies at once, and
  ``save_session=True``.
- ``export()``: the ``ValueError`` guard, and the "only combined sheets"
  branch when more than one frequency was requested (only the
  single-frequency branch, with per-EPW sheets, was tested before).
"""

import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.degree_hours import EpwBatchAnalyzer

SETPOINTS = {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}


def _write_synthetic_epw(path, city, temp=20.0, ghi=None, wind=None):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city=city, latitude=40.0, longitude=-3.0, time_zone=1.0, elevation=100.0)
    epw.dry_bulb_temperature.values = [temp] * 8760
    if ghi is not None:
        epw.global_horizontal_radiation.values = [ghi] * 8760
    if wind is not None:
        epw.wind_speed.values = [wind] * 8760
    epw.save(str(path))
    return str(path)


class TestConstructorValidation:
    def test_raises_for_empty_epw_paths(self):
        with pytest.raises(ValueError, match="epw_paths"):
            EpwBatchAnalyzer(epw_paths=[], setpoint_source=SETPOINTS)


class TestResolveHours:
    def test_none_defaults_to_24h(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, hours=None, frequencies=["yearly"])
        results = batch.run(save_session=False)
        assert "heating_dh_24h" in results["yearly"]["city_2020"].columns

    def test_single_list_of_ints(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, hours=list(range(8)), frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        cols = list(results["yearly"]["city_2020"].columns)
        assert any(c.startswith("heating_dh_0-8h") for c in cols)

    def test_list_of_lists_generates_one_scenario_per_sublist(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            hours=[list(range(8)), [1, 3, 5]], frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        cols = list(results["yearly"]["city_2020"].columns)
        assert any("0-8h" in c for c in cols)
        assert any("1_3_5h" in c for c in cols)

    def test_list_of_lists_with_empty_sublist(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, hours=[[]], frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        cols = list(results["yearly"]["city_2020"].columns)
        assert any("empty" in c for c in cols)

    def test_dict_form_used_verbatim_as_labels(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            hours={"morning": list(range(9))}, frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        cols = list(results["yearly"]["city_2020"].columns)
        assert any("morning" in c for c in cols)

    def test_invalid_type_raises_type_error(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, hours="not-valid")
        with pytest.raises(TypeError, match="hours must be"):
            batch.run(save_session=False)


class TestResolveEpwVariables:
    def test_default_when_none_is_radiation_sum(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0, ghi=500.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"])
        results = batch.run(save_session=False)
        df = results["yearly"]["city_2020"]
        assert df["global_horizontal_radiation_24h"].iloc[0] == pytest.approx(500.0 * 8760)

    def test_list_form_auto_detects_aggregation(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0, ghi=500.0, wind=3.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            epw_variables=["global_horizontal_radiation", "wind_speed"], frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        df = results["yearly"]["city_2020"]
        # radiation var -> sum aggregation; non-radiation var -> mean
        assert df["global_horizontal_radiation_24h"].iloc[0] == pytest.approx(500.0 * 8760)
        assert df["wind_speed_24h"].iloc[0] == pytest.approx(3.0)

    def test_dict_form_with_multiple_aggs_suffixes_column_names(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            epw_variables={"dry_bulb_temperature": ["mean", "max", "min"]}, frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        cols = list(results["yearly"]["city_2020"].columns)
        assert "dry_bulb_temperature_mean_24h" in cols
        assert "dry_bulb_temperature_max_24h" in cols
        assert "dry_bulb_temperature_min_24h" in cols

    def test_dict_form_single_agg_string(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            epw_variables={"dry_bulb_temperature": "mean"}, frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        # dict form -> use_suffix=True even with a single aggfunc
        assert "dry_bulb_temperature_mean_24h" in results["yearly"]["city_2020"].columns

    def test_invalid_type_raises_type_error(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, epw_variables="not-valid")
        with pytest.raises(TypeError, match="epw_variables must be"):
            batch.run(save_session=False)


class TestRunFileHandling:
    def test_missing_file_is_skipped_with_warning(self, tmp_path, capsys):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        missing = str(tmp_path / "does_not_exist.epw")
        batch = EpwBatchAnalyzer(epw_paths=[p, missing], setpoint_source=SETPOINTS, frequencies=["yearly"])
        results = batch.run(save_session=False)
        assert list(results["yearly"].columns.get_level_values("epw").unique()) == ["city_2020"]
        assert "EPW not found, skipping" in capsys.readouterr().out

    def test_raises_when_no_files_processed(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.epw")
        batch = EpwBatchAnalyzer(epw_paths=[missing], setpoint_source=SETPOINTS)
        with pytest.raises(RuntimeError, match="No EPW files could be processed"):
            batch.run(save_session=False)

    def test_variable_not_in_epw_data_warns(self, tmp_path, capsys):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS,
            epw_variables=["nonexistent_variable"], frequencies=["yearly"],
        )
        results = batch.run(save_session=False)
        assert "not in EPW data" in capsys.readouterr().out
        assert "nonexistent_variable_24h" not in results["yearly"]["city_2020"].columns

    def test_save_session_creates_pkl(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"])
        batch.run(save_session=True, session_dir=str(tmp_path))
        assert list(tmp_path.glob("EpwBatchAnalyzer_*.pkl"))

    def test_session_save_failure_warns_but_does_not_raise(self, tmp_path, capsys):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        not_a_dir = tmp_path / "not_a_directory.txt"
        not_a_dir.write_text("blocking file")  # os.makedirs(exist_ok=True) will fail on this
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"])

        batch.run(save_session=True, session_dir=str(not_a_dir))  # must not raise

        assert "Could not save the session" in capsys.readouterr().out


class TestDateRangeFiltering:
    def test_normal_range(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"],
            start_date="01/06", end_date="30/09",
        )
        results = batch.run(save_session=False)
        assert "heating_dh_24h" in results["yearly"]["city_2020"].columns

    def test_wrapping_range_end_before_start(self, tmp_path):
        # start_date > end_date -> wraps across year-end (e.g. a winter period)
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"],
            start_date="01/12", end_date="28/02",
        )
        results = batch.run(save_session=False)
        assert "heating_dh_24h" in results["yearly"]["city_2020"].columns

    def test_invalid_date_format_raises_value_error(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["yearly"],
            start_date="not-a-date",
        )
        with pytest.raises(ValueError, match="Invalid date format"):
            batch.run(save_session=False)


class TestFrequencyHandling:
    def test_hourly_frequency_keeps_datetime_index(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0, ghi=500.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["hourly"],
            epw_variables=["global_horizontal_radiation"],
        )
        results = batch.run(save_session=False)
        df = results["hourly"]["city_2020"]
        assert df.index.name == "datetime"
        assert len(df) == 8760
        assert df["global_horizontal_radiation_24h"].iloc[0] == pytest.approx(500.0)

    def test_hourly_frequency_with_explicit_aggfunc_keeps_series_unresampled(self, tmp_path):
        # Explicit (non-'auto') aggfunc + hourly frequency: resample() would be
        # meaningless at hourly granularity, so the raw series is kept as-is.
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["hourly"],
            epw_variables={"dry_bulb_temperature": "mean"},
        )
        results = batch.run(save_session=False)
        df = results["hourly"]["city_2020"]
        assert df["dry_bulb_temperature_mean_24h"].iloc[0] == pytest.approx(15.0)

    def test_daily_frequency_keeps_datetime_index(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["daily"])
        results = batch.run(save_session=False)
        df = results["daily"]["city_2020"]
        assert df.index.name == "datetime"
        assert len(df) == 365

    def test_multiple_frequencies_at_once(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS, frequencies=["monthly", "yearly"])
        results = batch.run(save_session=False)
        assert set(results.keys()) == {"monthly", "yearly"}


class TestExport:
    def test_raises_before_run(self, tmp_path):
        p = _write_synthetic_epw(tmp_path / "city_2020.epw", "city", temp=15.0)
        batch = EpwBatchAnalyzer(epw_paths=[p], setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            batch.export()

    def test_multiple_frequencies_only_creates_combined_sheets(self, tmp_path):
        p1 = _write_synthetic_epw(tmp_path / "cityA_2020.epw", "cityA", temp=15.0)
        p2 = _write_synthetic_epw(tmp_path / "cityB_2020.epw", "cityB", temp=25.0)
        batch = EpwBatchAnalyzer(
            epw_paths=[p1, p2], setpoint_source=SETPOINTS, frequencies=["monthly", "yearly"],
        )
        batch.run(save_session=False)
        out_path = tmp_path / "batch.xlsx"

        batch.export(str(out_path))

        sheets = pd.read_excel(out_path, sheet_name=None)
        assert "all_epws_monthly" in sheets
        assert "all_epws_yearly" in sheets
        assert "cityA_2020" not in sheets  # only combined sheets when >1 frequency



