# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_package.py
=====================================

Smoke tests for the ``pyweatherfiles.degree_hours`` package (Fase 5 of
``INFORME_REVISION_GENERAL.md`` §6): the former monolithic
``degree_hours.py`` was split into ``calculator.py`` / ``batch_analyzer.py``
/ ``group_trend_analyzer.py`` / ``_helpers.py``, re-exported from
``degree_hours/__init__.py``. These tests exercise the full ``run()``
pipeline of each analyzer end-to-end (not just isolated methods, unlike
``tests/test_fase4_trend_overlap_reduction.py``) against fully synthetic
EPW fixtures, to catch any regression from the module split (e.g. a
mis-wired relative import).
"""

import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.degree_hours import (
    DegreeHoursCalculator,
    EpwBatchAnalyzer,
    EpwGroupTrendAnalyzer,
)

SETPOINTS = {'type': 'constant', 'heating': 21.0, 'cooling': 25.0}


def _write_synthetic_epw(path, city, constant_temp=20.0):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city=city, latitude=40.0, longitude=-3.0, time_zone=1.0, elevation=100.0)
    # from_missing_values() fills dry_bulb_temperature with the EPW
    # "missing" code (99.9); overwrite with a usable constant temperature.
    epw.dry_bulb_temperature.values = [constant_temp] * 8760
    epw.save(str(path))
    return str(path)


class TestDegreeHoursCalculatorImportPaths:
    def test_importable_from_package_and_from_pyweatherfiles(self):
        from pyweatherfiles import degree_hours as dh_module

        assert dh_module.DegreeHoursCalculator is DegreeHoursCalculator
        assert dh_module.EpwBatchAnalyzer is EpwBatchAnalyzer
        assert dh_module.EpwGroupTrendAnalyzer is EpwGroupTrendAnalyzer

    def test_calculator_module_path_reflects_new_package_layout(self):
        assert DegreeHoursCalculator.__module__ == "pyweatherfiles.degree_hours.calculator"
        assert EpwBatchAnalyzer.__module__ == "pyweatherfiles.degree_hours.batch_analyzer"
        assert EpwGroupTrendAnalyzer.__module__ == "pyweatherfiles.degree_hours.group_trend_analyzer"


class TestDegreeHoursCalculatorEndToEnd:
    def test_calculate_with_dict_setpoints(self, tmp_path):
        epw_path = _write_synthetic_epw(tmp_path / "test_2020.epw", "test", constant_temp=15.0)
        calc = DegreeHoursCalculator(epw_path)

        results = calc.calculate(SETPOINTS, frequency=["monthly"], save_session=False)

        assert "monthly" in results
        # heating setpoint 21, constant temp 15 -> 6 HDH every hour
        assert results["monthly"]["heating_dh"].sum() == pytest.approx(6.0 * 8760, rel=1e-6)
        assert results["monthly"]["cooling_dh"].sum() == pytest.approx(0.0)


class TestEpwGroupTrendAnalyzerEndToEnd:
    def _make_epw_dir(self, tmp_path):
        for group, year, temp in [
            ("alpha", 2020, 15.0), ("alpha", 2021, 16.0),
            ("beta", 2020, 25.0), ("beta", 2021, 26.0),
        ]:
            _write_synthetic_epw(tmp_path / f"{group}_{year}.epw", group, constant_temp=temp)
        return tmp_path

    def test_run_produces_expected_results_shape(self, tmp_path):
        epw_dir = self._make_epw_dir(tmp_path)
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(epw_dir), setpoint_source=SETPOINTS)

        df = analyzer.run(save_session=False)

        assert isinstance(df, pd.DataFrame)
        assert set(df["group"]) == {"alpha", "beta"}
        assert len(df) == 4
        assert "heating_dh_allday" in df.columns
        assert "cooling_dh_allday" in df.columns
        # alpha is colder than beta -> more heating DH, no cooling DH for either
        # (constant temps 15-26 never exceed the 25 cooling setpoint after ffill).
        alpha_hdh = df.loc[df["group"] == "alpha", "heating_dh_allday"].mean()
        beta_hdh = df.loc[df["group"] == "beta", "heating_dh_allday"].mean()
        assert alpha_hdh > beta_hdh

    def test_compute_trends_and_fit_global_trend_after_run(self, tmp_path):
        epw_dir = self._make_epw_dir(tmp_path)
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(epw_dir), setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)

        per_group = analyzer.compute_trends("heating_dh_allday")
        assert set(per_group.index) == {"alpha", "beta"}

        global_result = analyzer.fit_global_trend("heating_dh_allday")
        assert global_result.n_cities == 2


class TestEpwBatchAnalyzerEndToEnd:
    def test_run_produces_multiindex_columns(self, tmp_path):
        p1 = _write_synthetic_epw(tmp_path / "cityA_2020.epw", "cityA", constant_temp=15.0)
        p2 = _write_synthetic_epw(tmp_path / "cityB_2020.epw", "cityB", constant_temp=25.0)

        batch = EpwBatchAnalyzer(
            epw_paths=[p1, p2], setpoint_source=SETPOINTS, frequencies=["monthly"],
        )
        results = batch.run(save_session=False)

        assert "monthly" in results
        epw_names = set(results["monthly"].columns.get_level_values("epw"))
        assert epw_names == {"cityA_2020", "cityB_2020"}

