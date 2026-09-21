# -*- coding: utf-8 -*-
"""epw_trend_analyzer
=====================

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
- Draw a **boxplot-per-year small-multiples figure** (one subplot per city,
  every year's ~8760 raw hourly readings as one box, with the fitted
  annual-mean trend line overlaid) via
  :meth:`EpwTrendAnalyzer.build_boxplot_figure` - the direct visual warming
  check, in addition to the
  line-plot city/global-adjusted figures above.
- Export reproducible CSV/XLSX tables, PNG figures, and a text/Markdown
  conclusion report (:meth:`EpwTrendAnalyzer.export_outputs`).

Two configuration dataclasses, :class:`TrendConfig` and :class:`OutputConfig`,
control the analysis logic and the output artefacts respectively; the main
class :class:`EpwTrendAnalyzer` orchestrates the whole pipeline, either step
by step or via the convenience :meth:`EpwTrendAnalyzer.run` method.

This used to be a single monolithic ``epw_trend_analyzer.py`` file; it was
split into this package in Fase 5 of ``INFORME_REVISION_GENERAL.md`` (§6),
mirroring ``degree_hours``'s earlier split, to keep each concern
(configuration, metrics, statistical models, plotting, reporting) in its
own, more manageable module while ``EpwTrendAnalyzer`` keeps its full,
unchanged public API (implemented via mixins combined in ``_core.py``).
The public import path (``from pyweatherfiles import EpwTrendAnalyzer,
TrendConfig, OutputConfig`` / ``from pyweatherfiles.epw_trend_analyzer
import EpwTrendAnalyzer, run_analysis, FixedEffectResult``) is unchanged.

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

from ..trend_stats import FixedEffectResult
from ._config import OutputConfig, TrendConfig
from ._core import EpwTrendAnalyzer, run_analysis

__all__ = [
    "EpwTrendAnalyzer",
    "TrendConfig",
    "OutputConfig",
    "FixedEffectResult",
    "run_analysis",
]

