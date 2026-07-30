# -*- coding: utf-8 -*-
"""
tests/test_hourly_epw_converter_extra.py
===========================================

Additional tests for :mod:`pyweatherfiles.hourly_epw_converter`
(``HourlyEPWConverter`` was 55% covered before this file per
``INFORME_REVISION_GENERAL.md``'s Fase 2 coverage analysis, since
``tests/test_regression_epw_pipeline.py``'s single end-to-end test only
exercises the simplest "happy path": one non-leap year, RH/pressure/DHI all
reconstructed, no separate hourly file, no ``BatchHourlyEPWConverter``, and
no error handling). This file complements it, focusing on the branches not
previously exercised: leap-year handling, optional columns (wind direction,
cloud cover, IRH), error handling in ``__init__``/``transform_to_epw``,
multi-year ``process()``, session persistence, and the whole
``BatchHourlyEPWConverter`` class.
"""

import numpy as np
import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.hourly_epw_converter import BatchHourlyEPWConverter, HourlyEPWConverter

LAT, LON, ELEV, TZ = 37.38, -5.98, 15.0, 1.0


@pytest.fixture
def base_epw_path(tmp_path):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city="TestCity", latitude=LAT, longitude=LON, time_zone=TZ, elevation=ELEV)
    path = tmp_path / "template.epw"
    epw.save(str(path))
    return str(path)


def _hourly_df(year, extra_cols=None):
    idx = pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:00", freq="h")
    n = len(idx)
    data = {
        "time": idx,
        "Dry-bulb temperature": np.full(n, 18.0),
        "Dew Point temperature": np.full(n, 10.0),
        "Wind Speed": np.full(n, 10.8),  # km/h -> 3.0 m/s
        "Global Horizontal Irradiance ": np.clip(300 * np.sin(np.linspace(0, 40 * np.pi, n)), 0, None),
        "Beam Normal Irradiance ": np.clip(400 * np.sin(np.linspace(0, 40 * np.pi, n)), 0, None),
    }
    if extra_cols:
        data.update(extra_cols)
    return pd.DataFrame(data)


class TestInitErrorHandling:
    def test_raises_when_geographic_params_cannot_be_determined(self, tmp_path):
        # base_epw_path points at a file that is not a valid EPW at all.
        bad_epw = tmp_path / "not_an_epw.epw"
        bad_epw.write_text("this is not a real EPW file")

        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)

        with pytest.raises(ValueError, match="Could not determine all geographic parameters"):
            HourlyEPWConverter(file_path=str(csv_path), base_epw_path=str(bad_epw))

    def test_explicit_lat_lon_elev_tz_bypass_extraction(self, tmp_path):
        bad_epw = tmp_path / "not_an_epw.epw"
        bad_epw.write_text("not a real EPW")
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)

        converter = HourlyEPWConverter(
            file_path=str(csv_path), base_epw_path=str(bad_epw),
            lat=1.0, lon=2.0, elev=3.0, tz_hour=1.0,
        )
        assert converter.lat == 1.0
        assert converter.tz_hour == 1.0


class TestLoadFile:
    def test_reads_xlsx_source(self, tmp_path, base_epw_path):
        xlsx_path = tmp_path / "data.xlsx"
        _hourly_df(2015).to_excel(xlsx_path, index=False)

        converter = HourlyEPWConverter(file_path=str(xlsx_path), base_epw_path=base_epw_path)
        assert converter.available_years == [2015]

    def test_wind_speed_converted_from_kmh_to_ms(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)

        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)
        assert converter.df["Wind Speed"].iloc[0] == pytest.approx(3.0)


