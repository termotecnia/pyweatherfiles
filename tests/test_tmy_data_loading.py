# -*- coding: utf-8 -*-
"""
tests/test_tmy_data_loading.py
=================================

Unit tests for :class:`pyweatherfiles.tmy._data_loading._DataLoadingMixin`
(Step 1 of the Sandia TMY workflow — 40% coverage before this file per
``INFORME_REVISION_GENERAL.md``'s Fase 2 coverage analysis, since
``tests/test_tmy_package.py``'s smoke tests only ever exercised the
simplest hourly-CSV-with-GHI path).

Covers the branches not previously exercised by any test: loading from
Excel, ``years_to_include`` validation, missing GHI/DNI placeholders,
negative-value clipping, the entire ``data_frequency='daily'`` branch, and
the entire separate ``hourly_file_path`` branch (including cross-filtering
hourly data to the months available in the daily file).
"""

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles import TMYGenerator

YEARS = list(range(2015, 2021))  # 6 years


def _hourly_frame(years, ghi=True, dni=False, negative=False, seed=1):
    rng = np.random.default_rng(seed)
    frames = []
    for year in years:
        idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz="UTC")
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
        n = len(idx)
        data = {
            "time": idx,
            "T_air": rng.normal(15, 5, n),
            "T_dew": rng.normal(8, 3, n),
            "Wind_speed": np.abs(rng.normal(2, 1, n)),
        }
        if ghi:
            data["GHI"] = np.abs(rng.normal(300, 100, n))
        if dni:
            data["DNI"] = np.abs(rng.normal(400, 100, n))
        if negative:
            data["Wind_speed"] = data["Wind_speed"] - 5.0  # force some negatives
            if ghi:
                data["GHI"] = data["GHI"] - 500.0
        frames.append(pd.DataFrame(data))
    return pd.concat(frames, ignore_index=True)


def _daily_frame(years, include_ghi=True, include_standard=True):
    rows = []
    for year in years:
        idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
        n = len(idx)
        data = {"time": idx}
        if include_standard:
            data["T_air_mean"] = np.linspace(5, 25, n)
            data["T_air_max"] = data["T_air_mean"] + 5
            data["T_air_min"] = data["T_air_mean"] - 5
            data["T_dew_mean"] = data["T_air_mean"] - 5
            data["T_dew_max"] = data["T_dew_mean"] + 2
            data["T_dew_min"] = data["T_dew_mean"] - 2
            data["Wind_speed_mean"] = np.full(n, 2.0)
            data["Wind_speed_max"] = np.full(n, 5.0)
        if include_ghi:
            data["GHI_sum"] = np.full(n, 4000.0)
        rows.append(pd.DataFrame(data))
    return pd.concat(rows, ignore_index=True)


class TestLoadFromExcel:
    def test_reads_xlsx_source_file(self, tmp_path):
        df = _hourly_frame(YEARS)
        df["time"] = df["time"].dt.tz_localize(None)  # Excel does not support tz-aware datetimes
        xlsx_path = tmp_path / "weather.xlsx"
        df.to_excel(xlsx_path, index=False)

        gen = TMYGenerator(file_path=str(xlsx_path), data_frequency="hourly", save_session=False)
        gen.sandia_step_1_load_and_prepare()

        assert gen.df_hourly is not None
        assert "T_air" in gen.df_hourly.columns


