# -*- coding: utf-8 -*-
"""
tests/test_tmy_plotting.py
=============================

Tests for :mod:`pyweatherfiles.tmy._plotting` (``_PlottingMixin``), the
least-covered ``tmy/`` submodule per ``INFORME_REVISION_GENERAL.md``'s Fase 2
coverage analysis (23%): only ``plot_cdfs()``, ``plot_monthly_means()`` and
``plot_monthly_trend()`` had any test at all before this file
(``tests/test_tmy_package.py``'s
``TestTMYGeneratorPlotting::test_plot_cdfs_and_plot_monthly_means_store_figure_data``),
and even those only exercised the ``cdf_method='daily'`` branch.

This file adds the remaining ``plot_*``/``compare_tmy_versions`` methods that
had **zero** previous coverage (``plot_fs_details``, ``plot_junctions``,
``plot_smoothing_comparison``, ``plot_persistence_runs``,
``plot_annual_cdfs``, ``plot_monthly_cdfs``, ``plot_monthly_series``,
``compare_tmy_versions``), plus the ``cdf_method='hourly'`` sibling branch for
the 3 already-tested ones. ``tests/conftest.py`` forces
``matplotlib.use("Agg")`` for the whole suite, so none of this renders
anything to screen; the goal is to exercise every code path (including the
documented ``RuntimeError``/``ValueError`` guards and the ``save_figure_data``
bookkeeping), not to validate the visual output pixel-by-pixel.
"""

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles import TMYGenerator

YEARS = list(range(2015, 2021))  # 6 synthetic years -> 5 top FS candidates per month


def _make_synthetic_hourly_csv(path, years=YEARS, seed=42):
    """Same generator used by tests/test_tmy_package.py (duplicated here so
    this file has no cross-file import dependency); see that file for the
    full rationale of each parameter choice."""
    rng = np.random.default_rng(seed)
    frames = []
    for i, year in enumerate(years):
        idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz="UTC")
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
        day_of_year = idx.dayofyear.values.astype(float)
        hour_of_day = idx.hour.values.astype(float)

        seasonal = 15.0 - 10.0 * np.cos(2 * np.pi * (day_of_year - 15) / 365.0)
        yearly_offset = (i - len(years) / 2.0) * 0.08
        t_air = seasonal + yearly_offset + rng.normal(0, 0.5, size=len(idx))
        t_dew = t_air - 5.0 - np.abs(rng.normal(0, 0.3, size=len(idx)))
        wind = np.clip(2.0 + rng.normal(0, 0.5, size=len(idx)), 0, None)

        daylight = np.clip(np.sin(np.pi * (hour_of_day - 6) / 12.0), 0, None)
        seasonal_amplitude = 500.0 + 300.0 * -np.cos(2 * np.pi * (day_of_year - 15) / 365.0)
        ghi = daylight * seasonal_amplitude + rng.normal(0, 5, size=len(idx))
        ghi = np.clip(ghi, 0, None)

        frames.append(pd.DataFrame({
            "time": idx, "T_air": t_air, "T_dew": t_dew,
            "Wind_speed": wind, "GHI": ghi,
        }))

    df = pd.concat(frames, ignore_index=True)
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture(scope="module")
def daily_cdf_tmy(tmp_path_factory):
    """A fully generated TMYGenerator using cdf_method='daily' (the default,
    per AGENTS.md). Module-scoped: generating a full 6-year TMY pipeline is
    expensive, and every test in this file only *reads* the result."""
    tmp_path = tmp_path_factory.mktemp("tmy_plotting_daily_cdf")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=321)
    gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    return gen


@pytest.fixture(scope="module")
def hourly_cdf_tmy(tmp_path_factory):
    """A fully generated TMYGenerator using cdf_method='hourly', to exercise
    the sibling branches of every plot_* method that behave differently
    depending on cdf_method (module-scoped for the same reason as above)."""
    tmp_path = tmp_path_factory.mktemp("tmy_plotting_hourly_cdf")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=654)
    gen = TMYGenerator(file_path=csv_path, cdf_method="hourly", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    return gen


@pytest.fixture
def fresh_tmy(tmp_path):
    """A *newly constructed* TMYGenerator, with no step run yet (df_hourly,
    df_daily, tmy_raw, tmy_final all still None). Function-scoped, one per
    test, for the "RuntimeError before prerequisites" tests below."""
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=13)
    return TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)


