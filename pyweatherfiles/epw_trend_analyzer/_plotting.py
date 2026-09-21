# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_plotting.py
==================================

``_PlottingMixin`` — figure-building methods for
:class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer` (per-city
trend panel, globally city-adjusted trend, and the boxplot-per-year
small-multiples figure).

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). This is a mixin (not a standalone
class): see ``_core.py`` for how it combines with the rest of
``EpwTrendAnalyzer``'s mixins.
"""

import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy.stats import linregress


class _PlottingMixin:
    """Figure-building methods (per-city trend, global-adjusted, boxplots)."""

    # ------------------------------------------------------------------
    # Public: orchestration
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

            if self.output_config.save_boxplot_plot:
                boxplot_grid_path = self.output_config.output_dir / self.output_config.city_boxplot_grid_filename
                boxplot_row_path = self.output_config.output_dir / self.output_config.city_boxplot_row_filename
                n_cities = annual_df["city"].nunique()

                fig_boxplot_grid, _ = self.build_boxplot_figure(
                    annual_df=annual_df, trend_df=city_trends_df, ncols=3,
                )
                fig_boxplot_row, _ = self.build_boxplot_figure(
                    annual_df=annual_df, trend_df=city_trends_df, ncols=max(n_cities, 1),
                )
                fig_boxplot_grid.savefig(boxplot_grid_path, dpi=self.output_config.plot_dpi)
                fig_boxplot_row.savefig(boxplot_row_path, dpi=self.output_config.plot_dpi)
                plt.close(fig_boxplot_grid)
                plt.close(fig_boxplot_row)

                created["fig_city_boxplot_grid"] = boxplot_grid_path
                created["fig_city_boxplot_row"] = boxplot_row_path

        self.outputs.update(created)
        return created

    # ------------------------------------------------------------------
    # Public: figure builders (no I/O)
    # ------------------------------------------------------------------

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

    def build_boxplot_figure(
        self,
        annual_df: Optional[pd.DataFrame] = None,
        trend_df: Optional[pd.DataFrame] = None,
        target_col: str = "t_mean_annual",
        ncols: int = 3,
        title: Optional[str] = None,
    ):
        """Build a per-city boxplot-per-year panel figure (one subplot per
        city; every year's ~8760 raw hourly dry-bulb temperature readings as
        one box, with the fitted annual-mean trend line overlaid) **without**
        saving it to disk - the direct visual warming check
        (each city/climate analysed fully
        independently, never pooled).

        Args:
            annual_df (pandas.DataFrame, optional): Annual metrics table.
                Defaults to :attr:`annual_df` (requires
                :meth:`compute_metrics`).
            trend_df (pandas.DataFrame, optional): Per-city trend table used
                to draw the overlaid trend line. Defaults to
                :attr:`city_trends_df` (requires :meth:`fit_city_trends`).
            target_col (str, optional): Annual-metric column whose fitted
                OLS trend line is overlaid on each city's boxplot. Defaults
                to ``'t_mean_annual'`` (the raw hourly boxplots always show
                dry-bulb temperature, i.e. :attr:`hourly_by_city`,
                regardless of *target_col*).
            ncols (int, optional): Number of columns in the subplot grid.
                Use ``ncols=<number of cities>`` for a single-row layout.
                Defaults to 3.
            title (str, optional): Figure title. ``None`` (default) omits
                the ``suptitle``.

        Returns:
            tuple[matplotlib.figure.Figure, numpy.ndarray]: ``(fig, axes)``
            so callers can further customise it before calling
            ``fig.savefig(...)`` themselves.

        Raises:
            RuntimeError: If :meth:`compute_metrics`/:meth:`fit_city_trends`
                have not been called yet.

        Example:
            >>> analyzer.compute_metrics(); analyzer.fit_city_trends()  # doctest: +SKIP
            >>> fig, axes = analyzer.build_boxplot_figure(ncols=5)  # doctest: +SKIP
            >>> fig.savefig("fig_hourly_temperature_boxplot_1x5.png", dpi=200)  # doctest: +SKIP
        """
        annual_df = annual_df if annual_df is not None else self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        trend_df = trend_df if trend_df is not None else self._require(self.city_trends_df, "city_trends_df", "Call fit_city_trends() first.")
        return self._plot_city_boxplots(
            annual_df=annual_df,
            trend_df=trend_df,
            target_col=target_col,
            ncols=ncols,
            output_path=None,
            title=title,
        )

    # ------------------------------------------------------------------
    # Internal drawing helpers
    # ------------------------------------------------------------------

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

    def _plot_city_boxplots(
        self,
        annual_df: pd.DataFrame,
        trend_df: pd.DataFrame,
        target_col: str,
        ncols: int,
        output_path: Optional[Path],
        title: Optional[str],
    ):
        """Build (and optionally save) the per-city boxplot-per-year panel
        figure used by :meth:`build_boxplot_figure`/:meth:`plot`: one
        subplot per city, drawing every year's raw hourly dry-bulb
        temperature readings (from :attr:`hourly_by_city`) as a box, with
        the fitted OLS trend line (from *trend_df*) overlaid.

        Args:
            annual_df (pandas.DataFrame): Annual metrics table (used only to
                enumerate which cities/years to draw).
            trend_df (pandas.DataFrame): Per-city trend table (as returned
                by :meth:`fit_city_trends`).
            target_col (str): Annual-metric column whose fitted trend line
                is overlaid.
            ncols (int): Number of columns in the subplot grid.
            output_path (pathlib.Path or None): If given, the figure is
                saved (at :attr:`OutputConfig.plot_dpi`) and closed;
                otherwise returned open for further editing.
            title (str or None): Overall figure title (``fig.suptitle``);
                omitted if ``None``.

        Returns:
            tuple[matplotlib.figure.Figure, numpy.ndarray]: ``(fig, axes)``.
        """
        cities = sorted(annual_df["city"].unique())
        nrows = int(math.ceil(len(cities) / ncols)) if cities else 1

        fig, axes = plt.subplots(nrows, ncols, figsize=(4.6 * ncols, 3.8 * nrows), squeeze=False)
        axes_flat = axes.flatten()

        for i, city in enumerate(cities):
            ax = axes_flat[i]
            years = sorted(self.hourly_by_city.get(city, {}).keys())
            data_by_year = [self.hourly_by_city[city][y].to_numpy(dtype=float) for y in years]

            ax.boxplot(
                data_by_year, positions=years, widths=0.65, showfliers=False,
                patch_artist=True, manage_ticks=False,
                boxprops=dict(facecolor="tab:blue", alpha=0.55, edgecolor="0.25"),
                medianprops=dict(color="black", linewidth=1.3),
                whiskerprops=dict(color="0.35"), capprops=dict(color="0.35"),
                showmeans=True,
                meanprops=dict(marker="D", markerfacecolor="white", markeredgecolor="black", markersize=4),
            )

            row = trend_df[(trend_df["city"] == city) & (trend_df["target"] == target_col)]
            if not row.empty and np.isfinite(row.iloc[0]["slope_c_per_year"]) and len(years) >= 2:
                slope = float(row.iloc[0]["slope_c_per_year"])
                intercept = float(row.iloc[0]["intercept"])
                pvalue = float(row.iloc[0]["p_value"])
                x_line = np.array([min(years), max(years)], dtype=float)
                sig = " *" if pvalue < 0.05 else ""
                ax.plot(
                    x_line, intercept + slope * x_line,
                    color="crimson", linestyle="--", linewidth=1.8, zorder=5,
                    label=f"trend {slope:+.3f} C/yr ({slope * 10:+.2f} C/decade), p={pvalue:.3f}{sig}",
                )
                ax.legend(fontsize=7, loc="upper left")

            ax.set_title(city)
            ax.set_xlabel("year")
            ax.set_ylabel("dry-bulb temperature (C)")
            ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            ax.grid(alpha=0.3)

        for j in range(len(cities), len(axes_flat)):
            axes_flat[j].axis("off")

        if title:
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
        x_design, names = self._build_fe_design(df)
        beta = np.linalg.pinv(x_design.T @ x_design) @ (x_design.T @ y)

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

