# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_models.py
================================

``_ModelsMixin`` — per-city OLS trends and the global fixed-effects model
for :class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`.

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). This is a mixin (not a standalone
class): see ``_core.py`` for how it combines with the rest of
``EpwTrendAnalyzer``'s mixins.
"""

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import linregress

from ..trend_stats import FixedEffectResult, build_fixed_effects_design, fit_fixed_effects_model


class _ModelsMixin:
    """Per-city OLS trends + global fixed-effects model fitting."""

    def fit_city_trends(self) -> pd.DataFrame:
        """Fit a per-city ordinary-least-squares linear trend (via
        ``scipy.stats.linregress``) for every metric in
        :attr:`TrendConfig.city_trend_targets`, against calendar year.

        Cities with fewer than 2 distinct years (or with no year-to-year
        variability) get a row of ``NaN`` results instead of raising.

        Returns:
            pandas.DataFrame: :attr:`city_trends_df`, one row per (target,
            city), with columns ``city``, ``target``, ``slope_c_per_year``,
            ``intercept``, ``r2``, ``p_value``, ``std_error``, ``n_years``.

        Raises:
            RuntimeError: If :meth:`compute_metrics` has not been called yet.

        Example:
            >>> analyzer.compute_metrics()  # doctest: +SKIP
            >>> analyzer.fit_city_trends()  # doctest: +SKIP
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")

        rows: List[Dict[str, object]] = []
        for city, group in annual_df.groupby("city"):
            group = group.sort_values("year")
            x = group["year"].to_numpy(dtype=float)
            for target in self.trend_config.city_trend_targets:
                y = group[target].to_numpy(dtype=float)
                if len(x) < 2 or np.isclose(np.std(x), 0.0):
                    rows.append(
                        {
                            "city": city,
                            "target": target,
                            "slope_c_per_year": np.nan,
                            "intercept": np.nan,
                            "r2": np.nan,
                            "p_value": np.nan,
                            "std_error": np.nan,
                            "n_years": int(len(x)),
                        }
                    )
                    continue

                reg = linregress(x, y)
                rows.append(
                    {
                        "city": city,
                        "target": target,
                        "slope_c_per_year": float(reg.slope),
                        "intercept": float(reg.intercept),
                        "r2": float(reg.rvalue ** 2),
                        "p_value": float(reg.pvalue),
                        "std_error": float(reg.stderr),
                        "n_years": int(len(x)),
                    }
                )

        self.city_trends_df = pd.DataFrame(rows).sort_values(["target", "city"]).reset_index(drop=True)
        return self.city_trends_df

    def fit_global_models(self) -> Dict[str, FixedEffectResult]:
        """Fit global fixed-effects models (see :meth:`fit_global_model`)
        for :attr:`TrendConfig.primary_target` and, if different and set,
        :attr:`TrendConfig.secondary_target`.

        Returns:
            dict[str, FixedEffectResult]: :attr:`global_results`, mapping
            target name to its fitted model summary.

        Raises:
            RuntimeError: If :meth:`compute_metrics` has not been called yet.

        Example:
            >>> analyzer.compute_metrics()  # doctest: +SKIP
            >>> results = analyzer.fit_global_models()  # doctest: +SKIP
            >>> results["t_mean_annual"].slope_c_per_year  # doctest: +SKIP
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")

        targets = [self.trend_config.primary_target]
        if self.trend_config.secondary_target and self.trend_config.secondary_target != self.trend_config.primary_target:
            targets.append(self.trend_config.secondary_target)

        out: Dict[str, FixedEffectResult] = {}
        for target in targets:
            out[target] = self.fit_global_model(target)
        self.global_results = out
        return out

    def fit_global_model(self, target: str) -> FixedEffectResult:
        """Fit one global fixed-effects model, ``target ~ year + C(city)``,
        for the requested annual metric (see :meth:`_fit_global_fixed_effect`
        for the estimation details: OLS via the normal equations, with a
        pseudo-inverse fallback if the design matrix is singular).

        This is useful when you want ad-hoc sensitivity runs beyond the
        configured primary/secondary targets.

        Args:
            target (str): Name of an :attr:`annual_df` column to fit the
                model on (e.g. ``'hot_days_abs'``).

        Returns:
            FixedEffectResult: The fitted model summary (slope in
            degrees Celsius/year after controlling for city fixed effects,
            its standard error, t-statistic, p-value, 95% CI, R2 and sample
            sizes).

        Raises:
            RuntimeError: If :meth:`compute_metrics` has not been called yet.
            ValueError: If *target* is not a column of :attr:`annual_df`.

        Example:
            >>> analyzer.compute_metrics()  # doctest: +SKIP
            >>> analyzer.fit_global_model("hot_days_abs")  # doctest: +SKIP
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        if target not in annual_df.columns:
            raise ValueError(f"Target '{target}' is not available in annual metrics columns.")
        return self._fit_global_fixed_effect(annual_df, target)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_fe_design(self, df: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """Build the fixed-effects design matrix ``X`` for the model
        ``target ~ year + C(city)``: an intercept column, the ``year``
        column, and one-hot ("dummy") columns for every city except the
        first (dropped as the reference level). Thin wrapper around the
        shared :func:`~pyweatherfiles.trend_stats.build_fixed_effects_design`
        (also used by
        :meth:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer.fit_global_trend`
        — see ``INFORME_REVISION_GENERAL.md`` §3.3/Fase 4).

        Args:
            df (pandas.DataFrame): Must contain ``city`` and ``year``
                columns.

        Returns:
            tuple[numpy.ndarray, list[str]]: ``(X, column_names)`` — the
            design matrix (shape ``(n_obs, 2 + n_cities - 1)``) and the
            corresponding column names (``'intercept'``, ``'year'``,
            ``'city_<name>'``, ...).
        """
        return build_fixed_effects_design(df, group_col="city")

    def _fit_global_fixed_effect(self, annual_df: pd.DataFrame, target: str) -> FixedEffectResult:
        """Estimate the global fixed-effects model ``target ~ year +
        C(city)`` by ordinary least squares (see
        :func:`~pyweatherfiles.trend_stats.fit_fixed_effects_model` for the
        estimation details: normal equations, with a Moore-Penrose
        pseudo-inverse fallback if the design matrix is singular, plus the
        full inferential summary). Thin wrapper around that shared
        function — see ``INFORME_REVISION_GENERAL.md`` §3.3/Fase 4.

        Args:
            annual_df (pandas.DataFrame): Must contain ``city``, ``year``
                and the *target* column; rows with missing values in these
                are dropped before fitting.
            target (str): Name of the annual-metric column to fit on.

        Returns:
            FixedEffectResult: The fitted model summary.

        Raises:
            ValueError: If there are not enough observations relative to
                the number of model parameters (``n_obs <= n_params``, i.e.
                zero or negative residual degrees of freedom).
        """
        return fit_fixed_effects_model(annual_df, target, group_col="city")

