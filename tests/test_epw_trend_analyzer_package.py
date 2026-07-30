# -*- coding: utf-8 -*-
"""
tests/test_epw_trend_analyzer_package.py
===========================================

Smoke tests for the ``pyweatherfiles.epw_trend_analyzer`` package (Fase 5
of ``INFORME_REVISION_GENERAL.md`` §6): the former monolithic
``epw_trend_analyzer.py`` was split into ``_config.py`` / ``_metrics.py`` /
``_models.py`` / ``_plotting.py`` / ``_report.py`` / ``_core.py``,
re-exported from ``epw_trend_analyzer/__init__.py``. This test exercises
the full ``run()`` pipeline (``discover_files`` -> ``compute_metrics`` ->
``fit_city_trends`` -> ``fit_global_models`` -> ``export_outputs``,
including figures and reports) end-to-end against fully synthetic EPW
fixtures with a known, deterministic warming trend, to catch any
regression from the module split.
"""

from pathlib import Path

import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles import EpwTrendAnalyzer, OutputConfig, TrendConfig
from pyweatherfiles.epw_trend_analyzer import FixedEffectResult, run_analysis

CITIES = {"alpha": 10.0, "beta": 20.0}
YEARS = [2020, 2021, 2022, 2023]
SLOPE_PER_YEAR = 0.5  # deg C / year, injected deterministically below


def _write_synthetic_epws(epw_dir: Path) -> None:
    for city, base_temp in CITIES.items():
        for i, year in enumerate(YEARS):
            epw = EPW.from_missing_values(is_leap_year=False)
            epw.location = Location(city=city, latitude=40.0, longitude=-3.0, time_zone=1.0, elevation=100.0)
            # A deterministic city-level offset plus a known linear warming
            # trend (SLOPE_PER_YEAR), so the fitted global fixed-effects
            # slope can be checked against an exact expected value.
            vals = [base_temp + i * SLOPE_PER_YEAR] * 8760
            epw.dry_bulb_temperature.values = vals
            epw.save(str(epw_dir / f"{city}_{year}.epw"))


class TestEpwTrendAnalyzerImportPaths:
    def test_importable_from_package_and_from_pyweatherfiles(self):
        from pyweatherfiles import epw_trend_analyzer as eta_module

        assert eta_module.EpwTrendAnalyzer is EpwTrendAnalyzer
        assert eta_module.TrendConfig is TrendConfig
        assert eta_module.OutputConfig is OutputConfig

    def test_core_module_path_reflects_new_package_layout(self):
        assert EpwTrendAnalyzer.__module__ == "pyweatherfiles.epw_trend_analyzer._core"
        assert TrendConfig.__module__ == "pyweatherfiles.epw_trend_analyzer._config"
        assert OutputConfig.__module__ == "pyweatherfiles.epw_trend_analyzer._config"

    def test_fixed_effect_result_still_reexported(self):
        # FixedEffectResult actually lives in trend_stats (Fase 4) but must
        # remain importable from epw_trend_analyzer for backward compatibility.
        assert FixedEffectResult.__module__ == "pyweatherfiles.trend_stats"


class TestEpwTrendAnalyzerEndToEnd:
    def test_run_produces_expected_slope_and_all_artifacts(self, tmp_path):
        epw_dir = tmp_path / "epws"
        out_dir = tmp_path / "out"
        epw_dir.mkdir()
        _write_synthetic_epws(epw_dir)

        analyzer = EpwTrendAnalyzer(
            trend_config=TrendConfig(root_dir=epw_dir, abs_hot_threshold_c=25.0),
            output_config=OutputConfig(output_dir=out_dir),
        )
        outputs = analyzer.run()

        # --- coverage / discovery ---
        assert set(analyzer.coverage_df["city"]) == {"alpha", "beta"}
        assert (analyzer.coverage_df["missing_years"] == "").all()

        # --- per-city trend ---
        assert analyzer.city_trends_df.shape[0] == len(CITIES) * len(TrendConfig.city_trend_targets)
        for row in analyzer.city_trends_df.itertuples():
            assert row.slope_c_per_year == pytest.approx(SLOPE_PER_YEAR, abs=1e-6)

        # --- global fixed-effects model recovers the exact injected slope ---
        assert isinstance(analyzer.global_results["t_mean_annual"], FixedEffectResult)
        for result in analyzer.global_results.values():
            assert result.slope_c_per_year == pytest.approx(SLOPE_PER_YEAR, abs=1e-6)
            assert result.n_cities == len(CITIES)

        # --- every configured artifact was written ---
        expected_files = {
            "annual_metrics.csv", "city_trends.csv", "global_trend.csv", "coverage_summary.csv",
            "trend_outputs.xlsx", "fig_city_timeseries.png", "fig_city_p95_timeseries.png",
            "fig_global_adjusted.png", "fig_city_boxplot_grid.png", "fig_city_boxplot_row.png",
            "conclusion_report.txt", "conclusion_report.md", "used_config.json",
        }
        actual_files = {p.name for p in out_dir.iterdir()}
        assert expected_files <= actual_files
        assert set(outputs.keys()) == {
            "annual_metrics", "city_trends", "global_trend", "coverage_summary", "xlsx_outputs",
            "fig_city_timeseries", "fig_city_p95_timeseries", "fig_global_adjusted",
            "fig_city_boxplot_grid", "fig_city_boxplot_row", "conclusion_report",
            "markdown_report", "used_config",
        }

    def test_module_level_run_analysis_convenience_function(self, tmp_path):
        epw_dir = tmp_path / "epws"
        out_dir = tmp_path / "out"
        epw_dir.mkdir()
        _write_synthetic_epws(epw_dir)

        outputs = run_analysis(root_dir=epw_dir, output_dir=out_dir)
        assert "annual_metrics" in outputs
        assert (out_dir / "annual_metrics.csv").exists()

    def test_get_results_and_to_json_after_run(self, tmp_path):
        epw_dir = tmp_path / "epws"
        out_dir = tmp_path / "out"
        epw_dir.mkdir()
        _write_synthetic_epws(epw_dir)

        analyzer = EpwTrendAnalyzer(
            trend_config=TrendConfig(root_dir=epw_dir), output_config=OutputConfig(output_dir=out_dir),
        )
        analyzer.run()

        results = analyzer.get_results()
        assert results["annual_df"] is not None
        assert "t_mean_annual" in results["global_results"]

        snapshot = analyzer.to_json()
        assert "root_dir" in snapshot and "output_dir" in snapshot