class TestPlotCdfs:
    def test_daily_cdf_method_stores_figure_data(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_cdfs(month_to_plot=3, save_figure_data=True)
        assert any("T_air_mean" in key for key in daily_cdf_tmy.figures_data)

    def test_hourly_cdf_method_stores_figure_data(self, hourly_cdf_tmy):
        # cdf_method='hourly' plots T_air/T_dew/Wind_speed/GHI (no _mean/_sum
        # suffix) from df_hourly instead of df_daily - a fully different
        # branch (fig, axes = plt.subplots(2, 2, ...) with 4 raw variables).
        hourly_cdf_tmy.plot_cdfs(month_to_plot=6, save_figure_data=True)
        assert any("GHI" in key and "Sum" not in key for key in hourly_cdf_tmy.figures_data)

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.plot_cdfs()


class TestPlotFsDetails:
    def test_daily_cdf_method_stores_figure_data(self, daily_cdf_tmy):
        year = daily_cdf_tmy.selected_months[1]
        daily_cdf_tmy.plot_fs_details(var_to_plot="T_air_mean", month_to_plot=1,
                                       year_to_plot=year, save_figure_data=True)
        assert any("FS Details" in key for key in daily_cdf_tmy.figures_data)

    def test_hourly_cdf_method_stores_figure_data(self, hourly_cdf_tmy):
        year = hourly_cdf_tmy.selected_months[7]
        hourly_cdf_tmy.plot_fs_details(var_to_plot="T_air", month_to_plot=7,
                                        year_to_plot=year, save_figure_data=True)
        assert any("FS Details" in key for key in hourly_cdf_tmy.figures_data)

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.plot_fs_details(var_to_plot="T_air_mean", month_to_plot=1, year_to_plot=2015)


class TestPlotJunctions:
    def test_creates_temporary_raw_tmy_and_stores_figure_data(self, daily_cdf_tmy, capsys):
        # tmy_raw already exists after generate_tmy(); this exercises the
        # normal (already-created) path rather than the auto-create fallback.
        daily_cdf_tmy.plot_junctions([("T_air", 1)], save_figure_data=True)
        assert any(key.startswith("Junction - T_air - 1") for key in daily_cdf_tmy.figures_data)

    def test_multiple_junctions_use_grid_layout(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_junctions([("T_air", 1), ("GHI", 7)], save_figure_data=True)
        assert any("Junction - GHI - 7" in key for key in daily_cdf_tmy.figures_data)

    def test_daily_variable_name_is_mapped_to_hourly(self, daily_cdf_tmy):
        # T_air_mean (a df_daily-style name) must be transparently mapped to
        # T_air (the hourly column actually present in tmy_raw).
        daily_cdf_tmy.plot_junctions([("T_air_mean", 3)], save_figure_data=True)
        assert any("Junction - T_air - 3" in key for key in daily_cdf_tmy.figures_data)

    def test_non_list_input_raises_type_error(self, daily_cdf_tmy):
        with pytest.raises(TypeError):
            daily_cdf_tmy.plot_junctions(("T_air", 1))

    def test_empty_list_prints_message_and_returns(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.plot_junctions([])
        assert "No junctions were specified" in capsys.readouterr().out

    def test_unknown_variable_is_skipped_with_warning(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.plot_junctions([("Does_Not_Exist", 1)])
        assert "not found in TMY data" in capsys.readouterr().out

    def test_creates_temporary_tmy_when_none_exists(self, tmp_path, capsys):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=222)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.step_1_load_and_prepare_data()
        gen.step_2_select_candidate_months()
        gen.step_3_apply_persistence()  # populates selected_months
        # tmy_raw is intentionally still None (only step_4 creates it).
        gen.plot_junctions([("T_air", 1)])
        assert "Creating temporary raw TMY" in capsys.readouterr().out
        assert gen.tmy_raw is not None


class TestPlotSmoothingComparison:
    def test_stores_figure_data_with_raw_and_smoothed_series(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_smoothing_comparison([("T_air", 1), ("GHI", 7)], save_figure_data=True)
        key = next(k for k in daily_cdf_tmy.figures_data if "Smoothing Comparison - T_air" in k)
        data = daily_cdf_tmy.figures_data[key]["data"]
        assert set(data["type"].unique()) == {"Raw", "Smoothed"}

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_4_create_and_smooth_tmy"):
            fresh_tmy.plot_smoothing_comparison([("T_air", 1)])

    def test_non_list_input_raises_type_error(self, daily_cdf_tmy):
        with pytest.raises(TypeError):
            daily_cdf_tmy.plot_smoothing_comparison(("T_air", 1))

    def test_empty_list_prints_message_and_returns(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.plot_smoothing_comparison([])
        assert "No junctions were specified" in capsys.readouterr().out


class TestPlotPersistenceRuns:
    def test_single_year_int_stores_figure_data(self, daily_cdf_tmy):
        year = daily_cdf_tmy.selected_months[1]
        daily_cdf_tmy.plot_persistence_runs(month=1, years=year, save_figure_data=True)
        assert "Year-by-Year Persistence Analysis for January" in daily_cdf_tmy.figures_data

    def test_multiple_years_list(self, daily_cdf_tmy):
        candidates = daily_cdf_tmy.candidate_months[7][:2]
        daily_cdf_tmy.plot_persistence_runs(month=7, years=candidates, save_figure_data=True)
        data = daily_cdf_tmy.figures_data["Year-by-Year Persistence Analysis for July"]["data"]
        assert set(data["type"].unique()) == {f"Year {y}" for y in candidates}

    def test_raises_before_daily_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.plot_persistence_runs(month=1, years=2015)

    def test_raises_before_persistence_applied(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=234)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.step_1_load_and_prepare_data()
        with pytest.raises(RuntimeError, match="step_3_apply_persistence"):
            gen.plot_persistence_runs(month=1, years=2015)


class TestPlotAnnualCdfs:
    def test_daily_cdf_method_stores_figure_data(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_annual_cdfs(save_figure_data=True)
        assert any("Annual CDF Comparison" in key for key in daily_cdf_tmy.figures_data)

    def test_hourly_cdf_method_stores_figure_data(self, hourly_cdf_tmy):
        hourly_cdf_tmy.plot_annual_cdfs(save_figure_data=True)
        assert any("Annual CDF Comparison" in key for key in hourly_cdf_tmy.figures_data)

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="must be generated first"):
            fresh_tmy.plot_annual_cdfs()


class TestPlotMonthlyMeans:
    def test_daily_cdf_method_stores_figure_data(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_monthly_means(save_figure_data=True)
        assert "Monthly Means Comparison" in daily_cdf_tmy.figures_data

    def test_hourly_cdf_method_stores_figure_data(self, hourly_cdf_tmy):
        hourly_cdf_tmy.plot_monthly_means(save_figure_data=True)
        assert "Monthly Means Comparison" in hourly_cdf_tmy.figures_data

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="must be generated first"):
            fresh_tmy.plot_monthly_means()


class TestPlotMonthlyCdfs:
    def test_daily_cdf_method_stores_one_figure_per_variable(self, daily_cdf_tmy):
        daily_cdf_tmy.plot_monthly_cdfs(save_figure_data=True)
        # T_air_mean, T_air_max, T_air_min, T_dew_mean, Wind_speed_mean, GHI_sum
        assert sum("Monthly CDF Comparison" in k for k in daily_cdf_tmy.figures_data) >= 4

    def test_hourly_cdf_method_stores_figure_data(self, hourly_cdf_tmy):
        hourly_cdf_tmy.plot_monthly_cdfs(save_figure_data=True)
        assert any("Monthly CDF Comparison" in key for key in hourly_cdf_tmy.figures_data)

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="must be generated first"):
            fresh_tmy.plot_monthly_cdfs()


class TestPlotMonthlyTrend:
    def test_returns_figure_and_default_months(self, daily_cdf_tmy):
        fig = daily_cdf_tmy.plot_monthly_trend(show=False)
        assert fig is not None

    def test_show_candidates_branch(self, daily_cdf_tmy):
        fig = daily_cdf_tmy.plot_monthly_trend(months=[1, 7], show_candidates=True, show=False)
        assert fig is not None

    def test_explicit_variable_and_custom_title(self, daily_cdf_tmy):
        fig = daily_cdf_tmy.plot_monthly_trend(
            months=[1], variable="T_air_mean", title="Custom Title", show=False,
        )
        assert fig is not None

    def test_unknown_variable_raises_value_error(self, daily_cdf_tmy):
        with pytest.raises(ValueError, match="not found in df_daily"):
            daily_cdf_tmy.plot_monthly_trend(variable="Does_Not_Exist", show=False)

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.plot_monthly_trend(show=False)


class TestPlotMonthlySeries:
    def test_returns_figure_for_multiple_months(self, daily_cdf_tmy):
        fig = daily_cdf_tmy.plot_monthly_series(months=[1, 7], show=False)
        assert fig is not None

    def test_returns_figure_for_single_month(self, daily_cdf_tmy):
        # n == 1 branch: axes is not naturally a list and must be wrapped.
        fig = daily_cdf_tmy.plot_monthly_series(months=[1], show=False)
        assert fig is not None

    def test_unknown_variable_raises_value_error(self, daily_cdf_tmy):
        with pytest.raises(ValueError, match="not found in df_daily"):
            daily_cdf_tmy.plot_monthly_series(variable="Does_Not_Exist", show=False)

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.plot_monthly_series(show=False)


class TestCompareTmyVersions:
    def test_compares_two_generated_tmys_with_auto_detected_variable(self, daily_cdf_tmy, hourly_cdf_tmy):
        fig = daily_cdf_tmy.compare_tmy_versions(hourly_cdf_tmy.tmy_final, months=[1, 7], show=False)
        assert fig is not None

    def test_explicit_variable_and_labels(self, daily_cdf_tmy, hourly_cdf_tmy):
        fig = daily_cdf_tmy.compare_tmy_versions(
            hourly_cdf_tmy.tmy_final, months=[3], variable="T_air",
            label_self="Sequential", label_other="Alternative", show=False,
        )
        assert fig is not None

    def test_single_month_branch(self, daily_cdf_tmy, hourly_cdf_tmy):
        fig = daily_cdf_tmy.compare_tmy_versions(hourly_cdf_tmy.tmy_final, months=[1], show=False)
        assert fig is not None

    def test_variable_missing_in_other_df_raises_value_error(self, daily_cdf_tmy):
        other = pd.DataFrame(
            {"Something_Else": [1.0]},
            index=pd.date_range("2000-01-01", periods=1, freq="h"),
        )
        with pytest.raises(ValueError, match="not found in other_tmy_df"):
            daily_cdf_tmy.compare_tmy_versions(other, variable="T_air", show=False)

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="No TMY available"):
            fresh_tmy.compare_tmy_versions(pd.DataFrame(), show=False)


