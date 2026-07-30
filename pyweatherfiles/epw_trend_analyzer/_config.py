# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_config.py
================================

Configuration dataclasses for :mod:`pyweatherfiles.epw_trend_analyzer`:
:class:`TrendConfig` (analysis logic) and :class:`OutputConfig` (output
artefacts and their persistence).

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6); see
``pyweatherfiles/epw_trend_analyzer/__init__.py`` for the package-level
overview.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


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
    :meth:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer.export_outputs`.
    Validated by calling :meth:`validate` (done automatically by
    :class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`'s
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
        Whether to generate the 3 default PNG figures (per-city mean trend,
        per-city P95 trend, globally city-adjusted trend). Defaults to
        ``True``.
    save_boxplot_plot : bool
        Whether to additionally generate the boxplot-per-year small-multiples
        figures (:meth:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer.build_boxplot_figure`) - one subplot
        per city, every year's raw hourly readings as a box, with the
        annual-mean trend line overlaid. Two files are written: a
        multi-column grid (``city_boxplot_grid_filename``) and a single-row
        layout with one column per city (``city_boxplot_row_filename``).
        Only takes effect if ``save_plots`` is also ``True``. Defaults to
        ``True``.
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
    save_boxplot_plot: bool = True
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
    city_boxplot_grid_filename: str = "fig_city_boxplot_grid.png"
    city_boxplot_row_filename: str = "fig_city_boxplot_row.png"
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

