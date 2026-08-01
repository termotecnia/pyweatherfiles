# -*- coding: utf-8 -*-
"""
tests/test_tmy_validation.py
===============================

Tests for :mod:`pyweatherfiles.tmy._validation` (``_ValidationMixin``),
49% covered before this file per ``INFORME_REVISION_GENERAL.md``'s Fase 2
coverage analysis. ``tests/test_tmy_package.py`` already smoke-tests
``generate_full_summary``, ``analyze_selection`` (only the "nothing flagged"
branch), ``get_candidate_stats``, ``summarize_fs_results`` and the other
"do not raise" validators; this file adds:

- ``validate_fs_calculation`` (0% previous coverage) and the ``'hourly'``
  ``cdf_method`` branch of ``validate_full_ranking_for_month``.
- The ``'score'``-persistence and "persistence skipped" branches of
  ``validate_persistence_selection`` (only the sequential-method branch was
  covered before).
- ``check_input_expectations`` (a ``@staticmethod``, 0% previous coverage):
  every combination of ``data_frequency``/``weighting_method``, column
  mapping, and the missing-time/invalid-time-format warnings.
- The "something actually flagged" + ``verbose=True`` branches of
  ``analyze_selection`` (previously only the high-threshold/nothing-flagged
  case was tested), plus its GHI-threshold branch.
- ``correct_selection_by_temperature`` (0% previous coverage): both the
  "within tolerance, no correction" and "correction applied + TMY
  regenerated" paths.
- The documented ``RuntimeError`` guards of every method above.
"""

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles import TMYGenerator

YEARS = list(range(2015, 2021))  # 6 synthetic years -> 5 top FS candidates per month


def _make_synthetic_hourly_csv(path, years=YEARS, seed=42):
    """Same generator used by tests/test_tmy_package.py and
    tests/test_tmy_plotting.py (duplicated here so this file has no
    cross-file import dependency)."""
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
    """A fully generated TMYGenerator using cdf_method='daily' and the
    default sequential-persistence method. Module-scoped and read-only in
    every test below (no test may mutate its state)."""
    tmp_path = tmp_path_factory.mktemp("tmy_validation_daily_cdf")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=741)
    gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    return gen


@pytest.fixture(scope="module")
def hourly_cdf_tmy(tmp_path_factory):
    """A fully generated TMYGenerator using cdf_method='hourly', to exercise
    the sibling branch of validate_fs_calculation/validate_full_ranking_for_month."""
    tmp_path = tmp_path_factory.mktemp("tmy_validation_hourly_cdf")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=852)
    gen = TMYGenerator(file_path=csv_path, cdf_method="hourly", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    return gen


@pytest.fixture(scope="module")
def score_persistence_tmy(tmp_path_factory):
    """A fully generated TMYGenerator using persistence_method='score', to
    exercise validate_persistence_selection()'s scoring-method branch."""
    tmp_path = tmp_path_factory.mktemp("tmy_validation_score")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=963)
    gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=True, persistence_method="score")
    return gen


@pytest.fixture(scope="module")
def no_persistence_tmy(tmp_path_factory):
    """A fully generated TMYGenerator with use_persistence=False, to
    exercise validate_persistence_selection()'s "skipped" branch."""
    tmp_path = tmp_path_factory.mktemp("tmy_validation_no_persistence")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=159)
    gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
    gen.generate_tmy(use_persistence=False)
    return gen


@pytest.fixture
def fresh_tmy(tmp_path):
    """A *newly constructed* TMYGenerator, with no step run yet. Function-
    scoped, one per test, for the "RuntimeError before prerequisites" tests."""
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=13)
    return TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)


