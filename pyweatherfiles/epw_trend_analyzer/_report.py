# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_report.py
================================

``_ReportMixin`` — text/Markdown conclusion-report generation for
:class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`.

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). This is a mixin (not a standalone
class): see ``_core.py`` for how it combines with the rest of
``EpwTrendAnalyzer``'s mixins.
"""

from pathlib import Path
from typing import Optional


class _ReportMixin:
    """Plain-text and Markdown conclusion-report generation."""

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
    # Internal helpers
    # ------------------------------------------------------------------

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

