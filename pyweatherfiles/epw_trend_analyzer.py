"""EPW temperature trend analyzer.

This module provides a configurable class-based workflow to analyze
long-term air-temperature trends from EPW files named as city_year.epw.

Main goals:
- Discover and parse EPW files from a root directory.
- Compute annual metrics from hourly dry-bulb temperature.
- Detect heatwave indicators with local percentile and absolute thresholds.
- Estimate city-level trends and a global fixed-effect trend controlling for city.
- Export reproducible tables, figures, and a text conclusion.
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
        """Validate logical constraints for configuration values."""
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
    """Configuration for outputs and persistence."""

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
        if not self.output_dir:
            raise ValueError("OutputConfig.output_dir is required.")
        if self.plot_dpi < 72:
            raise ValueError("plot_dpi should be >= 72.")


@dataclass
class FixedEffectResult:
    """Container for global fixed-effect model summary."""

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
    """Class-based analyzer for EPW temperature trend research.

    Workflow
    --------
    1) `discover_files()`
    2) `compute_metrics()`
    3) `fit_city_trends()`
    4) `fit_global_models()`
    5) `export_outputs()`

    You can call each method independently for custom studies, or call `run()`
    for the default full pipeline.
    """

    def __init__(self, trend_config: TrendConfig, output_config: OutputConfig):
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
        """Build analyzer from dictionary.

        Expected structure (either nested or flat):
        {
          "trend": {...},
          "output": {...}
        }
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
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_yaml(cls, config_path: Path) -> "EpwTrendAnalyzer":
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
        """Discover and parse `city_year.epw` files from root directory."""
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
        """Compute annual metrics and heatwave indicators for all files."""
        files_df = self._require(self.files_df, "files_df", "Call discover_files() first.")

        daily_df, annual_df = self._build_daily_and_annual_tables(files_df)
        annual_df = self._add_heatwave_metrics(annual_df, daily_df)

        self.daily_df = daily_df
        self.annual_df = annual_df
        return annual_df

    def fit_city_trends(self) -> pd.DataFrame:
        """Fit city-level linear trends for configured target metrics."""
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
        """Fit global fixed-effect models for primary and secondary targets."""
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
        """Fit one global fixed-effect model for the requested annual metric.

        This is useful when you want ad-hoc sensitivity runs beyond the
        configured primary/secondary targets.
        """
        annual_df = self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        if target not in annual_df.columns:
            raise ValueError(f"Target '{target}' is not available in annual metrics columns.")
        return self._fit_global_fixed_effect(annual_df, target)

    # ------------------------------------------------------------------
    # Plot and export
    # ------------------------------------------------------------------

    def plot(self) -> Dict[str, Path]:
        """Generate default figures and return created paths."""
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
        """Write configured CSV/TXT/PNG outputs and return paths."""
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
        """Run full pipeline and export outputs."""
        self.discover_files()
        self.compute_metrics()
        self.fit_city_trends()
        self.fit_global_models()
        return self.export_outputs()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_results(self) -> Dict[str, object]:
        """Return in-memory results for interactive analysis."""
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
        """Serialize effective analyzer configuration to JSON."""
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
        """Build a city-panel matplotlib figure without saving it.

        Returns
        -------
        (fig, axes)
            Figure and axes array so callers can further customize with
            matplotlib or seaborn before saving.
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
        """Build global adjusted trend figure without saving it.

        Returns
        -------
        (fig, ax, yearly_df)
            Matplotlib objects and yearly adjusted series for custom plotting.
        """
        annual_df = annual_df if annual_df is not None else self._require(self.annual_df, "annual_df", "Call compute_metrics() first.")
        return self._plot_global_adjusted(annual_df, output_path=None)

    def export_markdown_report(self, output_path: Optional[Path] = None) -> Path:
        """Export a detailed markdown report to help interpretation."""
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
        calc = DegreeHoursCalculator(epw_path)
        series = calc.epw_data["dry_bulb_temperature"].copy()
        series.name = "dry_bulb_temperature"
        return series

    def _build_daily_and_annual_tables(self, files_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
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
        cols = 3
        rows = int(math.ceil(n_cities / cols)) if n_cities > 0 else 1
        return rows, cols

    @staticmethod
    def _require(value, name: str, msg: str):
        if value is None or (isinstance(value, dict) and not value):
            raise RuntimeError(f"{name} is not ready. {msg}")
        return value

    @staticmethod
    def _to_serializable(data):
        if isinstance(data, dict):
            return {k: EpwTrendAnalyzer._to_serializable(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [EpwTrendAnalyzer._to_serializable(v) for v in data]
        if isinstance(data, Path):
            return str(data)
        return data


def run_analysis(root_dir: Path, output_dir: Path) -> Dict[str, Path]:
    """Compatibility helper that runs the full default pipeline."""
    analyzer = EpwTrendAnalyzer(
        trend_config=TrendConfig(root_dir=Path(root_dir)),
        output_config=OutputConfig(output_dir=Path(output_dir)),
    )
    return analyzer.run()

