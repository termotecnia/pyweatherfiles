# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_group_trend_analyzer.py
==================================================

Tests for :mod:`pyweatherfiles.degree_hours.group_trend_analyzer`
(``EpwGroupTrendAnalyzer``), 46% covered before this file per
``INFORME_REVISION_GENERAL.md``'s coverage analysis.
``tests/test_degree_hours_package.py`` already smoke-tests the ``run()`` ->
``compute_trends()``/``fit_global_trend()`` -> ``export_results()`` happy
path (only 2 years/group, so the "insufficient data" branch of
``compute_trends()`` is the only one it exercises); this file adds:

- The constructor's ``ValueError`` (neither ``epw_dir`` nor ``epw_paths``).
- ``run()``: the unsupported-aggfunc ``ValueError``, the ``extra_epw_variables``
  branch (both "column not found" and a real scaled value), a file that
  raises during processing (skipped with a warning, not fatal), the
  ``RuntimeError`` when nothing could be processed, and ``save_session=True``.
- ``compute_trends()``: both ``ValueError`` guards, and the real
  ``scipy.stats.linregress`` branch (>=3 years/group) with a known linear
  trend, alongside a group with <3 years to keep the NaN branch covered too.
- The display helpers ``_group_label``/``_group_color``/``_group_zone``
  (default vs. custom maps).
- ``plot_variable_grid()`` and ``plot_overview_grid()`` (which together
  exercise ``_draw_group_subplot``/``_harmonize_ylim``): default/explicit
  variables, ``out_path`` saving, ``harmonize_ylim=False``, ``show=True``,
  and their ``ValueError`` guard.
- ``export_results()``: the ``ValueError`` guard and the plain-CSV branch
  (only ``.xlsx`` was tested before).
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer

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


@pytest.fixture
def trend_epw_dir(tmp_path):
    """3 groups x up to 5 years (2018-2022), each with a *known* linear
    temperature trend so heating_dh_allday (a linear function of a constant
    annual temperature) is also perfectly linear in year -> exact slope/r2 to
    assert against. 'gamma' only gets 2 years, to keep compute_trends()'s
    "insufficient data" (NaN) branch covered alongside the real-regression
    one, in the same run."""
    years = [2018, 2019, 2020, 2021, 2022]
    # alpha cools down over time -> heating_dh increases with year
    for i, year in enumerate(years):
        _write_synthetic_epw(tmp_path / f"alpha_{year}.epw", "alpha", temp=10.0 - i * 0.5)
    # beta warms up over time -> heating_dh decreases with year
    for i, year in enumerate(years):
        _write_synthetic_epw(tmp_path / f"beta_{year}.epw", "beta", temp=5.0 + i * 0.5)
    # gamma: only 2 years -> insufficient data for a trend
    for year in years[:2]:
        _write_synthetic_epw(tmp_path / f"gamma_{year}.epw", "gamma", temp=15.0)
    return str(tmp_path)


class TestConstructorValidation:
    def test_raises_without_epw_dir_or_epw_paths(self):
        with pytest.raises(ValueError, match="epw_dir.*epw_paths"):
            EpwGroupTrendAnalyzer()