class TestYearsToInclude:
    def test_missing_requested_year_raises(self, tmp_path):
        df = _hourly_frame(YEARS)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(
            file_path=str(csv_path), data_frequency="hourly",
            years_to_include=[2015, 2099], save_session=False,
        )
        with pytest.raises(ValueError, match="Requested years not found"):
            gen.sandia_step_1_load_and_prepare()

    def test_filters_to_requested_years_only(self, tmp_path):
        df = _hourly_frame(YEARS)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(
            file_path=str(csv_path), data_frequency="hourly",
            years_to_include=[2015, 2016], save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()
        assert set(gen.df_hourly.index.year.unique()) == {2015, 2016}


class TestHourlyGhiDniHandling:
    def test_missing_ghi_creates_zero_placeholder(self, tmp_path, capsys):
        df = _hourly_frame(YEARS, ghi=False)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="hourly", save_session=False)
        gen.sandia_step_1_load_and_prepare()

        assert "GHI" in gen.df_hourly.columns
        assert (gen.df_hourly["GHI"] == 0.0).all()
        assert "'GHI' data not found" in capsys.readouterr().out

    def test_dni_column_is_preserved_when_present(self, tmp_path):
        df = _hourly_frame(YEARS, dni=True)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="hourly", save_session=False)
        gen.sandia_step_1_load_and_prepare()

        assert "DNI" in gen.df_hourly.columns

    def test_negative_values_are_clipped_to_zero(self, tmp_path, capsys):
        df = _hourly_frame(YEARS, negative=True)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="hourly", save_session=False)
        gen.sandia_step_1_load_and_prepare()

        assert (gen.df_hourly["GHI"] >= 0).all()
        assert (gen.df_hourly["Wind_speed"] >= 0).all()
        assert "Clipping to 0" in capsys.readouterr().out

    def test_tmy3_without_dni_warns_and_defaults_to_zero(self, tmp_path, capsys):
        df = _hourly_frame(YEARS, dni=False)
        csv_path = tmp_path / "weather.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(
            file_path=str(csv_path), data_frequency="hourly",
            weighting_method="tmy3", save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert "DNI_sum" in gen.df_daily.columns
        assert (gen.df_daily["DNI_sum"] == 0.0).all()
        assert "'DNI' column missing for TMY3" in capsys.readouterr().out


