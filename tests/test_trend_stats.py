# -*- coding: utf-8 -*-
"""
tests/test_trend_stats.py
============================

Unit tests for :mod:`pyweatherfiles.trend_stats`, the shared global
fixed-effects estimator extracted in Fase 4 of
``INFORME_REVISION_GENERAL.md`` (§3.3/§6) so that both
``EpwTrendAnalyzer`` and ``EpwGroupTrendAnalyzer.fit_global_trend()`` can
reuse the same panel-data regression instead of each maintaining (or
lacking) their own copy.
"""

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles.trend_stats import (
    FixedEffectResult,
    build_fixed_effects_design,
    fit_fixed_effects_model,
)


def _make_two_group_df():
    """Two groups, perfectly linear trend with the same slope, offset by a
    constant group-level effect — the textbook case for a fixed-effects
    model to recover the common slope exactly."""
    years = [2020, 2021, 2022, 2023]
    rows = []
    for year in years:
        rows.append({"city": "a", "year": year, "value": 10.0 + 0.5 * (year - 2020)})
        rows.append({"city": "b", "year": year, "value": 20.0 + 0.5 * (year - 2020)})
    return pd.DataFrame(rows)


class TestBuildFixedEffectsDesign:
    def test_design_has_intercept_year_and_group_dummies(self):
        df = _make_two_group_df()
        x, names = build_fixed_effects_design(df, group_col="city")
        assert names[0] == "intercept"
        assert names[1] == "year"
        assert any(n.startswith("city_") for n in names)
        assert x.shape == (len(df), len(names))

    def test_drops_first_group_as_reference(self):
        df = _make_two_group_df()
        _, names = build_fixed_effects_design(df, group_col="city")
        # 2 groups -> drop_first=True -> only 1 dummy column.
        dummy_cols = [n for n in names if n.startswith("city_")]
        assert len(dummy_cols) == 1

    def test_works_with_generic_group_column_name(self):
        df = _make_two_group_df().rename(columns={"city": "group"})
        _, names = build_fixed_effects_design(df, group_col="group")
        assert any(n.startswith("group_") for n in names)


class TestFitFixedEffectsModel:
    def test_recovers_exact_common_slope(self):
        df = _make_two_group_df()
        result = fit_fixed_effects_model(df, target="value", group_col="city")
        assert isinstance(result, FixedEffectResult)
        assert result.slope_c_per_year == pytest.approx(0.5, abs=1e-9)
        assert result.n_cities == 2
        assert result.r2 == pytest.approx(1.0, abs=1e-6)

    def test_default_group_col_is_city(self):
        df = _make_two_group_df()
        result_default = fit_fixed_effects_model(df, target="value")
        result_explicit = fit_fixed_effects_model(df, target="value", group_col="city")
        assert result_default.slope_c_per_year == pytest.approx(result_explicit.slope_c_per_year)

    def test_works_with_generic_group_column_name(self):
        # Same data, but the grouping column is called 'group' instead of
        # 'city' (EpwGroupTrendAnalyzer's convention).
        df = _make_two_group_df().rename(columns={"city": "group"})
        result = fit_fixed_effects_model(df, target="value", group_col="group")
        assert result.slope_c_per_year == pytest.approx(0.5, abs=1e-9)
        assert result.n_cities == 2

    def test_raises_on_insufficient_degrees_of_freedom(self):
        # 2 groups x 1 year each = 2 obs, but the model needs
        # intercept + year + 1 group dummy = 3 params -> n_obs <= n_params.
        df = pd.DataFrame({
            "city": ["a", "b"],
            "year": [2020, 2020],
            "value": [10.0, 20.0],
        })
        with pytest.raises(ValueError, match="Insufficient degrees of freedom"):
            fit_fixed_effects_model(df, target="value", group_col="city")

    def test_drops_rows_with_missing_target(self):
        df = _make_two_group_df()
        df.loc[0, "value"] = np.nan
        result = fit_fixed_effects_model(df, target="value", group_col="city")
        assert result.n_obs == len(df) - 1

    def test_confidence_interval_contains_slope(self):
        df = _make_two_group_df()
        result = fit_fixed_effects_model(df, target="value", group_col="city")
        assert result.ci95_low <= result.slope_c_per_year <= result.ci95_high