class TestRun:
    def test_raises_for_unsupported_aggfunc(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=trend_epw_dir, setpoint_source=SETPOINTS,
            extra_epw_variables={'wind_speed': ['bogus_agg']},
        )
        with pytest.raises(ValueError, match="Unsupported aggfunc"):
            analyzer.run(save_session=False)

    def test_extra_epw_variable_missing_column_warns_and_continues(self, tmp_path):
        # NOTE: the per-file inner block of run() runs under
        # contextlib.redirect_stdout(io.StringIO()) (to silence
        # DegreeHoursCalculator's own console noise), so the "not found"
        # warning printed here is swallowed too - only the *behavior*
        # (column absent from the result) is observable from the outside.
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0)
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS,
            extra_epw_variables={'nonexistent_variable': ['sum']},
        )
        df = analyzer.run(save_session=False)
        assert 'nonexistent_variable_sum' not in df.columns

    def test_default_setpoint_source_is_used_when_omitted(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0)
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path))  # no setpoint_source given
        df = analyzer.run(save_session=False)
        # default is {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}
        assert df.loc[0, 'heating_dh_allday'] == pytest.approx((20.0 - 15.0) * 8760)

    def test_session_save_failure_warns_but_does_not_raise(self, tmp_path, capsys):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0)
        not_a_dir = tmp_path / "not_a_directory.txt"
        not_a_dir.write_text("blocking file")  # os.makedirs(exist_ok=True) will fail on this
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)

        analyzer.run(save_session=True, session_dir=str(not_a_dir))  # must not raise

        assert "Could not save the session" in capsys.readouterr().out

    def test_extra_epw_variable_scaled_value(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0, ghi=1000.0)
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS,
            extra_epw_variables={'global_horizontal_radiation': ['sum']},
            scale_factors={'global_horizontal_radiation_sum': 0.001},
        )
        df = analyzer.run(save_session=False)
        expected = 1000.0 * 8760 * 0.001
        assert df.loc[0, 'global_horizontal_radiation_sum'] == pytest.approx(expected)

    def test_hours_scenario_forwards_months_and_invert_cooling(self, tmp_path):
        # T=10 degC constant -> classic CDH excess is always 0, but the
        # inverted "night cooling potential" (deficit below 25 degC),
        # restricted to hours 0-8 and months Jul-Sep, must be non-zero and
        # match the manual formula: 9h x 92 days x 15 degC.
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=10.0)
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS,
            hours_scenarios={
                'allday': {'hours': None, 'mode': 'both'},
                'night_potential_jul_sep': {
                    'hours': list(range(0, 9)), 'mode': 'cooling',
                    'invert_cooling': True, 'months': [7, 8, 9],
                },
            },
        )
        df = analyzer.run(save_session=False)
        assert 'cooling_dh_night_potential_jul_sep' in df.columns
        assert df.loc[0, 'cooling_dh_night_potential_jul_sep'] == pytest.approx(9 * (31 + 31 + 30) * 15.0)

    def test_run_skips_unprocessable_file_and_warns(self, tmp_path, capsys):
        real_path = _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0)
        missing_path = str(tmp_path / "beta_2020.epw")  # matches the pattern, but does not exist
        analyzer = EpwGroupTrendAnalyzer(
            epw_paths=[real_path, missing_path], setpoint_source=SETPOINTS,
        )
        df = analyzer.run(save_session=False)
        assert set(df['group']) == {'alpha'}
        assert "Skipping beta 2020" in capsys.readouterr().out

    def test_run_raises_when_nothing_could_be_processed(self, tmp_path):
        missing_path = str(tmp_path / "alpha_2020.epw")
        analyzer = EpwGroupTrendAnalyzer(epw_paths=[missing_path], setpoint_source=SETPOINTS)
        with pytest.raises(RuntimeError, match="No EPW files could be processed"):
            analyzer.run(save_session=False)

    def test_run_saves_session_when_requested(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha", temp=15.0)
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        analyzer.run(save_session=True, session_dir=str(tmp_path))
        saved = list(tmp_path.glob("EpwGroupTrendAnalyzer_*.pkl"))
        assert saved, "expected a saved .pkl session file"


class TestComputeTrends:
    def test_raises_before_run(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            analyzer.compute_trends("heating_dh_allday")

    def test_raises_for_unknown_column(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        with pytest.raises(ValueError, match="not found in results"):
            analyzer.compute_trends("nonexistent_col")

    def test_real_regression_and_insufficient_data_branches(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)

        trends = analyzer.compute_trends("heating_dh_allday")

        assert trends.loc["alpha", "n"] == 5
        assert trends.loc["alpha", "slope"] > 0  # colder over time -> more heating
        assert trends.loc["alpha", "significant"]
        assert trends.loc["alpha", "r2"] == pytest.approx(1.0, abs=1e-6)

        assert trends.loc["beta", "slope"] < 0  # warmer over time -> less heating

        assert trends.loc["gamma", "n"] == 2
        assert np.isnan(trends.loc["gamma", "slope"])
        assert not trends.loc["gamma", "significant"]


class TestFitGlobalTrend:
    def test_raises_before_run(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            analyzer.fit_global_trend("heating_dh_allday")

    def test_raises_for_unknown_column(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        with pytest.raises(ValueError, match="not found in results"):
            analyzer.fit_global_trend("nonexistent_col")

    def test_fits_global_fixed_effects_model(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        result = analyzer.fit_global_trend("heating_dh_allday")
        assert result.n_cities == 3  # 'n_cities' here really means "n_groups"


class TestDisplayHelpers:
    def test_group_label_default_and_custom(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS,
            group_labels={'alpha': 'Alpha City'},
        )
        assert analyzer._group_label('alpha') == 'Alpha City'
        assert analyzer._group_label('unmapped') == 'Unmapped'

    def test_group_color_default_cycle_and_custom(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS,
            group_colors={'alpha': '#123456'},
        )
        cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
        assert analyzer._group_color('alpha', 0) == '#123456'
        assert analyzer._group_color('other', 0) == cycle[0]

    def test_group_zone_default_and_custom(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=str(tmp_path), setpoint_source=SETPOINTS, group_zone={'alpha': 'Zone A'},
        )
        assert analyzer._group_zone('alpha') == 'Zone A'
        assert analyzer._group_zone('unmapped') == ''


class TestPlotVariableGrid:
    def test_raises_before_run(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            analyzer.plot_variable_grid("heating_dh_allday")

    def test_saves_figure_with_harmonized_ylim_and_odd_grid(self, trend_epw_dir, tmp_path):
        # 3 groups, ncols=2 -> 2x2 grid with 1 unused (turned-off) axis.
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        out_path = tmp_path / "grid.png"

        fig = analyzer.plot_variable_grid(
            "heating_dh_allday", ylabel="HDH", suptitle="Heating DH by group",
            ncols=2, out_path=str(out_path),
        )

        assert out_path.exists()
        assert fig is not None

    def test_without_harmonize_ylim_and_show_true(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        fig = analyzer.plot_variable_grid("heating_dh_allday", harmonize_ylim=False, show=True)
        assert fig is not None


class TestPlotOverviewGrid:
    def test_raises_before_run(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            analyzer.plot_overview_grid()

    def test_default_variables_uses_every_result_column(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        fig = analyzer.plot_overview_grid()
        assert fig is not None

    def test_explicit_variables_with_zone_labels_and_save(self, trend_epw_dir, tmp_path):
        analyzer = EpwGroupTrendAnalyzer(
            epw_dir=trend_epw_dir, setpoint_source=SETPOINTS, group_zone={'alpha': 'Cold'},
        )
        analyzer.run(save_session=False)
        out_path = tmp_path / "overview.png"

        fig = analyzer.plot_overview_grid(
            variables=[("heating_dh_allday", "HDH", "Heating DH")], out_path=str(out_path),
        )

        assert out_path.exists()
        assert fig is not None

    def test_show_true(self, trend_epw_dir):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        fig = analyzer.plot_overview_grid(
            variables=[("heating_dh_allday", "HDH", "Heating DH")], show=True,
        )
        assert fig is not None


class TestExportResults:
    def test_raises_before_run(self, tmp_path):
        _write_synthetic_epw(tmp_path / "alpha_2020.epw", "alpha")
        analyzer = EpwGroupTrendAnalyzer(epw_dir=str(tmp_path), setpoint_source=SETPOINTS)
        with pytest.raises(ValueError, match="run"):
            analyzer.export_results()

    def test_csv_export(self, trend_epw_dir, tmp_path):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        out_path = tmp_path / "results.csv"

        analyzer.export_results(str(out_path))

        assert out_path.exists()
        df = pd.read_csv(out_path)
        assert "heating_dh_allday" in df.columns

    def test_xlsx_export_includes_cached_trend_sheets(self, trend_epw_dir, tmp_path):
        analyzer = EpwGroupTrendAnalyzer(epw_dir=trend_epw_dir, setpoint_source=SETPOINTS)
        analyzer.run(save_session=False)
        analyzer.compute_trends("heating_dh_allday")
        out_path = tmp_path / "results.xlsx"

        analyzer.export_results(str(out_path))

        sheets = pd.read_excel(out_path, sheet_name=None)
        assert "results" in sheets
        assert "trend_heating_dh_allday" in sheets





