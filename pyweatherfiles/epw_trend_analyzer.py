"""epw_trend_analyzer.py
=========================

Multi-year climate-trend analysis (warming, heatwaves) over a collection of
annual EPW files named ``city_year.epw``.

This module answers a question that naturally follows once you have several
years of EPW data for one or more locations (e.g. the "long-term" series
produced by :meth:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter.process`,
which conveniently already names its files ``city_year.epw``): *is the
climate warming, and by how much, once we control for each city's own
baseline climate?* It provides a configurable, class-based workflow to:

- Discover and parse EPW files from a root directory (:meth:`EpwTrendAnalyzer.discover_files`).
- Compute annual metrics (mean/median/P95 temperature, hot-hour/day counts)
  from hourly dry-bulb temperature (:meth:`EpwTrendAnalyzer.compute_metrics`).
- Detect heatwave indicators using both a local (per city, per day-of-year)
  percentile threshold and a fixed absolute threshold.
- Estimate per-city linear trends (:meth:`EpwTrendAnalyzer.fit_city_trends`)
  and a **global fixed-effects trend** that controls for each city's own
  climate level (:meth:`EpwTrendAnalyzer.fit_global_models`) - a panel-data
  estimator suitable for citing in a methods section.
- Export reproducible CSV/XLSX tables, PNG figures, and a text/Markdown
  conclusion report (:meth:`EpwTrendAnalyzer.export_outputs`).

Two configuration dataclasses, :class:`TrendConfig` and :class:`OutputConfig`,
control the analysis logic and the output artefacts respectively; the main
class :class:`EpwTrendAnalyzer` orchestrates the whole pipeline, either step
by step or via the convenience :meth:`EpwTrendAnalyzer.run` method.

Example
-------
Full default pipeline over a folder of annual EPWs (e.g. ``longterm_epw/``,
containing files like ``seville_2005.epw`` ... ``seville_2025.epw``)::

    from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig

    analyzer = EpwTrendAnalyzer(
        trend_config=TrendConfig(root_dir="longterm_epw/"),
        output_config=OutputConfig(output_dir="trend_results/"),
    )
    outputs = analyzer.run()   # discover_files -> compute_metrics -> fit_city_trends -> fit_global_models -> export_outputs
    print(analyzer.coverage_df)       # per-city years found / missing
    print(analyzer.city_trends_df)    # per-city OLS trend
    print(analyzer.global_results)    # {'t_mean_annual': FixedEffectResult(...), ...}

Module-level convenience function (equivalent to the snippet above, with
default configuration)::

    from pyweatherfiles.epw_trend_analyzer import run_analysis
    run_analysis(root_dir="longterm_epw/", output_dir="trend_results/")
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy.stats import linregress, t

from .degree_hours import DegreeHoursCalculator


@dataclass
class TrendConfig:
    """Configuration for trend analysis logic.

    Parameters
    ----------
    root_dir:
        Directory where `*_????.epw` files are searched.
    file_glob:
        Glob pattern used for discovery.
    filename_regex:
        Regex used to parse `city` and `year` groups from filename.
    abs_hot_threshold_c:
        Absolute temperature threshold (C) used for hot hour/day and
        absolute heatwave detection.
    local_hot_percentile:
        Local percentile (0-100) used as city/day-of-year threshold.
    min_heatwave_length_days:
        Minimum consecutive hot days to count one heatwave event.
    city_trend_targets:
        Annual metric columns for city-level trend fits.
    primary_target:
        Main target used for global conclusion.
    secondary_target:
        Optional sensitivity target for global model.
    min_slope_for_practical_significance:
        Practical threshold for classification in conclusion report.

    Example
    -------
    >>> from pyweatherfiles import TrendConfig
    >>> cfg = TrendConfig(root_dir="longterm_epw/", abs_hot_threshold_c=35.0)
    >>> cfg.validate()  # raises ValueError if misconfigured
    """

    root_dir: Path
    file_glob: str = "*_????.epw"
    filename_regex: str = r"^(?P<city>[A-Za-z]+)_(?P<year>\d{4})\.epw$"
    abs_hot_threshold_c: float = 35.0
    local_hot_percentile: float = 90.0
    min_heatwave_length_days: int = 3
    city_trend_targets: Tuple[str, ...] = ("t_mean_annual", "t_p95_annual")
    primary_target: str = "t_mean_annual"
    secondary_target: str = "t_p95_annual"
    min_slope_for_practical_significance: float = 0.02

    def validate(self) -> None:
        """Validate logical constraints for configuration values.

        Raises
        ------
        ValueError
            If ``root_dir`` is falsy, ``local_hot_percentile`` is not in
            ``(0, 100)``, ``min_heatwave_length_days`` is ``< 1``, or
            ``primary_target``/``secondary_target`` is not one of
            ``city_trend_targets``.
        """
        if not self.root_dir:
            raise ValueError("TrendConfig.root_dir is required.")
        if self.local_hot_percentile <= 0 or self.local_hot_percentile >= 100:
            raise ValueError("local_hot_percentile must be between 0 and 100 (exclusive).")
        if self.min_heatwave_length_days < 1:
            raise ValueError("min_heatwave_length_days must be >= 1.")
        if self.primary_target not in self.city_trend_targets:
            raise ValueError("primary_target must exist in city_trend_targets.")
        if self.secondary_target and self.secondary_target not in self.city_trend_targets:
            raise ValueError("secondary_target must exist in city_trend_targets.")


@dataclass
class OutputConfig:
    """Configuration for output artefacts and their persistence (which
    files to write, where, and under what names).

    All ``save_*``/``write_*`` flags default to ``True`` - set the ones you
    do not need to ``False`` to skip generating that artefact in
    :meth:`EpwTrendAnalyzer.export_outputs`. Validated by calling
    :meth:`validate` (done automatically by :class:`EpwTrendAnalyzer`'s
    constructor).

    Every attribute not listed below (``annual_metrics_filename``,
    ``city_trends_filename``, ``global_trend_filename``, ``coverage_filename``,
    ``xlsx_filename``, ``city_mean_plot_filename``, ``city_p95_plot_filename``,
    ``global_plot_filename``, ``conclusion_filename``,
    ``markdown_report_filename``, ``snapshot_filename``) is a configurable
    ``str`` output file name, relative to :attr:`output_dir`, for the
    correspondingly-named artefact.

    Parameters
    ----------
    output_dir : pathlib.Path
        Directory where every output artefact is written (created if it
        does not exist).
    save_csv : bool
        Whether to write ``annual_metrics.csv``, ``city_trends.csv``,
        ``global_trend.csv`` and ``coverage_summary.csv``. Defaults to
        ``True``.
    save_xlsx : bool
        Whether to write a combined ``trend_outputs.xlsx`` workbook (one
        sheet per table above). Defaults to ``True``.
    save_plots : bool
        Whether to generate the 3 PNG figures (per-city mean trend, per-city
        P95 trend, globally city-adjusted trend). Defaults to ``True``.
    save_report : bool
        Whether to write the plain-text ``conclusion_report.txt`` with an
        automatic verdict. Defaults to ``True``.
    save_markdown_report : bool
        Whether to write the more detailed ``conclusion_report.md``.
        Defaults to ``True``.
    write_config_snapshot : bool
        Whether to write ``used_config.json``, a snapshot of the exact
        :class:`TrendConfig`/:class:`OutputConfig` used (reproducibility).
        Defaults to ``True``.
    plot_dpi : int
        Resolution (dots per inch) for every saved PNG figure. Must be
        ``>= 72``. Defaults to ``150``.

    Example
    -------
    >>> from pyweatherfiles import OutputConfig
    >>> out_cfg = OutputConfig(output_dir="trend_results/", save_markdown_report=False)
    """

    output_dir: Path
    save_csv: bool = True
    save_xlsx: bool = True
    save_plots: bool = True
    save_report: bool = True
    save_markdown_report: bool = True
    write_config_snapshot: bool = True
    plot_dpi: int = 150

    annual_metrics_filename: str = "annual_metrics.csv"
    city_trends_filename: str = "city_trends.csv"
    global_trend_filename: str = "global_trend.csv"
    coverage_filename: str = "coverage_summary.csv"
    xlsx_filename: str = "trend_outputs.xlsx"
    city_mean_plot_filename: str = "fig_city_timeseries.png"
    city_p95_plot_filename: str = "fig_city_p95_timeseries.png"
    global_plot_filename: str = "fig_global_adjusted.png"
    conclusion_filename: str = "conclusion_report.txt"
    markdown_report_filename: str = "conclusion_report.md"
    snapshot_filename: str = "used_config.json"

    def validate(self) -> None:
        """Validate logical constraints for configuration values.

        Raises
        ------
        ValueError
            If ``output_dir`` is falsy or ``plot_dpi`` is below 72.
        """
        if not self.output_dir:
            raise ValueError("OutputConfig.output_dir is required.")
        if self.plot_dpi < 72:
            raise ValueError("plot_dpi should be >= 72.")


@dataclass
class FixedEffectResult:
    """Container for the summary of one global fixed-effects trend model
    (``target ~ year + C(city)``), as returned by
    :meth:`EpwTrendAnalyzer.fit_global_model`.

    Parameters
    ----------
    target : str
        Name of the annual-metric column the model was fit on (e.g.
        ``'t_mean_annual'``).
    slope_c_per_year : float
        Estimated common warming/cooling rate in degrees Celsius per year,
        after controlling for each city's own baseline level (the
        coefficient on ``year`` in the fixed-effects regression).
    intercept : float
        Model intercept (fitted value at ``year=0`` for the reference city).
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
        Number of city-year observations used in the fit.
    n_cities : int
        Number of distinct cities included in the fit.
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


