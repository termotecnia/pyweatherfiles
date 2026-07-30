# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_metrics.py
=================================

``_MetricsMixin`` — file discovery/classification and annual-metrics /
heatwave-indicator computation for
:class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`.

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). This is a mixin (not a standalone
class): it expects to be combined with the rest of
``EpwTrendAnalyzer``'s mixins in ``_core.py``, which provides the shared
``self.trend_config``/``self.output_config``/``self._require`` state and
helpers.
"""

from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..degree_hours import DegreeHoursCalculator


class _MetricsMixin:
    """Discovery, annual-metrics and heatwave-indicator computation."""

    # ------------------------------------------------------------------
    # Discovery and metrics
    # ------------------------------------------------------------------

    def discover_files(self) -> pd.DataFrame:
        """Discover and parse ``city_year.epw`` files from
        :attr:`trend_config`'s ``root_dir``, matching :attr:`TrendConfig.file_glob`
        and parsing ``city``/``year`` via :attr:`TrendConfig.filename_regex`
        (delegating the actual classification to the shared
        :func:`~pyweatherfiles.epw_utils.classify_epw_files` helper — also
        used by :class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer`
        — see ``INFORME_REVISION_GENERAL.md`` §3.3/Fase 4).

        Also computes :attr:`coverage_df` (per-city year count, min/max year
        and any missing years within that range) as a side effect.

        Returns:
            pandas.DataFrame: :attr:`files_df`, with columns ``city``
            (lower-cased), ``year`` (int) and ``epw_path`` (resolved
            absolute path), sorted by city then year.

        Raises:
            FileNotFoundError: If no file in ``root_dir`` matches both the
                glob pattern and the filename regex.

        Example:
            >>> analyzer.discover_files()  # doctest: +SKIP
            >>> analyzer.coverage_df  # doctest: +SKIP
        """
        from ..epw_utils import classify_epw_files

        candidate_paths = [str(p) for p in self.trend_config.root_dir.glob(self.trend_config.file_glob)]
        if not candidate_paths:
            raise FileNotFoundError(
                f"No EPW files were found in {self.trend_config.root_dir} with pattern {self.trend_config.file_glob}."
            )

        grouped = classify_epw_files(epw_paths=candidate_paths, filename_pattern=self.trend_config.filename_regex)

        records: List[Dict[str, object]] = [
            {"city": city.lower(), "year": year, "epw_path": str(Path(path).resolve())}
            for city, years in grouped.items()
            for year, path in years.items()
        ]

        if not records:
            raise FileNotFoundError(
                f"No EPW files were found in {self.trend_config.root_dir} with pattern {self.trend_config.file_glob} "
                f"matching filename_regex {self.trend_config.filename_regex!r}."
            )

        self.files_df = pd.DataFrame(records).sort_values(["city", "year"]).reset_index(drop=True)
        self.coverage_df = self._compute_coverage_summary(self.files_df)
        return self.files_df

    def compute_metrics(self) -> pd.DataFrame:
        """Compute annual metrics and heatwave indicators for every EPW
        discovered by :meth:`discover_files`.

        For each file, loads the hourly dry-bulb temperature (reusing
        :class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator`
        internally, see :meth:`_load_hourly_temperature`) and computes
        ``t_mean_annual``, ``t_median_annual``, ``t_p95_annual``,
        ``hot_hours_abs``/``hot_days_abs`` (see
        :meth:`_build_daily_and_annual_tables`), then adds heatwave metrics
        based on both a local per-day-of-year percentile threshold and the
        fixed absolute threshold (see :meth:`_add_heatwave_metrics`).

        Returns:
            pandas.DataFrame: :attr:`annual_df`, one row per city-year.

        Raises:
            RuntimeError: If :meth:`discover_files` has not been called yet.

        Example:
            >>> analyzer.discover_files()  # doctest: +SKIP
            >>> analyzer.compute_metrics()  # doctest: +SKIP
        """
        files_df = self._require(self.files_df, "files_df", "Call discover_files() first.")

        daily_df, annual_df = self._build_daily_and_annual_tables(files_df)
        annual_df = self._add_heatwave_metrics(annual_df, daily_df)

        self.daily_df = daily_df
        self.annual_df = annual_df
        return annual_df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_hourly_temperature(self, epw_path: str) -> pd.Series:
        """Load the hourly dry-bulb temperature series of one EPW file,
        reusing :class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator`
        internally (which handles EPW parsing via Ladybug).

        Args:
            epw_path (str): Path to the EPW file.

        Returns:
            pandas.Series: Hourly dry-bulb temperature, named
            ``'dry_bulb_temperature'``.
        """
        calc = DegreeHoursCalculator(epw_path)
        series = calc.epw_data["dry_bulb_temperature"].copy()
        series.name = "dry_bulb_temperature"
        return series

    def _build_daily_and_annual_tables(self, files_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build the base daily (daily Tmax) and annual (mean/median/P95
        temperature, absolute hot-hour/day counts) tables for every EPW in
        *files_df*, used by :meth:`compute_metrics` before
        :meth:`_add_heatwave_metrics` layers the heatwave indicators on top.

        Args:
            files_df (pandas.DataFrame): As returned by
                :meth:`discover_files` (columns ``city``, ``year``,
                ``epw_path``).

        Returns:
            tuple[pandas.DataFrame, pandas.DataFrame]: ``(daily_df,
            annual_df)`` — per city-year-day daily-Tmax table, and per
            city-year annual-metrics table (without heatwave columns yet).
            As a side effect, also (re)populates :attr:`hourly_by_city` with
            the raw hourly dry-bulb temperature series of every file.
        """
        daily_rows: List[pd.DataFrame] = []
        annual_rows: List[Dict[str, object]] = []
        self.hourly_by_city = {}

        for row in files_df.itertuples(index=False):
            hourly_t = self._load_hourly_temperature(row.epw_path)
            self.hourly_by_city.setdefault(row.city, {})[row.year] = hourly_t
            daily_tmax = hourly_t.resample("D").max()

            daily_rows.append(
                pd.DataFrame(
                    {
                        "city": row.city,
                        "year": row.year,
                        "date": daily_tmax.index,
                        "month_day": daily_tmax.index.strftime("%m-%d"),
                        "tmax": daily_tmax.values,
                    }
                )
            )

            annual_rows.append(
                {
                    "city": row.city,
                    "year": row.year,
                    "epw_path": row.epw_path,
                    "t_mean_annual": float(hourly_t.mean()),
                    "t_median_annual": float(hourly_t.median()),
                    "t_p95_annual": float(hourly_t.quantile(0.95)),
                    "hot_hours_abs": int((hourly_t >= self.trend_config.abs_hot_threshold_c).sum()),
                    "hot_days_abs": int((daily_tmax >= self.trend_config.abs_hot_threshold_c).sum()),
                }
            )

        daily_df = pd.concat(daily_rows, ignore_index=True)
        annual_df = pd.DataFrame(annual_rows).sort_values(["city", "year"]).reset_index(drop=True)
        return daily_df, annual_df

    def _add_heatwave_metrics(self, annual_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Compute heatwave event/day counts and merge them into
        *annual_df*, using two complementary "hot day" definitions:

        - **Local**: daily Tmax exceeds the :attr:`TrendConfig.local_hot_percentile`-th
          percentile of that exact calendar day (``month_day``) across all
          of that city's years (falling back to the city-wide percentile if
          insufficient same-day data exists).
        - **Absolute**: daily Tmax is at or above
          :attr:`TrendConfig.abs_hot_threshold_c`.

        Runs of consecutive hot days (either definition) of length ``>=``
        :attr:`TrendConfig.min_heatwave_length_days` count as one heatwave
        event (see :meth:`_count_heatwave_events`).

        Args:
            annual_df (pandas.DataFrame): Base annual table (as returned by
                :meth:`_build_daily_and_annual_tables`).
            daily_df (pandas.DataFrame): Daily Tmax table (as returned by
                :meth:`_build_daily_and_annual_tables`).

        Returns:
            pandas.DataFrame: *annual_df* with 4 additional integer columns:
            ``heatwave_events_local``, ``heatwave_days_local``,
            ``heatwave_events_abs``, ``heatwave_days_abs``.
        """
        p_quant = self.trend_config.local_hot_percentile / 100.0

        baseline = (
            daily_df.groupby(["city", "month_day"])["tmax"]
            .quantile(p_quant)
            .rename("local_percentile_tmax")
            .reset_index()
        )
        merged = daily_df.merge(baseline, on=["city", "month_day"], how="left")

        city_fallback = (
            daily_df.groupby("city")["tmax"]
            .quantile(p_quant)
            .rename("city_percentile_tmax")
            .reset_index()
        )
        merged = merged.merge(city_fallback, on="city", how="left")
        merged["local_threshold"] = merged["local_percentile_tmax"].fillna(merged["city_percentile_tmax"])

        merged["hot_local"] = merged["tmax"] > merged["local_threshold"]
        merged["hot_abs"] = merged["tmax"] >= self.trend_config.abs_hot_threshold_c

        rows: List[Dict[str, object]] = []
        for (city, year), group in merged.sort_values("date").groupby(["city", "year"]):
            events_local, days_local = self._count_heatwave_events(group["hot_local"])
            events_abs, days_abs = self._count_heatwave_events(group["hot_abs"])
            rows.append(
                {
                    "city": city,
                    "year": int(year),
                    "heatwave_events_local": events_local,
                    "heatwave_days_local": days_local,
                    "heatwave_events_abs": events_abs,
                    "heatwave_days_abs": days_abs,
                }
            )

        heat_df = pd.DataFrame(rows)
        out = annual_df.merge(heat_df, on=["city", "year"], how="left")
        for col in [
            "heatwave_events_local",
            "heatwave_days_local",
            "heatwave_events_abs",
            "heatwave_days_abs",
        ]:
            out[col] = out[col].fillna(0).astype(int)
        return out

    def _compute_coverage_summary(self, files_df: pd.DataFrame) -> pd.DataFrame:
        """Build the per-city data-coverage summary exposed as
        :attr:`coverage_df`: how many years were found, the min/max year,
        and which years are missing within that range (useful to spot gaps
        such as a missing pandemic year).

        Args:
            files_df (pandas.DataFrame): As returned by
                :meth:`discover_files`.

        Returns:
            pandas.DataFrame: One row per city, with columns ``city``,
            ``n_years``, ``min_year``, ``max_year`` and
            ``missing_years`` (comma-separated string, empty if none).
        """
        rows: List[Dict[str, object]] = []
        for city, group in files_df.groupby("city"):
            years = sorted(group["year"].tolist())
            year_set = set(years)
            missing = sorted(set(range(min(years), max(years) + 1)) - year_set)
            rows.append(
                {
                    "city": city,
                    "n_years": len(years),
                    "min_year": min(years),
                    "max_year": max(years),
                    "missing_years": ",".join(str(y) for y in missing),
                }
            )
        return pd.DataFrame(rows).sort_values("city").reset_index(drop=True)

    def _count_heatwave_events(self, mask: pd.Series) -> Tuple[int, int]:
        """Count heatwave events and total heatwave days in a boolean
        "is this day hot?" series, where a heatwave event is any run of
        consecutive ``True`` values of length ``>=``
        :attr:`TrendConfig.min_heatwave_length_days`.

        Args:
            mask (pandas.Series): Boolean series (chronologically ordered)
                flagging "hot" days.

        Returns:
            tuple[int, int]: ``(n_events, n_days)`` — number of qualifying
            heatwave events and the total number of days they span.
        """
        lengths: List[int] = []
        current = 0
        for val in mask.astype(bool).tolist():
            if val:
                current += 1
            else:
                if current > 0:
                    lengths.append(current)
                current = 0
        if current > 0:
            lengths.append(current)

        filtered = [x for x in lengths if x >= self.trend_config.min_heatwave_length_days]
        return len(filtered), int(sum(filtered))

