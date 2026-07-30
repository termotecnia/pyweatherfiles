# -*- coding: utf-8 -*-
"""
trend_stats.py
================

Shared statistical building block for fitting a **global fixed-effects**
linear trend (``target ~ year + C(group)``) across several independently
tracked groups (e.g. cities/climates), used by both
:class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer` (temperature
metrics, where the group is a city) and, optionally,
:class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer` (degree-hour
metrics, via :meth:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer.fit_global_trend`).

Extracted in Fase 4 of ``INFORME_REVISION_GENERAL.md`` (§3.3/§6): before
this module existed, only ``EpwTrendAnalyzer`` had this estimator;
``EpwGroupTrendAnalyzer.compute_trends()`` could only fit independent
per-group regressions, with no equivalent to a *global* trend that
controls for each group's own baseline level. Both analyzers now share the
exact same estimation code instead of maintaining (or lacking) their own
copy.

The model
---------
``target = intercept + slope_c_per_year * year + sum(group_dummy_i * beta_i)``

fit by ordinary least squares via the normal equations (``beta = (X'X)^-1
X'y``), with a Moore-Penrose pseudo-inverse fallback if the design matrix
is singular. ``slope_c_per_year`` is the quantity of interest: the rate of
change common to *every* group, after controlling for each group's own
level — a panel-data / fixed-effects estimator, not a naive pooled
regression that would conflate cross-group differences with a genuine
trend over time.

.. note::
   :class:`FixedEffectResult`'s field names (``n_cities``,
   ``slope_c_per_year``) keep their original, city-centric names from
   ``EpwTrendAnalyzer`` for backward compatibility. When this module is
   used for a non-city grouping (e.g. ``EpwGroupTrendAnalyzer``'s
   ``group`` column), ``n_cities`` simply means "number of distinct
   groups" and ``slope_c_per_year`` "slope per year, in the target
   column's own units" (not necessarily degrees Celsius).
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import t


@dataclass
class FixedEffectResult:
    """Container for the summary of one global fixed-effects trend model
    (``target ~ year + C(group)``), as returned by
    :func:`fit_fixed_effects_model`.

    Parameters
    ----------
    target : str
        Name of the column the model was fit on (e.g. ``'t_mean_annual'``
        or ``'heating_dh_allday'``).
    slope_c_per_year : float
        Estimated common rate of change per year, after controlling for
        each group's own baseline level (the coefficient on ``year`` in
        the fixed-effects regression). Named after its original
        degrees-Celsius-per-year use in ``EpwTrendAnalyzer``; the unit is
        whatever *target*'s own unit is.
    intercept : float
        Model intercept (fitted value at ``year=0`` for the reference
        group).
    std_error : float
        Standard error of :attr:`slope_c_per_year`.
    t_stat : float
        t-statistic for the slope (``slope / std_error``).
    p_value : float
        Two-sided p-value for the slope, computed from a Student's t
        distribution with :attr:`df_resid` degrees of freedom.
    ci95_low : float
        Lower bound of the 95% confidence interval for the slope.
    ci95_high : float
        Upper bound of the 95% confidence interval for the slope.
    r2 : float
        Coefficient of determination of the fitted model.
    n_obs : int
        Number of group-year observations used in the fit.
    n_cities : int
        Number of distinct groups included in the fit (kept under its
        original city-centric name; means "number of groups" in general).
    df_resid : int
        Residual degrees of freedom (``n_obs - n_params``).
    """

    target: str
    slope_c_per_year: float
    intercept: float
    std_error: float
    t_stat: float
    p_value: float
    ci95_low: float
    ci95_high: float
    r2: float
    n_obs: int
    n_cities: int
    df_resid: int


def build_fixed_effects_design(df: pd.DataFrame, group_col: str = "city") -> Tuple[np.ndarray, List[str]]:
    """Build the fixed-effects design matrix ``X`` for the model
    ``target ~ year + C(group_col)``: an intercept column, the ``year``
    column, and one-hot ("dummy") columns for every distinct value of
    *group_col* except the first (dropped as the reference level).

    Args:
        df (pandas.DataFrame): Must contain *group_col* and ``year``
            columns.
        group_col (str): Name of the column identifying each group (e.g.
            ``'city'`` for :class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`,
            ``'group'`` for :class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer`).
            Defaults to ``'city'``.

    Returns:
        tuple[numpy.ndarray, list[str]]: ``(X, column_names)`` — the
        design matrix (shape ``(n_obs, 2 + n_groups - 1)``) and the
        corresponding column names (``'intercept'``, ``'year'``,
        ``'<group_col>_<value>'``, ...).
    """
    group_dummies = pd.get_dummies(df[group_col], prefix=group_col, drop_first=True)
    x_df = pd.concat(
        [
            pd.Series(1.0, index=df.index, name="intercept"),
            df["year"].astype(float).rename("year"),
            group_dummies.astype(float),
        ],
        axis=1,
    )
    return x_df.to_numpy(dtype=float), x_df.columns.tolist()


def fit_fixed_effects_model(df: pd.DataFrame, target: str, group_col: str = "city") -> FixedEffectResult:
    """Estimate the global fixed-effects model ``target ~ year +
    C(group_col)`` by ordinary least squares, solved via the normal
    equations ``beta = (X'X)^-1 X'y`` (falling back to the Moore-Penrose
    pseudo-inverse if ``X'X`` is singular), and derive the full
    inferential summary (standard errors, t-statistic, two-sided p-value
    via a Student's t distribution, 95% CI, R2).

    Args:
        df (pandas.DataFrame): Must contain *group_col*, ``year`` and the
            *target* column; rows with missing values in these are
            dropped before fitting.
        target (str): Name of the column to fit on.
        group_col (str): Name of the column identifying each group.
            Defaults to ``'city'``.

    Returns:
        FixedEffectResult: The fitted model summary.

    Raises:
        ValueError: If there are not enough observations relative to the
            number of model parameters (``n_obs <= n_params``, i.e. zero
            or negative residual degrees of freedom).

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'city': ['a', 'a', 'a', 'b', 'b', 'b'],
        ...     'year': [2020, 2021, 2022, 2020, 2021, 2022],
        ...     't_mean_annual': [18.0, 18.2, 18.5, 22.0, 22.3, 22.5],
        ... })
        >>> result = fit_fixed_effects_model(df, target='t_mean_annual')
        >>> round(result.slope_c_per_year, 2)
        0.25
        >>> result.n_cities
        2
    """
    sub = df[[group_col, "year", target]].dropna().copy()
    y = sub[target].to_numpy(dtype=float)
    x, col_names = build_fixed_effects_design(sub, group_col=group_col)

    n_obs, n_params = x.shape
    if n_obs <= n_params:
        raise ValueError(
            f"Insufficient degrees of freedom for global FE model on {target}: n={n_obs}, p={n_params}."
        )

    xtx = x.T @ x
    try:
        xtx_inv = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        xtx_inv = np.linalg.pinv(xtx)

    beta = xtx_inv @ (x.T @ y)
    y_hat = x @ beta
    resid = y - y_hat

    sse = float(resid.T @ resid)
    sst = float(((y - y.mean()) ** 2).sum())
    df_resid = n_obs - n_params
    sigma2 = sse / df_resid

    cov = sigma2 * xtx_inv
    se = np.sqrt(np.diag(cov))

    year_idx = col_names.index("year")
    slope = float(beta[year_idx])
    slope_se = float(se[year_idx])
    t_stat = slope / slope_se if slope_se > 0 else np.nan
    p_value = 2.0 * (1.0 - t.cdf(abs(t_stat), df_resid)) if np.isfinite(t_stat) else np.nan

    tcrit = t.ppf(0.975, df_resid)
    ci95_low = slope - tcrit * slope_se
    ci95_high = slope + tcrit * slope_se

    r2 = 1.0 - (sse / sst if sst > 0 else np.nan)
    return FixedEffectResult(
        target=target,
        slope_c_per_year=slope,
        intercept=float(beta[col_names.index("intercept")]),
        std_error=slope_se,
        t_stat=float(t_stat),
        p_value=float(p_value),
        ci95_low=float(ci95_low),
        ci95_high=float(ci95_high),
        r2=float(r2),
        n_obs=int(n_obs),
        n_cities=int(sub[group_col].nunique()),
        df_resid=int(df_resid),
    )