class EpwTrendAnalyzer:
    """Class-based analyzer for multi-year, multi-city EPW temperature
    trend research.

    Workflow
    --------
    1) :meth:`discover_files`
    2) :meth:`compute_metrics`
    3) :meth:`fit_city_trends`
    4) :meth:`fit_global_models`
    5) :meth:`export_outputs`

    You can call each method independently for custom studies (each one
    stores its result on ``self`` and also returns it), or call :meth:`run`
    for the default full pipeline.

    Parameters
    ----------
    trend_config : TrendConfig
        The analysis configuration in use.
    output_config : OutputConfig
        The output configuration in use.
    files_df : pandas.DataFrame or None
        One row per discovered EPW file (``city``, ``year``, ``epw_path``).
        Populated by :meth:`discover_files`.
    daily_df : pandas.DataFrame or None
        One row per city-year-day with the daily maximum dry-bulb
        temperature (``tmax``) and its calendar ``month_day``. Populated by
        :meth:`compute_metrics`.
    annual_df : pandas.DataFrame or None
        One row per city-year with all computed annual metrics and heatwave
        indicators. Populated by :meth:`compute_metrics`.
    coverage_df : pandas.DataFrame or None
        One row per city summarising the number of years found, the
        min/max year, and any missing years within that range. Populated by
        :meth:`discover_files`.
    city_trends_df : pandas.DataFrame or None
        One row per (city, target) with the per-city OLS linear-trend
        results. Populated by :meth:`fit_city_trends`.
    global_results : dict[str, FixedEffectResult]
        Mapping of target name to its global fixed-effects result.
        Populated by :meth:`fit_global_models`.
    outputs : dict[str, pathlib.Path]
        Mapping of artefact name to the path it was written to, accumulated
        across calls to :meth:`plot`/:meth:`export_outputs`.

    Example
    -------
    >>> from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig
    >>> analyzer = EpwTrendAnalyzer(
    ...     trend_config=TrendConfig(root_dir="longterm_epw/"),
    ...     output_config=OutputConfig(output_dir="trend_results/"),
    ... )  # doctest: +SKIP
    >>> analyzer.run()  # doctest: +SKIP
    """

    def __init__(self, trend_config: TrendConfig, output_config: OutputConfig):
        """Store and validate the configuration, and initialise every
        result attribute to its empty/``None`` state (no file discovery or
        computation happens yet).

        Args:
            trend_config (TrendConfig): Analysis configuration; validated
                immediately via :meth:`TrendConfig.validate`.
            output_config (OutputConfig): Output configuration; validated
                immediately via :meth:`OutputConfig.validate`.

        Raises:
            ValueError: If either configuration object fails validation.
        """
        self.trend_config = trend_config
        self.output_config = output_config
        self.trend_config.validate()
        self.output_config.validate()

        self._filename_re = re.compile(self.trend_config.filename_regex)

        self.files_df: Optional[pd.DataFrame] = None
        self.daily_df: Optional[pd.DataFrame] = None
        self.annual_df: Optional[pd.DataFrame] = None
        self.coverage_df: Optional[pd.DataFrame] = None
        self.city_trends_df: Optional[pd.DataFrame] = None
        self.global_results: Dict[str, FixedEffectResult] = {}

        self.outputs: Dict[str, Path] = {}

    # ------------------------------------------------------------------
    # Config loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, config: Dict[str, object]) -> "EpwTrendAnalyzer":
        """Build an analyzer from a plain configuration dictionary, either
        nested (separate ``"trend"``/``"output"`` sub-dicts) or flat (all
        keys at the top level, in which case they are used for both
        :class:`TrendConfig` and :class:`OutputConfig` as applicable).

        Expected structure (either nested or flat)::

            {
              "trend": {...},
              "output": {...}
            }

        Args:
            config (dict): Configuration dictionary. Must contain
                ``root_dir`` (directly or under ``"trend"``) and
                ``output_dir`` (directly or under ``"output"``, falling back
                to the top-level/``"trend"`` value if present there).

        Returns:
            EpwTrendAnalyzer: A new, validated instance.

        Raises:
            ValueError: If ``root_dir`` or ``output_dir`` cannot be
                determined from *config*.

        Example:
            >>> EpwTrendAnalyzer.from_dict({
            ...     "trend": {"root_dir": "longterm_epw/"},
            ...     "output": {"output_dir": "trend_results/"},
            ... })  # doctest: +SKIP
        """
        trend_raw = dict(config.get("trend", config))
        output_raw = dict(config.get("output", {}))

        if "root_dir" not in trend_raw:
            raise ValueError("Configuration must include trend.root_dir or root_dir.")
        if "output_dir" not in output_raw and "output_dir" in trend_raw:
            output_raw["output_dir"] = trend_raw["output_dir"]
        if "output_dir" not in output_raw:
            raise ValueError("Configuration must include output.output_dir or output_dir.")

        trend_raw["root_dir"] = Path(trend_raw["root_dir"])
        output_raw["output_dir"] = Path(output_raw["output_dir"])

        trend_cfg = TrendConfig(**trend_raw)
        output_cfg = OutputConfig(**output_raw)
        return cls(trend_cfg, output_cfg)

    @classmethod
    def from_json(cls, config_path: Path) -> "EpwTrendAnalyzer":
        """Build an analyzer from a JSON configuration file (see
        :meth:`from_dict` for the expected structure).

        Args:
            config_path (pathlib.Path): Path to a ``.json`` file.

        Returns:
            EpwTrendAnalyzer: A new, validated instance.

        Example:
            >>> from pathlib import Path
            >>> EpwTrendAnalyzer.from_json(Path("trend_config.json"))  # doctest: +SKIP
        """
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_yaml(cls, config_path: Path) -> "EpwTrendAnalyzer":
        """Build an analyzer from a YAML configuration file (see
        :meth:`from_dict` for the expected structure). Requires the
        optional dependency ``pyyaml``.

        Args:
            config_path (pathlib.Path): Path to a ``.yaml``/``.yml`` file.

        Returns:
            EpwTrendAnalyzer: A new, validated instance.

        Raises:
            ImportError: If ``pyyaml`` is not installed.

        Example:
            >>> from pathlib import Path
            >>> EpwTrendAnalyzer.from_yaml(Path("trend_config.yaml"))  # doctest: +SKIP
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for YAML config. Install with: pip install pyyaml"
            ) from exc

        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Discovery and metrics
    # ------------------------------------------------------------------

    def discover_files(self) -> pd.DataFrame:
        """Discover and parse ``city_year.epw`` files from
        :attr:`trend_config`'s ``root_dir``, matching :attr:`TrendConfig.file_glob`
        and parsing ``city``/``year`` via :attr:`TrendConfig.filename_regex`.

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
        records: List[Dict[str, object]] = []
        for path in self.trend_config.root_dir.glob(self.trend_config.file_glob):
            match = self._filename_re.match(path.name)
            if not match:
                continue
            records.append(
                {
                    "city": match.group("city").lower(),
                    "year": int(match.group("year")),
                    "epw_path": str(path.resolve()),
                }
            )

        if not records:
            raise FileNotFoundError(
                f"No EPW files were found in {self.trend_config.root_dir} with pattern {self.trend_config.file_glob}."
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
    # Plot and export
    # ------------------------------------------------------------------

    def plot(self) -> Dict[str, Path]:
        """Generate the 3 default figures (per-city annual-mean trend,
        per-city P95 trend, and the globally city-adjusted trend) and save
        them under :attr:`output_config`'s ``output_dir``, if
        :attr:`OutputConfig.save_plots` is ``True``.

        Returns:
            dict[str, pathlib.Path]: Mapping of figure name
            (``'fig_city_timeseries'``, ``'fig_city_p95_timeseries'``,
            ``'fig_global_adjusted'``) to the path it was saved to (empty
            dict if :attr:`OutputConfig.save_plots` is ``False``). Also
            merged into :attr:`outputs`.

        Raises:
            RuntimeError: If :meth:`compute_metrics`/:meth:`fit_city_trends`
                have not been called yet.

        Example:
            >>> analyzer.compute_metrics(); analyzer.fit_city_trends()  # doctest: +SKIP
            >>> analyzer.plot()  # doctest: +SKIP
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        city_trends_df = self._require(self.city_trends_df, "city_trends_df", "Call fit_city_trends() first.")

        self.output_config.output_dir.mkdir(parents=True, exist_ok=True)

        created: Dict[str, Path] = {}
        if self.output_config.save_plots:
            mean_plot = self.output_config.output_dir / self.output_config.city_mean_plot_filename
            p95_plot = self.output_config.output_dir / self.output_config.city_p95_plot_filename
            global_plot = self.output_config.output_dir / self.output_config.global_plot_filename

            fig_mean, _ = self.build_city_figure(
                annual_df=annual_df,
                trend_df=city_trends_df,
                target_col="t_mean_annual",
                title="City trend - annual mean",
            )
            fig_p95, _ = self.build_city_figure(
                annual_df=annual_df,
                trend_df=city_trends_df,
                target_col="t_p95_annual",
                title="City trend - annual p95",
            )
            fig_global, _, _ = self.build_global_adjusted_figure(annual_df)

            fig_mean.savefig(mean_plot, dpi=self.output_config.plot_dpi)
            fig_p95.savefig(p95_plot, dpi=self.output_config.plot_dpi)
            fig_global.savefig(global_plot, dpi=self.output_config.plot_dpi)
            plt.close(fig_mean)
            plt.close(fig_p95)
            plt.close(fig_global)

            created["fig_city_timeseries"] = mean_plot
            created["fig_city_p95_timeseries"] = p95_plot
            created["fig_global_adjusted"] = global_plot

        self.outputs.update(created)
        return created

    def export_outputs(self) -> Dict[str, Path]:
        """Write every configured output artefact (CSV/XLSX tables, PNG
        figures via :meth:`plot`, text/Markdown conclusion reports and a
        JSON configuration snapshot) according to :attr:`output_config`'s
        ``save_*``/``write_*`` flags.

        Returns:
            dict[str, pathlib.Path]: Mapping of artefact name to the path it
            was written to (only the artefacts actually enabled by
            :attr:`output_config` are present). Also merged into
            :attr:`outputs`.

        Raises:
            RuntimeError: If any of :meth:`compute_metrics`,
                :meth:`discover_files`, :meth:`fit_city_trends` or
                :meth:`fit_global_models` has not been called yet.

        Example:
            >>> analyzer.discover_files(); analyzer.compute_metrics()  # doctest: +SKIP
            >>> analyzer.fit_city_trends(); analyzer.fit_global_models()  # doctest: +SKIP
            >>> analyzer.export_outputs()  # doctest: +SKIP
        """
        self.output_config.output_dir.mkdir(parents=True, exist_ok=True)

        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        coverage_df = self._require(self.coverage_df, "coverage_df", "Call discover_files() first.")
        city_trends_df = self._require(self.city_trends_df, "city_trends_df", "Call fit_city_trends() first.")
        global_results = self._require(self.global_results, "global_results", "Call fit_global_models() first.")

        created: Dict[str, Path] = {}

        if self.output_config.save_csv:
            annual_csv = self.output_config.output_dir / self.output_config.annual_metrics_filename
            city_csv = self.output_config.output_dir / self.output_config.city_trends_filename
            global_csv = self.output_config.output_dir / self.output_config.global_trend_filename
            coverage_csv = self.output_config.output_dir / self.output_config.coverage_filename

            annual_df.to_csv(annual_csv, index=False)
            city_trends_df.to_csv(city_csv, index=False)
            pd.DataFrame([asdict(v) for v in global_results.values()]).to_csv(global_csv, index=False)
            coverage_df.to_csv(coverage_csv, index=False)

            created["annual_metrics"] = annual_csv
            created["city_trends"] = city_csv
            created["global_trend"] = global_csv
            created["coverage_summary"] = coverage_csv

        if self.output_config.save_xlsx:
            xlsx_path = self.output_config.output_dir / self.output_config.xlsx_filename
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                annual_df.to_excel(writer, sheet_name="annual_metrics", index=False)
                city_trends_df.to_excel(writer, sheet_name="city_trends", index=False)
                pd.DataFrame([asdict(v) for v in global_results.values()]).to_excel(
                    writer, sheet_name="global_trend", index=False
                )
                coverage_df.to_excel(writer, sheet_name="coverage_summary", index=False)
            created["xlsx_outputs"] = xlsx_path

        created.update(self.plot())

        if self.output_config.save_report:
            report_path = self.output_config.output_dir / self.output_config.conclusion_filename
            self._write_conclusion(report_path)
            created["conclusion_report"] = report_path

        if self.output_config.save_markdown_report:
            md_path = self.output_config.output_dir / self.output_config.markdown_report_filename
            self.export_markdown_report(md_path)
            created["markdown_report"] = md_path

        if self.output_config.write_config_snapshot:
            snapshot = self.output_config.output_dir / self.output_config.snapshot_filename
            snapshot.write_text(self.to_json(indent=2), encoding="utf-8")
            created["used_config"] = snapshot

        self.outputs.update(created)
        return created

    def run(self) -> Dict[str, Path]:
        """Run the full default pipeline: :meth:`discover_files` ->
        :meth:`compute_metrics` -> :meth:`fit_city_trends` ->
        :meth:`fit_global_models` -> :meth:`export_outputs`.

        Returns:
            dict[str, pathlib.Path]: The same mapping returned by
            :meth:`export_outputs`.

        Example:
            >>> from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig
            >>> analyzer = EpwTrendAnalyzer(TrendConfig(root_dir="longterm_epw/"), OutputConfig(output_dir="trends/"))  # doctest: +SKIP
            >>> analyzer.run()  # doctest: +SKIP
        """
        self.discover_files()
        self.compute_metrics()
        self.fit_city_trends()
        self.fit_global_models()
        return self.export_outputs()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_results(self) -> Dict[str, object]:
        """Return every in-memory result computed so far, for interactive
        analysis (e.g. in a Jupyter notebook) without needing to re-read the
        exported files.

        Returns:
            dict: A dict with keys ``'files_df'``, ``'coverage_df'``,
            ``'daily_df'``, ``'annual_df'``, ``'city_trends_df'``,
            ``'global_results'`` (as plain dicts, via
            :func:`dataclasses.asdict`) and ``'outputs'`` (paths as
            strings). Values not yet computed are ``None``/empty.

        Example:
            >>> analyzer.run()  # doctest: +SKIP
            >>> analyzer.get_results()["global_results"]  # doctest: +SKIP
        """
        return {
            "files_df": self.files_df,
            "coverage_df": self.coverage_df,
            "daily_df": self.daily_df,
            "annual_df": self.annual_df,
            "city_trends_df": self.city_trends_df,
            "global_results": {k: asdict(v) for k, v in self.global_results.items()},
            "outputs": {k: str(v) for k, v in self.outputs.items()},
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize the effective :attr:`trend_config`/:attr:`output_config`
        in use to a JSON string (used internally to write
        ``used_config.json`` when :attr:`OutputConfig.write_config_snapshot`
        is ``True``).

        Args:
            indent (int, optional): Indentation level passed to
                ``json.dumps``. ``None`` (default) produces compact JSON.

        Returns:
            str: JSON string with top-level keys ``'trend'`` and
            ``'output'``, each a serialised copy of the corresponding
            configuration dataclass (``pathlib.Path`` values converted to
            strings).

        Example:
            >>> analyzer.to_json(indent=2)  # doctest: +SKIP
        """
        payload = {
            "trend": self._to_serializable(asdict(self.trend_config)),
            "output": self._to_serializable(asdict(self.output_config)),
        }
        return json.dumps(payload, indent=indent)

    def build_city_figure(
        self,
        annual_df: Optional[pd.DataFrame] = None,
        trend_df: Optional[pd.DataFrame] = None,
        target_col: str = "t_mean_annual",
        title: Optional[str] = None,
    ):
        """Build a per-city panel matplotlib figure (one subplot per city,
        showing the annual metric series plus its fitted trend line)
        **without** saving it to disk, so callers can further customise it
        before calling ``fig.savefig(...)`` themselves.

        Args:
            annual_df (pandas.DataFrame, optional): Annual metrics table to
                plot. Defaults to :attr:`annual_df` (requires
                :meth:`compute_metrics` to have been called).
            trend_df (pandas.DataFrame, optional): Per-city trend table.
                Defaults to :attr:`city_trends_df` (requires
                :meth:`fit_city_trends`).
            target_col (str, optional): Annual-metric column to plot.
                Defaults to ``'t_mean_annual'``.
            title (str, optional): Figure title. Defaults to
                ``f"City trend - {target_col}"``.

        Returns:
            tuple[matplotlib.figure.Figure, numpy.ndarray]: ``(fig, axes)``
            - figure and axes array so callers can further customize with
            matplotlib or seaborn before saving.

        Example:
            >>> fig, axes = analyzer.build_city_figure(target_col="t_p95_annual")  # doctest: +SKIP
            >>> fig.savefig("custom_p95_trend.png", dpi=200)  # doctest: +SKIP
        """
        annual_df = annual_df if annual_df is not None else self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        trend_df = trend_df if trend_df is not None else self._require(self.city_trends_df, "city_trends_df", "Call fit_city_trends() first.")
        return self._plot_city_series(
            annual_df=annual_df,
            trend_df=trend_df,
            target_col=target_col,
            output_path=None,
            title=title or f"City trend - {target_col}",
        )

    def build_global_adjusted_figure(self, annual_df: Optional[pd.DataFrame] = None):
        """Build the globally city-adjusted trend figure **without** saving
        it to disk: the primary target's city fixed effects (from the
        global model) are subtracted from each observation, the remainder
        is averaged per year, and an OLS trend line is drawn through the
        resulting "climate-level-normalised" yearly series.

        Args:
            annual_df (pandas.DataFrame, optional): Annual metrics table.
                Defaults to :attr:`annual_df` (requires
                :meth:`compute_metrics`).

        Returns:
            tuple[matplotlib.figure.Figure, matplotlib.axes.Axes, pandas.DataFrame]:
            ``(fig, ax, yearly_df)`` - matplotlib objects and the
            city-adjusted yearly series (columns ``year``, ``adjusted``) for
            custom plotting/analysis.

        Example:
            >>> fig, ax, yearly = analyzer.build_global_adjusted_figure()  # doctest: +SKIP
            >>> yearly.plot(x="year", y="adjusted")  # doctest: +SKIP
        """
        annual_df = annual_df if annual_df is not None else self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        return self._plot_global_adjusted(annual_df, output_path=None)

    def export_markdown_report(self, output_path: Optional[Path] = None) -> Path:
        """Export a detailed Markdown report (executive summary, model
        definition, top-5 warming cities, sensitivity model if configured,
        data-coverage summary, and a list of output files) to help
        interpret the results - more detailed than :meth:`_write_conclusion`'s
        plain-text report.

        Args:
            output_path (pathlib.Path, optional): Destination path. Defaults
                to ``output_config.output_dir / output_config.markdown_report_filename``.

        Returns:
            pathlib.Path: The path the report was written to.

        Raises:
            RuntimeError: If :meth:`compute_metrics`, :meth:`discover_files`,
                :meth:`fit_city_trends` or :meth:`fit_global_models` has not
                been called yet.

        Example:
            >>> analyzer.run()  # doctest: +SKIP
            >>> analyzer.export_markdown_report("custom_report.md")  # doctest: +SKIP
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        coverage_df = self._require(self.coverage_df, "coverage_df", "Call discover_files() first.")
        city_trends_df = self._require(self.city_trends_df, "city_trends_df", "Call fit_city_trends() first.")
        global_results = self._require(self.global_results, "global_results", "Call fit_global_models() first.")

        output_path = output_path or (self.output_config.output_dir / self.output_config.markdown_report_filename)
        primary = global_results[self.trend_config.primary_target]
        secondary = global_results.get(self.trend_config.secondary_target)

        top_city_lines = []
        primary_city = city_trends_df[city_trends_df["target"] == self.trend_config.primary_target].sort_values("slope_c_per_year", ascending=False)
        for row in primary_city.head(5).itertuples(index=False):
            top_city_lines.append(
                f"- `{row.city}`: slope `{row.slope_c_per_year:+.4f} C/yr`, p-value `{row.p_value:.4g}`, R2 `{row.r2:.3f}`"
            )

        lines = [
            "# EPW Temperature Trend Report",
            "",
            "## Executive summary",
            f"- Primary target: `{self.trend_config.primary_target}`",
            f"- Global slope: `{primary.slope_c_per_year:+.6f} C/yr`",
            f"- p-value: `{primary.p_value:.6g}`",
            f"- 95% CI: `[{primary.ci95_low:+.6f}, {primary.ci95_high:+.6f}]`",
            f"- Observations: `{primary.n_obs}` across `{primary.n_cities}` cities",
            "",
            "## Model definition",
            f"- Primary model: `{self.trend_config.primary_target} ~ year + C(city)`",
            "- City fixed effects control level differences among cities.",
            "",
            "## City-level highlights (primary target)",
        ]
        lines.extend(top_city_lines or ["- No city trend rows available."])

        if secondary is not None:
            lines.extend(
                [
                    "",
                    "## Sensitivity model",
                    f"- Target: `{secondary.target}`",
                    f"- Slope: `{secondary.slope_c_per_year:+.6f} C/yr`",
                    f"- p-value: `{secondary.p_value:.6g}`",
                    f"- 95% CI: `[{secondary.ci95_low:+.6f}, {secondary.ci95_high:+.6f}]`",
                ]
            )

        lines.extend(
            [
                "",
                "## Data coverage",
                f"- City-year rows in annual table: `{len(annual_df)}`",
                f"- Cities in coverage table: `{coverage_df['city'].nunique() if not coverage_df.empty else 0}`",
                "",
                "## Output files",
                "- `annual_metrics.csv`",
                "- `city_trends.csv`",
                "- `global_trend.csv`",
                "- `coverage_summary.csv`",
                "- `trend_outputs.xlsx`",
                "- `fig_city_timeseries.png`",
                "- `fig_city_p95_timeseries.png`",
                "- `fig_global_adjusted.png`",
                "- `conclusion_report.txt`",
                "",
                "## Interpretation notes",
                "- Positive and significant slope indicates warming signal after controlling city effects.",
                "- Magnitude threshold for practical relevance is configurable.",
                "- Review city-level heterogeneity before policy decisions.",
            ]
        )

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # Internal methods
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
        """
        daily_rows: List[pd.DataFrame] = []
        annual_rows: List[Dict[str, object]] = []

        for row in files_df.itertuples(index=False):
            hourly_t = self._load_hourly_temperature(row.epw_path)
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

    def _build_fe_design(self, df: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """Build the fixed-effects design matrix ``X`` for the model
        ``target ~ year + C(city)``: an intercept column, the ``year``
        column, and one-hot ("dummy") columns for every city except the
        first (dropped as the reference level).

        Args:
            df (pandas.DataFrame): Must contain ``city`` and ``year``
                columns.

        Returns:
            tuple[numpy.ndarray, list[str]]: ``(X, column_names)`` — the
            design matrix (shape ``(n_obs, 2 + n_cities - 1)``) and the
            corresponding column names (``'intercept'``, ``'year'``,
            ``'city_<name>'``, ...).
        """
        city_dummies = pd.get_dummies(df["city"], prefix="city", drop_first=True)
        X_df = pd.concat(
            [
                pd.Series(1.0, index=df.index, name="intercept"),
                df["year"].astype(float).rename("year"),
                city_dummies.astype(float),
            ],
            axis=1,
        )
        return X_df.to_numpy(dtype=float), X_df.columns.tolist()

    def _fit_global_fixed_effect(self, annual_df: pd.DataFrame, target: str) -> FixedEffectResult:
        """Estimate the global fixed-effects model ``target ~ year +
        C(city)`` by ordinary least squares, solved via the normal
        equations ``beta = (X'X)^-1 X'y`` (falling back to the
        Moore-Penrose pseudo-inverse if ``X'X`` is singular), and derive the
        full inferential summary (standard errors, t-statistic, two-sided
        p-value via a Student's t distribution, 95% CI, R2).

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
        df = annual_df[["city", "year", target]].dropna().copy()
        y = df[target].to_numpy(dtype=float)
        X, col_names = self._build_fe_design(df)

        n_obs, n_params = X.shape
        if n_obs <= n_params:
            raise ValueError(
                f"Insufficient degrees of freedom for global FE model on {target}: n={n_obs}, p={n_params}."
            )

        xtx = X.T @ X
        try:
            xtx_inv = np.linalg.inv(xtx)
        except np.linalg.LinAlgError:
            xtx_inv = np.linalg.pinv(xtx)

        beta = xtx_inv @ (X.T @ y)
        y_hat = X @ beta
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
            n_cities=int(df["city"].nunique()),
            df_resid=int(df_resid),
        )

    def _plot_city_series(
        self,
        annual_df: pd.DataFrame,
        trend_df: pd.DataFrame,
        target_col: str,
        output_path: Optional[Path],
        title: str,
    ):
        """Build (and optionally save) the per-city panel figure used by
        :meth:`build_city_figure`/:meth:`plot`: one subplot per city, with
        the raw annual series and its fitted OLS trend line overlaid.

        Args:
            annual_df (pandas.DataFrame): Annual metrics table.
            trend_df (pandas.DataFrame): Per-city trend table (as returned
                by :meth:`fit_city_trends`).
            target_col (str): Annual-metric column to plot.
            output_path (pathlib.Path or None): If given, the figure is
                saved to this path (at :attr:`OutputConfig.plot_dpi`) and
                closed; otherwise it is returned open for further editing.
            title (str): Overall figure title (``fig.suptitle``).

        Returns:
            tuple[matplotlib.figure.Figure, numpy.ndarray]: ``(fig, axes)``.
        """
        cities = sorted(annual_df["city"].unique())
        rows, cols = self._subplot_layout(len(cities))

        fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 3.6 * rows), squeeze=False)
        axes_flat = axes.flatten()

        for i, city in enumerate(cities):
            ax = axes_flat[i]
            group = annual_df[annual_df["city"] == city].sort_values("year")
            x = group["year"].to_numpy(dtype=int)
            y = group[target_col].to_numpy(dtype=float)
            ax.plot(x, y, marker="o", linewidth=1.4, label=target_col)

            row = trend_df[(trend_df["city"] == city) & (trend_df["target"] == target_col)]
            if not row.empty and np.isfinite(row.iloc[0]["slope_c_per_year"]):
                slope = float(row.iloc[0]["slope_c_per_year"])
                intercept = float(row.iloc[0]["intercept"])
                ax.plot(x, intercept + slope * x, "k--", linewidth=1.4, label=f"trend {slope:+.3f} C/yr")

            ax.set_title(city)
            ax.set_xlabel("year")
            ax.set_ylabel("temperature (C)")
            ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)

        for j in range(len(cities), len(axes_flat)):
            axes_flat[j].axis("off")

        fig.suptitle(title)
        plt.tight_layout()
        if output_path is not None:
            fig.savefig(output_path, dpi=self.output_config.plot_dpi)
            plt.close(fig)
        return fig, axes

    def _plot_global_adjusted(self, annual_df: pd.DataFrame, output_path: Optional[Path]):
        """Build (and optionally save) the globally city-adjusted trend
        figure used by :meth:`build_global_adjusted_figure`/:meth:`plot`.

        The primary target's per-city fixed effects (from a fresh fit of
        ``target ~ year + C(city)`` via :meth:`_build_fe_design`) are
        subtracted from each observation, the remainder is averaged per
        year, and an OLS trend line (``scipy.stats.linregress``) is drawn
        through the resulting series.

        Args:
            annual_df (pandas.DataFrame): Annual metrics table.
            output_path (pathlib.Path or None): If given, the figure is
                saved (at :attr:`OutputConfig.plot_dpi`) and closed;
                otherwise returned open.

        Returns:
            tuple[matplotlib.figure.Figure, matplotlib.axes.Axes, pandas.DataFrame]:
            ``(fig, ax, yearly_df)``.
        """
        df = annual_df[["city", "year", self.trend_config.primary_target]].dropna().copy().reset_index(drop=True)
        target = self.trend_config.primary_target

        y = df[target].to_numpy(dtype=float)
        X, names = self._build_fe_design(df)
        beta = np.linalg.pinv(X.T @ X) @ (X.T @ y)

        city_effect = pd.Series(0.0, index=df.index)
        for name, coef in zip(names, beta):
            if name.startswith("city_"):
                city_name = name.replace("city_", "")
                city_effect[df["city"] == city_name] = coef

        adjusted = df[target] - city_effect
        yearly = (
            pd.DataFrame({"year": df["year"], "adjusted": adjusted})
            .groupby("year", as_index=False)["adjusted"]
            .mean()
        )

        x = yearly["year"].to_numpy(dtype=int)
        y = yearly["adjusted"].to_numpy(dtype=float)
        reg = linregress(x, y)

        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(x, y, marker="o", linewidth=1.8, label="city-adjusted mean")
        ax.plot(x, reg.intercept + reg.slope * x, "k--", linewidth=1.6, label=f"trend {reg.slope:+.3f} C/yr")
        ax.set_xlabel("year")
        ax.set_ylabel(f"adjusted {target} (C)")
        ax.set_title("Global trend adjusted by city fixed effects")
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.grid(alpha=0.3)
        ax.legend()
        plt.tight_layout()
        if output_path is not None:
            fig.savefig(output_path, dpi=self.output_config.plot_dpi)
            plt.close(fig)
        return fig, ax, yearly

    def _write_conclusion(self, output_path: Path) -> None:
        """Write the plain-text executive-summary conclusion report
        (``conclusion_report.txt``), including an automatic verdict derived
        from the primary global model's sign, statistical significance
        (p < 0.05) and practical significance (slope above
        :attr:`TrendConfig.min_slope_for_practical_significance`).
        """
        primary = self.global_results[self.trend_config.primary_target]
        secondary = self.global_results.get(self.trend_config.secondary_target)

        positive = primary.slope_c_per_year > 0
        significant = primary.p_value < 0.05
        practical = primary.slope_c_per_year >= self.trend_config.min_slope_for_practical_significance

        if positive and significant and practical:
            verdict = "Statistically significant positive warming trend (practically relevant)."
        elif positive and significant:
            verdict = "Statistically significant positive trend with modest practical magnitude."
        elif positive:
            verdict = "Positive slope but statistical evidence is not conclusive."
        else:
            verdict = "No conclusive positive global trend was detected."

        lines = [
            "EPW TEMPERATURE TREND - EXECUTIVE SUMMARY",
            "=" * 60,
            f"Primary target: {self.trend_config.primary_target}",
            "",
            f"Global model: {self.trend_config.primary_target} ~ year + C(city)",
            f"  slope (C/yr): {primary.slope_c_per_year:+.6f}",
            f"  p-value: {primary.p_value:.6g}",
            f"  95% CI: [{primary.ci95_low:+.6f}, {primary.ci95_high:+.6f}]",
            f"  R2: {primary.r2:.4f}",
            f"  n_obs: {primary.n_obs} | n_cities: {primary.n_cities}",
            "",
        ]

        if secondary is not None:
            lines.extend(
                [
                    f"Sensitivity model: {secondary.target} ~ year + C(city)",
                    f"  slope (C/yr): {secondary.slope_c_per_year:+.6f}",
                    f"  p-value: {secondary.p_value:.6g}",
                    f"  95% CI: [{secondary.ci95_low:+.6f}, {secondary.ci95_high:+.6f}]",
                    "",
                ]
            )

        lines.extend(["Conclusion:", f"  {verdict}"])
        output_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _subplot_layout(n_cities: int) -> Tuple[int, int]:
        """Compute a ``(rows, cols)`` subplot grid layout for *n_cities*
        panels, using a fixed 3-column grid.

        Args:
            n_cities (int): Number of city panels to lay out.

        Returns:
            tuple[int, int]: ``(rows, cols)``, with ``cols = 3`` and enough
            ``rows`` to fit all *n_cities* (at least 1 row).
        """
        cols = 3
        rows = int(math.ceil(n_cities / cols)) if n_cities > 0 else 1
        return rows, cols

    @staticmethod
    def _require(value, name: str, msg: str):
        """Guard clause used throughout the class: return *value* if it is
        "ready" (not ``None`` and, for dicts, not empty), otherwise raise a
        descriptive error pointing at which pipeline step to run first.

        Args:
            value: The attribute value to check (e.g. ``self.annual_df``).
            name (str): Human-readable name of the attribute, used in the
                error message.
            msg (str): Hint about which method to call first, appended to
                the error message.

        Returns:
            The unchanged *value*, if it passed the check.

        Raises:
            RuntimeError: If *value* is ``None`` or an empty dict.
        """
        if value is None or (isinstance(value, dict) and not value):
            raise RuntimeError(f"{name} is not ready. {msg}")
        return value

    @staticmethod
    def _to_serializable(data):
        """Recursively convert a (possibly nested) dict/list/tuple
        structure into one made only of JSON-serialisable types, converting
        any :class:`pathlib.Path` value to its string form. Used by
        :meth:`to_json`.

        Args:
            data: Value to convert (dict, list, tuple, ``Path``, or any
                already-JSON-safe scalar).

        Returns:
            The same structure with every ``Path`` replaced by ``str(path)``.
        """
        if isinstance(data, dict):
            return {k: EpwTrendAnalyzer._to_serializable(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [EpwTrendAnalyzer._to_serializable(v) for v in data]
        if isinstance(data, Path):
            return str(data)
        return data


def run_analysis(root_dir: Path, output_dir: Path) -> Dict[str, Path]:
    """Compatibility helper that runs the full default pipeline in a single
    call, equivalent to instantiating :class:`EpwTrendAnalyzer` with default
    :class:`TrendConfig`/:class:`OutputConfig` (only *root_dir*/*output_dir*
    customised) and calling :meth:`EpwTrendAnalyzer.run`.

    Args:
        root_dir (str or pathlib.Path): Directory containing the
            ``city_year.epw`` files to analyse.
        output_dir (str or pathlib.Path): Directory to write every output
            artefact to.

    Returns:
        dict[str, pathlib.Path]: Same mapping as
        :meth:`EpwTrendAnalyzer.export_outputs`.

    Example:
        >>> from pyweatherfiles.epw_trend_analyzer import run_analysis
        >>> run_analysis("longterm_epw/", "trend_results/")  # doctest: +SKIP
    """
    analyzer = EpwTrendAnalyzer(
        trend_config=TrendConfig(root_dir=Path(root_dir)),
        output_config=OutputConfig(output_dir=Path(output_dir)),
    )
    return analyzer.run()