class TestGetYearData:
    def test_unavailable_year_raises(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        with pytest.raises(ValueError, match="is not available in this file"):
            converter.get_year_data(1999)


class TestTransformToEpwOptionalColumns:
    def test_wind_direction_defaults_to_zero_when_absent(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        out_path = tmp_path / "out.epw"
        ok = converter.transform_to_epw(converter.get_year_data(2015), str(out_path))
        assert ok is True
        epw = EPW(str(out_path))
        assert list(epw.wind_direction.values)[0] == 0

    def test_wind_direction_used_when_present(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        df = _hourly_df(2015, extra_cols={"Wind Direction": np.full(8760, 90.0)})
        df.to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        out_path = tmp_path / "out.epw"
        converter.transform_to_epw(converter.get_year_data(2015), str(out_path))
        epw = EPW(str(out_path))
        assert list(epw.wind_direction.values)[0] == pytest.approx(90.0)

    def test_cloud_cover_and_irh_injected_when_present(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        df = _hourly_df(2015, extra_cols={
            "Total Cloud Cover": np.full(8760, 5.0),
            "IRh": np.full(8760, 350.0),
        })
        df.to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path, preserve_extra=True)

        out_path = tmp_path / "out.epw"
        converter.transform_to_epw(converter.get_year_data(2015), str(out_path))
        epw = EPW(str(out_path))
        assert list(epw.total_sky_cover.values)[0] == pytest.approx(5.0)
        assert list(epw.horizontal_infrared_radiation_intensity.values)[0] == pytest.approx(350.0)

    def test_relative_humidity_column_used_when_present(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        df = _hourly_df(2015, extra_cols={"Relative Humidity": np.full(8760, 65.0)})
        df.to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        out_path = tmp_path / "out.epw"
        converter.transform_to_epw(converter.get_year_data(2015), str(out_path))
        epw = EPW(str(out_path))
        assert list(epw.relative_humidity.values)[0] == pytest.approx(65.0)


class TestTransformToEpwLeapYear:
    def test_remove_leap_day_true_produces_8760_hours(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2016).to_csv(csv_path, index=False)  # 2016 is a leap year
        converter = HourlyEPWConverter(
            file_path=str(csv_path), base_epw_path=base_epw_path, remove_leap_day=True,
        )
        out_path = tmp_path / "out.epw"
        converter.transform_to_epw(converter.get_year_data(2016), str(out_path))
        epw = EPW(str(out_path))
        assert len(list(epw.dry_bulb_temperature.values)) == 8760

    def test_remove_leap_day_false_keeps_8784_hours(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        # Explicit DHI column so Feb 29th does not need the Sunpath-based
        # reconstruction (ladybug's Sunpath.calculate_sun() has no
        # leap-year support and would raise for month=2, day=29).
        df = _hourly_df(2016, extra_cols={"Diffuse Horizontal Irradiance": np.full(8784, 50.0)})
        df.to_csv(csv_path, index=False)

        # The base EPW template must itself be a leap-year template (8784
        # hours): transform_to_epw() only swaps the AnalysisPeriod object,
        # it does not retroactively resize each DataCollection's expected
        # length, so a regular (8760-hour) template can never accept 8784
        # values regardless of remove_leap_day.
        leap_epw = tmp_path / "leap_template.epw"
        EPW.from_missing_values(is_leap_year=True).save(str(leap_epw))
        leap_epw_obj = EPW(str(leap_epw))
        leap_epw_obj.location = Location(city="TestCity", latitude=LAT, longitude=LON, time_zone=TZ, elevation=ELEV)
        leap_epw_obj.save(str(leap_epw))

        converter = HourlyEPWConverter(
            file_path=str(csv_path), base_epw_path=str(leap_epw), remove_leap_day=False,
        )
        out_path = tmp_path / "out.epw"
        ok = converter.transform_to_epw(converter.get_year_data(2016), str(out_path), base_epw_path=str(leap_epw))
        assert ok is True
        epw = EPW(str(out_path))
        assert len(list(epw.dry_bulb_temperature.values)) == 8784


class TestTransformToEpwErrorHandling:
    def test_invalid_base_epw_path_returns_false(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        out_path = tmp_path / "out.epw"
        ok = converter.transform_to_epw(
            converter.get_year_data(2015), str(out_path), base_epw_path="does_not_exist.epw",
        )
        assert ok is False

    def test_fewer_hours_than_expected_warns_before_failing(self, tmp_path, base_epw_path, capsys):
        # Documents a known limitation: transform_to_epw() prints a warning
        # when df_year has fewer rows than a full year, but does not pad
        # the series to match the EPW template's AnalysisPeriod length, so
        # assigning the resulting short series to the EPW object still
        # raises further down (ladybug enforces an exact length match).
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        partial_year = converter.get_year_data(2015).iloc[:100]  # far fewer than 8760
        out_path = tmp_path / "out.epw"
        with pytest.raises(AssertionError, match="Length of values does not match"):
            converter.transform_to_epw(partial_year, str(out_path))
        assert "only has 100 hours available" in capsys.readouterr().out


class TestProcessMultiYear:
    def test_processes_multiple_years_and_skips_unavailable_ones(self, tmp_path, base_epw_path, capsys):
        csv_path = tmp_path / "data.csv"
        combined = pd.concat([_hourly_df(2015), _hourly_df(2016)], ignore_index=True)
        combined.to_csv(csv_path, index=False)

        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)
        success = converter.process(
            output_dir=str(tmp_path), years=[2015, 2016, 1999],
            output_pattern="city_{year}.epw", save_session=False,
        )
        assert success == [2015, 2016]
        assert (tmp_path / "city_2015.epw").exists()
        assert (tmp_path / "city_2016.epw").exists()
        assert "Year 1999 not found in the data" in capsys.readouterr().out

    def test_output_pattern_with_unknown_key_falls_back_to_default_name(self, tmp_path, base_epw_path, capsys):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        success = converter.process(
            output_dir=str(tmp_path), years=[2015],
            output_pattern="{unknown_key}_{year}.epw", save_session=False,
        )
        assert success == [2015]
        assert "Filename format failed with KeyError" in capsys.readouterr().out
        # Falls back to '{source_basename}_{year}.epw'.
        assert (tmp_path / "data_2015.epw").exists()

    def test_save_session_creates_pkl_and_json(self, tmp_path, base_epw_path):
        csv_path = tmp_path / "data.csv"
        _hourly_df(2015).to_csv(csv_path, index=False)
        converter = HourlyEPWConverter(file_path=str(csv_path), base_epw_path=base_epw_path)

        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        converter.process(
            output_dir=str(tmp_path), years=[2015], output_pattern="out.epw",
            save_session=True, session_dir=str(session_dir),
        )
        assert list(session_dir.glob("*.pkl"))
        assert list(session_dir.glob("*.json"))


class TestBatchHourlyEPWConverter:
    def test_get_mandatory_config_keys(self, capsys):
        keys = BatchHourlyEPWConverter.get_mandatory_config_keys()
        assert keys == ["file_path", "base_epw_path"]
        assert "mandatory configuration keys" in capsys.readouterr().out

    def test_init_accepts_dataframe_config(self):
        df = pd.DataFrame([{"file_path": "a.csv", "base_epw_path": "a.epw"}])
        batch = BatchHourlyEPWConverter(df)
        assert batch.cities_config == [{"file_path": "a.csv", "base_epw_path": "a.epw"}]

    def test_suggest_config_matches_by_identifier(self, tmp_path, base_epw_path):
        city_csv = tmp_path / "SEVILLE_data.csv"
        _hourly_df(2015).to_csv(city_csv, index=False)

        # suggest_config() matches by substring in the *file name*, so the
        # EPW template also needs "seville" in its own name (the shared
        # base_epw_path fixture is named "template.epw", which would never match).
        seville_epw = tmp_path / "SEVILLE_template.epw"
        EPW(base_epw_path).save(str(seville_epw))

        config = BatchHourlyEPWConverter.suggest_config(
            identifiers=["SEVILLE"], data_files=[str(city_csv)], base_epw_files=[str(seville_epw)],
        )
        assert len(config) == 1
        assert config[0]["identifier"] == "SEVILLE"
        assert config[0]["lat"] == pytest.approx(LAT)

    def test_suggest_config_skips_unmatched_identifier(self, tmp_path, base_epw_path, capsys):
        city_csv = tmp_path / "SEVILLE_data.csv"
        _hourly_df(2015).to_csv(city_csv, index=False)

        config = BatchHourlyEPWConverter.suggest_config(
            identifiers=["MADRID"], data_files=[str(city_csv)], base_epw_files=[base_epw_path],
        )
        assert config == []
        assert "Could not find a match for 'MADRID'" in capsys.readouterr().out

    def test_process_all_runs_multiple_cities(self, tmp_path, base_epw_path):
        csv_a = tmp_path / "cityA.csv"
        csv_b = tmp_path / "cityB.csv"
        _hourly_df(2015).to_csv(csv_a, index=False)
        _hourly_df(2015).to_csv(csv_b, index=False)

        batch = BatchHourlyEPWConverter(
            [
                {"file_path": str(csv_a), "base_epw_path": base_epw_path, "identifier": "A"},
                {"file_path": str(csv_b), "base_epw_path": base_epw_path, "identifier": "B"},
            ],
            output_dir=str(tmp_path),
        )
        results = batch.process_all(output_pattern="{identifier}_{year}.epw", save_session=False)

        assert results[str(csv_a)] == [2015]
        assert results[str(csv_b)] == [2015]
        assert (tmp_path / "A_2015.epw").exists()
        assert (tmp_path / "B_2015.epw").exists()

    def test_process_all_skips_entry_missing_mandatory_key(self, tmp_path, capsys):
        batch = BatchHourlyEPWConverter([{"file_path": "only_this.csv"}], output_dir=str(tmp_path))
        results = batch.process_all(save_session=False)

        assert results == {}
        assert "missing the mandatory attributes" in capsys.readouterr().out

    def test_process_all_saves_batch_session(self, tmp_path, base_epw_path):
        csv_a = tmp_path / "cityA.csv"
        _hourly_df(2015).to_csv(csv_a, index=False)

        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        batch = BatchHourlyEPWConverter(
            [{"file_path": str(csv_a), "base_epw_path": base_epw_path, "identifier": "A"}],
            output_dir=str(tmp_path),
        )
        batch.process_all(
            output_pattern="{identifier}_{year}.epw", save_session=True, session_dir=str(session_dir),
        )
        assert list(session_dir.glob("BatchHourlyEPWConverter*.pkl"))





