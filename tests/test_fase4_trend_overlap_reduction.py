# -*- coding: utf-8 -*-
"""
tests/test_fase4_trend_overlap_reduction.py
==============================================

Integration tests for Fase 4 of ``INFORME_REVISION_GENERAL.md`` (§3.3/§6):
reducing the overlap between :class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`
and :class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer`.

- :class:`TestEpwTrendAnalyzerDiscoverFiles` confirms
  ``EpwTrendAnalyzer.discover_files()`` still works end-to-end after being
  refactored to delegate classification to the shared
  :func:`~pyweatherfiles.epw_utils.classify_epw_files` helper instead of
  reimplementing its own glob+regex matching.
- :class:`TestEpwGroupTrendAnalyzerFitGlobalTrend` confirms the new
  ``EpwGroupTrendAnalyzer.fit_global_trend()`` method produces the exact
  same result as calling the shared
  :func:`~pyweatherfiles.trend_stats.fit_fixed_effects_model` directly.

All EPW fixtures are fully synthetic (``ladybug.epw.EPW.from_missing_values()``),
so these tests do not depend on any external file.
"""

import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles import EpwTrendAnalyzer, OutputConfig, TrendConfig
from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer
from pyweatherfiles.trend_stats import fit_fixed_effects_model


def _write_synthetic_epw(path, city):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city=city, latitude=40.0, longitude=-3.0, time_zone=1.0, elevation=100.0)
    epw.save(str(path))


class TestEpwTrendAnalyzerDiscoverFiles:
    def test_discover_files_uses_shared_classify_epw_files(self, tmp_path):
        for city, year in [("alpha", 2020), ("alpha", 2021), ("beta", 2020)]:
            _write_synthetic_epw(tmp_path / f"{city}_{year}.epw", city)

        analyzer = EpwTrendAnalyzer(
            trend_config=TrendConfig(root_dir=tmp_path),
            output_config=OutputConfig(output_dir=tmp_path / "out"),
        )
        files_df = analyzer.discover_files()

        assert set(files_df["city"]) == {"alpha", "beta"}
        assert len(files_df) == 3
        assert sorted(files_df.loc[files_df["city"] == "alpha", "year"]) == [2020, 2021]
        assert analyzer.coverage_df is not None
        assert not analyzer.coverage_df.empty

    def test_discover_files_lowercases_city_like_before(self, tmp_path):
        # Filenames with uppercase letters must still be classified (the
        # default TrendConfig.filename_regex is [A-Za-z]+) and normalised
        # to lowercase, exactly like the pre-refactor implementation did.
        _write_synthetic_epw(tmp_path / "Madrid_2020.epw", "Madrid")

        analyzer = EpwTrendAnalyzer(
            trend_config=TrendConfig(root_dir=tmp_path),
            output_config=OutputConfig(output_dir=tmp_path / "out"),
        )
        files_df = analyzer.discover_files()
        assert files_df.iloc[0]["city"] == "madrid"

    def test_discover_files_raises_when_no_files_match(self, tmp_path):
        analyzer = EpwTrendAnalyzer(
            trend_config=TrendConfig(root_dir=tmp_path),
            output_config=OutputConfig(output_dir=tmp_path / "out"),
        )
        with pytest.raises(FileNotFoundError):
            analyzer.discover_files()


class TestEpwGroupTrendAnalyzerFitGlobalTrend:
    def _make_analyzer(self, tmp_path):
        for group, year in [("alpha", 2020), ("alpha", 2021), ("beta", 2020), ("beta", 2021)]:
            _write_synthetic_epw(tmp_path / f"{group}_{year}.epw", group)
        return EpwGroupTrendAnalyzer(epw_dir=str(tmp_path))

    def test_fit_global_trend_matches_shared_estimator(self, tmp_path):
        analyzer = self._make_analyzer(tmp_path)
        # Bypass run() (which needs a full DegreeHoursCalculator pipeline
        # with real hourly temperature data); inject synthetic results
        # directly to test fit_global_trend() in isolation.
        analyzer.results = pd.DataFrame({
            "group": ["alpha", "alpha", "beta", "beta"],
            "year": [2020, 2021, 2020, 2021],
            "heating_dh_allday": [100.0, 110.0, 200.0, 210.0],
        })

        result = analyzer.fit_global_trend("heating_dh_allday")
        expected = fit_fixed_effects_model(analyzer.results, target="heating_dh_allday", group_col="group")

        assert result.slope_c_per_year == pytest.approx(expected.slope_c_per_year)
        assert result.n_cities == 2
        assert result.n_cities == expected.n_cities

    def test_fit_global_trend_raises_before_run(self, tmp_path):
        analyzer = self._make_analyzer(tmp_path)
        with pytest.raises(ValueError, match="Call run"):
            analyzer.fit_global_trend("heating_dh_allday")

    def test_fit_global_trend_raises_on_unknown_column(self, tmp_path):
        analyzer = self._make_analyzer(tmp_path)
        analyzer.results = pd.DataFrame({
            "group": ["alpha", "beta"],
            "year": [2020, 2020],
            "heating_dh_allday": [100.0, 200.0],
        })
        with pytest.raises(ValueError, match="not found in results"):
            analyzer.fit_global_trend("does_not_exist")