class TestDailyDataFrequency:
    def test_loads_daily_data_successfully(self, tmp_path):
        df = _daily_frame(YEARS)
        csv_path = tmp_path / "daily.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="daily", save_session=False)
        gen.sandia_step_1_load_and_prepare()

        assert gen.df_hourly is None
        assert gen.df_daily is not None
        assert "T_air_mean" in gen.df_daily.columns

    def test_fewer_than_5_years_raises(self, tmp_path):
        df = _daily_frame(YEARS[:3])  # only 3 years
        csv_path = tmp_path / "daily.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="daily", save_session=False)
        with pytest.raises(ValueError, match="fewer than 5 years"):
            gen.sandia_step_1_load_and_prepare()

    def test_empty_dataframe_raises(self, tmp_path):
        # Only a header row -> empty after parsing.
        csv_path = tmp_path / "empty.csv"
        pd.DataFrame(columns=["time", "T_air_mean"]).to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="daily", save_session=False)
        with pytest.raises(ValueError, match="empty after loading"):
            gen.sandia_step_1_load_and_prepare()

    def test_missing_ghi_sum_warns(self, tmp_path, capsys):
        df = _daily_frame(YEARS, include_ghi=False)
        csv_path = tmp_path / "daily.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(file_path=str(csv_path), data_frequency="daily", save_session=False)
        gen.sandia_step_1_load_and_prepare()
        assert "No 'GHI' or 'GHI_sum' column found" in capsys.readouterr().out

    def test_missing_weight_components_warns(self, tmp_path, capsys):
        # Sandia weighting needs T_air_mean/max/min etc.; omit them.
        df = _daily_frame(YEARS, include_standard=False)
        csv_path = tmp_path / "daily.csv"
        df.to_csv(csv_path, index=False)

        gen = TMYGenerator(
            file_path=str(csv_path), data_frequency="daily",
            weighting_method="sandia", save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()
        assert "components" in capsys.readouterr().out


class TestSeparateHourlyFilePath:
    def test_loads_and_merges_separate_hourly_file(self, tmp_path):
        daily_df = _daily_frame(YEARS)
        daily_path = tmp_path / "daily.csv"
        daily_df.to_csv(daily_path, index=False)

        hourly_df = _hourly_frame(YEARS)
        hourly_path = tmp_path / "hourly.csv"
        hourly_df.to_csv(hourly_path, index=False)

        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path), save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert gen.df_hourly is not None
        assert len(gen.df_hourly) > 0
        assert "T_air" in gen.df_hourly.columns

    def test_excludes_months_not_present_in_daily_file(self, tmp_path):
        # Daily file only covers Jan-Jun of each year; hourly covers the
        # full year -> July-December hours must be excluded and tracked.
        daily_full = _daily_frame(YEARS)
        daily_partial = daily_full[daily_full["time"].dt.month <= 6]
        daily_path = tmp_path / "daily.csv"
        daily_partial.to_csv(daily_path, index=False)

        hourly_df = _hourly_frame(YEARS)
        hourly_path = tmp_path / "hourly.csv"
        hourly_df.to_csv(hourly_path, index=False)

        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path), save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert gen.df_hourly.index.month.max() <= 6
        assert len(gen.excluded_months_initial) > 0

    def test_missing_essential_columns_raises(self, tmp_path):
        daily_df = _daily_frame(YEARS)
        daily_path = tmp_path / "daily.csv"
        daily_df.to_csv(daily_path, index=False)

        # Hourly file missing Wind_speed entirely.
        bad_hourly = _hourly_frame(YEARS).drop(columns=["Wind_speed"])
        hourly_path = tmp_path / "hourly_bad.csv"
        bad_hourly.to_csv(hourly_path, index=False)

        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path), save_session=False,
        )
        with pytest.raises(ValueError, match="Essential columns missing in hourly file"):
            gen.sandia_step_1_load_and_prepare()

    def test_missing_ghi_in_hourly_file_creates_placeholder(self, tmp_path, capsys):
        daily_df = _daily_frame(YEARS)
        daily_path = tmp_path / "daily.csv"
        daily_df.to_csv(daily_path, index=False)

        hourly_no_ghi = _hourly_frame(YEARS, ghi=False)
        hourly_path = tmp_path / "hourly_no_ghi.csv"
        hourly_no_ghi.to_csv(hourly_path, index=False)

        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path), save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert "GHI" in gen.df_hourly.columns
        assert (gen.df_hourly["GHI"] == 0.0).all()
        assert "'GHI' not found in hourly file" in capsys.readouterr().out

    def test_negative_values_in_hourly_file_are_clipped(self, tmp_path, capsys):
        daily_df = _daily_frame(YEARS)
        daily_path = tmp_path / "daily.csv"
        daily_df.to_csv(daily_path, index=False)

        hourly_negative = _hourly_frame(YEARS, negative=True)
        hourly_path = tmp_path / "hourly_negative.csv"
        hourly_negative.to_csv(hourly_path, index=False)

        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path), save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert (gen.df_hourly["GHI"] >= 0).all()
        assert (gen.df_hourly["Wind_speed"] >= 0).all()
        assert "(hourly file)" in capsys.readouterr().out

    def test_years_to_include_filters_separate_hourly_file_too(self, tmp_path):
        daily_df = _daily_frame(YEARS)
        daily_path = tmp_path / "daily.csv"
        daily_df.to_csv(daily_path, index=False)

        hourly_df = _hourly_frame(YEARS)
        hourly_path = tmp_path / "hourly.csv"
        hourly_df.to_csv(hourly_path, index=False)

        # Restrict to 5 of the 6 available years (still satisfies the
        # "minimum 5 years" requirement of sandia_step_1_load_and_prepare).
        restricted_years = YEARS[:5]
        gen = TMYGenerator(
            file_path=str(daily_path), data_frequency="daily",
            hourly_file_path=str(hourly_path),
            years_to_include=restricted_years, save_session=False,
        )
        gen.sandia_step_1_load_and_prepare()

        assert set(gen.df_hourly.index.year.unique()) <= set(restricted_years)
        assert YEARS[-1] not in gen.df_hourly.index.year.unique()