class TestValidateStep1DataLoading:
    def test_prints_statistics_without_raising(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.validate_step_1_data_loading()
        assert "Descriptive Statistics" in capsys.readouterr().out

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.validate_step_1_data_loading()


class TestValidateFsCalculation:
    def test_daily_cdf_method_returns_dataframe(self, daily_cdf_tmy):
        result = daily_cdf_tmy.validate_fs_calculation("T_air_mean", month=1, year=daily_cdf_tmy.selected_months[1])
        assert result is not None
        assert "Absolute_Difference" in result.columns

    def test_generic_variable_name_is_auto_mapped_to_mean_suffix(self, daily_cdf_tmy):
        # 'T_air' is not a column of df_daily (only 'T_air_mean' is); the
        # method must transparently map it instead of raising a KeyError.
        result = daily_cdf_tmy.validate_fs_calculation("T_air", month=3, year=daily_cdf_tmy.selected_months[3])
        assert result is not None

    def test_hourly_cdf_method_uses_df_hourly(self, hourly_cdf_tmy):
        result = hourly_cdf_tmy.validate_fs_calculation("T_air", month=7, year=hourly_cdf_tmy.selected_months[7])
        assert result is not None

    def test_year_not_in_data_returns_none(self, daily_cdf_tmy, capsys):
        result = daily_cdf_tmy.validate_fs_calculation("T_air_mean", month=1, year=1999)
        assert result is None
        assert "Not enough data" in capsys.readouterr().out

    def test_raises_before_data_loaded(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_1_load_and_prepare_data"):
            fresh_tmy.validate_fs_calculation("T_air", month=1, year=2015)


class TestValidateFullRankingForMonth:
    def test_hourly_cdf_method_stores_and_returns_ranking(self, hourly_cdf_tmy):
        df_ranking = hourly_cdf_tmy.validate_full_ranking_for_month(month=2)
        assert len(df_ranking) == len(YEARS)
        assert hourly_cdf_tmy.validation_step2_fs_ranking_by_month[2] is df_ranking


class TestValidatePersistenceSelection:
    def test_sequential_method_prints_selected_year(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.validate_persistence_selection()
        assert "Selected Year" in capsys.readouterr().out

    def test_score_method_prints_selected_year(self, score_persistence_tmy, capsys):
        score_persistence_tmy.validate_persistence_selection()
        assert "Rank 1" in capsys.readouterr().out

    def test_skipped_persistence_prints_message(self, no_persistence_tmy, capsys):
        no_persistence_tmy.validate_persistence_selection()
        assert "Persistence step was skipped" in capsys.readouterr().out


class TestValidateStep4FinalTmy:
    def test_prints_composition_and_statistics(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.validate_step_4_final_tmy()
        assert "TMY Composition Table" in capsys.readouterr().out

    def test_raises_before_tmy_generated(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_4_create_and_smooth_tmy"):
            fresh_tmy.validate_step_4_final_tmy()


class TestSummarizeFsResults:
    def test_prints_ranking_breakdown(self, daily_cdf_tmy, capsys):
        daily_cdf_tmy.summarize_fs_results()
        assert "Ranking Breakdown" in capsys.readouterr().out

    def test_regenerates_summary_when_attribute_cleared(self, daily_cdf_tmy):
        # NOTE: _generate_summary_fs_ranking() (called internally when
        # validation_step3_proximity_ranking is None) only ever populates
        # validation_step2_summary_fs_ranking (a *different* attribute - see
        # tmy/_proximity.py, which is the one that actually assigns
        # validation_step3_proximity_ranking, either by copying the Step-2
        # summary or by computing the real proximity-reordered one). In the
        # normal generate_tmy() pipeline Step 3 always runs right after Step
        # 2, so validation_step3_proximity_ranking is never actually None
        # once candidate_months is set - this branch only exists for an
        # atypical manual-call scenario, not exercised here.
        assert daily_cdf_tmy.validation_step3_proximity_ranking is not None

    def test_raises_before_candidates_selected(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_2_select_candidate_months"):
            fresh_tmy.summarize_fs_results()


class TestCheckInputExpectations:
    def _write_csv(self, tmp_path, columns_data, name="input.csv"):
        path = tmp_path / name
        pd.DataFrame(columns_data).to_csv(path, index=False)
        return str(path)

    def test_hourly_sandia_all_columns_found(self, tmp_path):
        csv_path = self._write_csv(tmp_path, {
            "time": pd.date_range("2020-01-01", periods=5, freq="h", tz="UTC"),
            "T_air": [10.0] * 5, "T_dew": [5.0] * 5, "Wind_speed": [2.0] * 5, "GHI": [100.0] * 5,
        })
        result = TMYGenerator.check_input_expectations(csv_path, weighting_method="sandia", data_frequency="hourly")
        assert result["missing_exact"] == []
        assert result["time_valid"] is True

    def test_hourly_tmy3_requires_dni_column(self, tmp_path, capsys):
        csv_path = self._write_csv(tmp_path, {
            "time": pd.date_range("2020-01-01", periods=5, freq="h", tz="UTC"),
            "T_air": [10.0] * 5, "T_dew": [5.0] * 5, "Wind_speed": [2.0] * 5, "GHI": [100.0] * 5,
        })
        result = TMYGenerator.check_input_expectations(csv_path, weighting_method="tmy3", data_frequency="hourly")
        assert "DNI" in result["missing_exact"]
        assert "column_mapping" in capsys.readouterr().out

    def test_daily_sandia_expected_columns(self, tmp_path):
        csv_path = self._write_csv(tmp_path, {
            "time": pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC"),
            "T_air_mean": [10.0] * 5, "T_air_max": [12.0] * 5, "T_air_min": [8.0] * 5,
            "T_dew_mean": [5.0] * 5, "T_dew_max": [6.0] * 5, "T_dew_min": [4.0] * 5,
            "Wind_speed_mean": [2.0] * 5, "Wind_speed_max": [4.0] * 5, "GHI_sum": [2000.0] * 5,
        })
        result = TMYGenerator.check_input_expectations(csv_path, weighting_method="sandia", data_frequency="daily")
        assert result["missing_exact"] == []
        assert "DNI_sum" not in result["expected_variables"]

    def test_daily_tmy3_expects_dni_sum(self, tmp_path):
        csv_path = self._write_csv(tmp_path, {
            "time": pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC"),
            "T_air_mean": [10.0] * 5,
        })
        result = TMYGenerator.check_input_expectations(csv_path, weighting_method="tmy3", data_frequency="daily")
        assert "DNI_sum" in result["expected_variables"]
        assert "DNI_sum" in result["missing_exact"]

    def test_column_mapping_is_applied(self, tmp_path):
        csv_path = self._write_csv(tmp_path, {
            "Fecha": pd.date_range("2020-01-01", periods=5, freq="h", tz="UTC"),
            "Temp": [10.0] * 5, "Dew": [5.0] * 5, "Wind": [2.0] * 5, "Rad": [100.0] * 5,
        })
        result = TMYGenerator.check_input_expectations(
            csv_path, weighting_method="sandia", data_frequency="hourly",
            column_mapping={"Fecha": "time", "Temp": "T_air", "Dew": "T_dew", "Wind": "Wind_speed", "Rad": "GHI"},
        )
        assert result["missing_exact"] == []

    def test_missing_time_column_warns(self, tmp_path, capsys):
        csv_path = self._write_csv(tmp_path, {"T_air": [10.0] * 5})
        result = TMYGenerator.check_input_expectations(csv_path, data_frequency="hourly")
        assert result["time_valid"] is False
        assert "'time' column missing" in capsys.readouterr().out

    def test_invalid_time_format_warns(self, tmp_path, capsys):
        csv_path = self._write_csv(tmp_path, {"time": ["not-a-date"] * 5, "T_air": [10.0] * 5})
        result = TMYGenerator.check_input_expectations(csv_path, data_frequency="hourly")
        assert result["time_valid"] is False
        assert "invalid format" in capsys.readouterr().out

    def test_unreadable_file_returns_none(self, tmp_path, capsys):
        missing_path = str(tmp_path / "does_not_exist.csv")
        result = TMYGenerator.check_input_expectations(missing_path)
        assert result is None
        assert "Error reading file" in capsys.readouterr().out

    def test_reads_xlsx_source(self, tmp_path):
        xlsx_path = tmp_path / "input.xlsx"
        pd.DataFrame({
            # Naive (timezone-less) timestamps: pandas' to_excel() cannot
            # write tz-aware datetimes (raises ValueError), unrelated to the
            # method under test here.
            "time": pd.date_range("2020-01-01", periods=5, freq="h"),
            "T_air": [10.0] * 5, "T_dew": [5.0] * 5, "Wind_speed": [2.0] * 5, "GHI": [100.0] * 5,
        }).to_excel(xlsx_path, index=False)
        result = TMYGenerator.check_input_expectations(str(xlsx_path), data_frequency="hourly")
        assert result["missing_exact"] == []


class TestGetCandidateStats:
    def test_raises_before_candidates_selected(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="step_2_select_candidate_months"):
            fresh_tmy.get_candidate_stats(month=1)

    def test_unknown_month_key_returns_none(self, daily_cdf_tmy, capsys):
        result = daily_cdf_tmy.get_candidate_stats(month=13)
        assert result is None
        assert "No candidates found" in capsys.readouterr().out


class TestGenerateFullSummary:
    def test_raises_before_selection(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="sandia_step_4_and_5_apply_persistence"):
            fresh_tmy.generate_full_summary()

    def test_score_method_summary_uses_score_columns(self, score_persistence_tmy):
        summary = score_persistence_tmy.generate_full_summary()
        assert "Persist_Decision" in summary.columns


class TestAnalyzeSelection:
    def test_low_threshold_flags_and_prints_report(self, daily_cdf_tmy, capsys):
        analysis = daily_cdf_tmy.analyze_selection(temp_diff_threshold=0.0001, verbose=True)
        assert len(analysis) == 12
        assert analysis["Flagged"].any()
        out = capsys.readouterr().out
        assert "TMY SELECTION ANALYSIS" in out
        assert "Flagged months" in out

    def test_ghi_threshold_branch(self, daily_cdf_tmy):
        analysis = daily_cdf_tmy.analyze_selection(
            temp_diff_threshold=None, ghi_diff_threshold=0.0001, verbose=False,
        )
        assert "Flagged_GHI" in analysis.columns

    def test_specific_months_only(self, daily_cdf_tmy):
        analysis = daily_cdf_tmy.analyze_selection(months=[1, 7], verbose=False)
        assert sorted(analysis["Month_Num"].tolist()) == [1, 7]

    def test_raises_before_selected_months(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="generate_tmy"):
            fresh_tmy.analyze_selection()


class TestCorrectSelectionByTemperature:
    """These tests mutate selected_months (and, when regenerate=True, the
    TMY itself), so each one gets its own freshly generated TMYGenerator
    rather than sharing the module-scoped fixtures used elsewhere in this
    file."""

    @pytest.fixture
    def gen_for_correction(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=2024)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly", save_session=False)
        gen.generate_tmy(use_persistence=True, persistence_method="sequential")
        return gen

    def test_no_correction_needed_within_high_tolerance(self, gen_for_correction, capsys):
        corrections = gen_for_correction.correct_selection_by_temperature(temp_diff_threshold=1000.0)
        assert corrections == {}
        assert "No corrections needed" in capsys.readouterr().out

    def test_correction_applied_and_tmy_regenerated(self, gen_for_correction, capsys):
        original_selection = dict(gen_for_correction.selected_months)
        corrections = gen_for_correction.correct_selection_by_temperature(
            temp_diff_threshold=1e-6, regenerate=True,
        )
        assert corrections  # with a near-zero threshold, at least one month should be corrected
        out = capsys.readouterr().out
        assert "CORRECTION REPORT" in out
        assert "Regenerating TMY" in out
        for month, info in corrections.items():
            assert gen_for_correction.selected_months[month] == info["corrected"]
            assert info["corrected"] != original_selection[month]
        assert gen_for_correction.applied_corrections

    def test_regenerate_false_skips_tmy_recreation(self, gen_for_correction, capsys):
        gen_for_correction.correct_selection_by_temperature(temp_diff_threshold=1e-6, regenerate=False)
        assert "Regenerating TMY" not in capsys.readouterr().out

    def test_raises_before_selected_months(self, fresh_tmy):
        with pytest.raises(RuntimeError, match="generate_tmy"):
            fresh_tmy.correct_selection_by_temperature()



