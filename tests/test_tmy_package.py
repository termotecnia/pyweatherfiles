# -*- coding: utf-8 -*-
"""
tests/test_tmy_package.py
============================

Smoke tests for the ``pyweatherfiles.tmy`` package (Fase 5 of
``INFORME_REVISION_GENERAL.md`` §6): the former monolithic ``tmy.py``
(~4.100 lines, a single ``TMYGenerator`` class) was split into
``_data_loading.py`` / ``_fs_selection.py`` / ``_proximity.py`` /
``_persistence.py`` / ``_assembly_smoothing.py`` / ``_validation.py`` /
``_plotting.py`` / ``_compat.py``, combined via mixins in ``_core.py`` and
re-exported from ``tmy/__init__.py``.

These tests exercise the full :meth:`TMYGenerator.generate_tmy` pipeline
end-to-end (Steps 1-7) against a fully synthetic, deterministic hourly
weather CSV generated in-memory (no dependency on external un-versioned
files), to catch any regression from the module split (e.g. a mis-wired
relative import or a method landing in the wrong mixin) - this is exactly
the smoke test recommended, but not yet implemented, by
``INFORME_REVISION_GENERAL.md`` before touching ``tmy.py``.
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles import TMYGenerator

YEARS = list(range(2015, 2021))  # 6 synthetic years -> 5 top FS candidates per month


def _make_synthetic_hourly_csv(path, years=YEARS, seed=42):
    """Builds a fully synthetic, gap-free hourly weather CSV spanning
    *years*, with a smooth seasonal (winter-cold/summer-hot) temperature
    cycle, a simple diurnal+seasonal GHI cycle (0 at night, positive during
    the day), non-negative wind speed, and small deterministic noise/
    inter-annual variability (fixed *seed*) - just enough realism to
    exercise FS ranking, proximity ranking and persistence filtering
    meaningfully, while keeping every year exactly 8760 hours (Feb 29th
    dropped from leap years) so the assembled TMY is unambiguously 8760
    hours long regardless of which year is picked for February.
    """
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


class TestTMYGeneratorImportPaths:
    def test_importable_from_package_and_from_pyweatherfiles(self):
        from pyweatherfiles import tmy as tmy_module

        assert tmy_module.TMYGenerator is TMYGenerator

    def test_module_path_reflects_new_package_layout(self):
        assert TMYGenerator.__module__ == "pyweatherfiles.tmy._core"


class TestTMYGeneratorEndToEndSequentialPersistence:
    def test_generate_tmy_full_pipeline(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather.csv")

        gen = TMYGenerator(
            file_path=csv_path,
            cdf_method="daily",
            data_frequency="hourly",
            weighting_method="sandia",
            save_session=False,
        )
        result = gen.generate_tmy(use_persistence=True, persistence_method="sequential")

        assert result is gen  # method chaining
        assert gen.tmy_final is not None
        assert len(gen.tmy_final) == 8760  # always 365 days, regardless of source leap years
        assert set(gen.selected_months.keys()) == set(range(1, 13))
        assert all(year in YEARS for year in gen.selected_months.values())

        for col in ["T_air", "T_dew", "Wind_speed", "GHI"]:
            assert col in gen.tmy_final.columns
            assert not gen.tmy_final[col].isna().any()
        assert (gen.tmy_final["GHI"] >= 0).all()
        assert (gen.tmy_final["Wind_speed"] >= 0).all()

        # Step 2/3 candidate lists: up to 5 candidates per month, drawn from YEARS
        assert set(gen.candidate_months.keys()) == set(range(1, 13))
        for month, candidates in gen.candidate_months.items():
            assert 1 <= len(candidates) <= 5
            assert all(y in YEARS for y in candidates)

        # Validation dataframes populated (save_validation_dfs=True by default)
        assert len(gen.validation_step2_fs_ranking_by_month) == 12
        assert gen.validation_step3_proximity_ranking is not None
        assert gen.validation_step4_persistence_sequential_details is not None
        assert gen.validation_step6_tmy_composition is not None
        assert gen.validation_full_summary is not None
        assert len(gen.validation_full_summary) == 12

    def test_export_tmy_roundtrip(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_export.csv", seed=123)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="sequential")

        out_path = tmp_path / "tmy_out.csv"
        gen.export_tmy(str(out_path))
        assert out_path.exists()

        exported = pd.read_csv(out_path)
        assert len(exported) == 8760
        for col in ["T_air", "T_dew", "Wind_speed", "GHI"]:
            assert col in exported.columns


class TestTMYGeneratorEndToEndScorePersistence:
    def test_generate_tmy_score_method(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_score.csv", seed=7)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="score")

        assert gen.tmy_final is not None
        assert len(gen.tmy_final) == 8760
        assert gen.validation_step4_df_persistence_decision is not None
        assert isinstance(gen.validation_step4_df_persistence_decision, pd.DataFrame)

    def test_generate_tmy_without_persistence(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_noperf.csv", seed=13)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=False)

        assert gen.tmy_final is not None
        assert len(gen.tmy_final) == 8760
        # Without persistence, the selected year for each month must be the best FS/proximity rank (index 0)
        for month, candidates in gen.candidate_months.items():
            assert gen.selected_months[month] == candidates[0]


class TestTMYGeneratorAnalysisAndValidationMethods:
    def _generated(self, tmp_path, seed=55):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_analysis.csv", seed=seed)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="sequential")
        return gen

    def test_generate_full_summary(self, tmp_path):
        gen = self._generated(tmp_path)
        summary = gen.generate_full_summary()
        assert len(summary) == 12
        assert "Source_Year" in summary.columns
        assert "FS_Total_W_FS" in summary.columns

    def test_analyze_selection_high_threshold_flags_nothing(self, tmp_path):
        gen = self._generated(tmp_path)
        analysis = gen.analyze_selection(temp_diff_threshold=1000.0, verbose=False)
        assert len(analysis) == 12
        assert not analysis["Flagged"].any()

    def test_get_candidate_stats(self, tmp_path):
        gen = self._generated(tmp_path)
        stats = gen.get_candidate_stats(month=7)
        assert stats is not None
        assert "Is_Selected" in stats.columns
        assert stats["Is_Selected"].sum() == 1  # exactly one candidate is the selected year

    def test_summarize_fs_results_and_validate_helpers_do_not_raise(self, tmp_path):
        gen = self._generated(tmp_path)
        gen.summarize_fs_results()
        gen.validate_step_1_data_loading()
        gen.validate_full_ranking_for_month(month=1)
        gen.validate_persistence_selection()
        gen.validate_step_4_final_tmy()


class TestTMYGeneratorPlotting:
    def test_plot_cdfs_and_plot_monthly_means_store_figure_data(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_plot.csv", seed=77)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="sequential")

        gen.plot_cdfs(month_to_plot=1, save_figure_data=True)
        gen.plot_monthly_means(save_figure_data=True)
        gen.plot_monthly_trend(months=[1, 7], show=False)

        assert any("CDFs" in key for key in gen.figures_data)
        assert "Monthly Means Comparison" in gen.figures_data


class TestTMYGeneratorDeprecatedCompatAliases:
    def test_deprecated_step_aliases_delegate_and_warn(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_compat.csv", seed=99)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gen.step_1_load_and_prepare_data()
            gen.step_2_select_candidate_months()
            gen.step_3_apply_persistence()
            gen.step_4_create_and_smooth_tmy()

        assert any(issubclass(w.category, DeprecationWarning) for w in caught)
        assert gen.tmy_final is not None
        assert len(gen.tmy_final) == 8760

    def test_validation_st_compat_properties_alias_current_attributes(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "synthetic_weather_compat2.csv", seed=101)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="sequential")

        assert gen.validation_st2_df_fs_ranking_by_month is gen.validation_step2_fs_ranking_by_month
        assert gen.validation_st2_summary_fs_ranking is gen.validation_step3_proximity_ranking
        assert gen.validation_st4_df_tmy_composition is gen.validation_step6_tmy_composition

