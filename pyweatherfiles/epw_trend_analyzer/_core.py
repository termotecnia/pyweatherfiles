# -*- coding: utf-8 -*-
"""
epw_trend_analyzer/_core.py
==============================

:class:`EpwTrendAnalyzer` — the orchestrator class combining the
``_MetricsMixin`` (discovery + annual metrics), ``_ModelsMixin`` (per-city
and global-fixed-effects trend fitting), ``_PlottingMixin`` (figures) and
``_ReportMixin`` (text/Markdown conclusion reports) mixins, plus
``run_analysis`` (module-level convenience function).

Extracted from the former monolithic ``epw_trend_analyzer.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6): the class itself keeps its full,
unchanged public API (``discover_files``, ``compute_metrics``,
``fit_city_trends``, ``fit_global_models``, ``plot``, ``export_outputs``,
``run``, etc. are still plain methods on ``EpwTrendAnalyzer``, just
implemented in the mixins above it in the MRO) — only the *implementation*
moved to keep each concern in its own, more manageable file. See
``pyweatherfiles/epw_trend_analyzer/__init__.py`` for the package-level
overview.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..trend_stats import FixedEffectResult
from .._export_utils import export_frames_to_excel
from ._config import OutputConfig, TrendConfig
from ._metrics import _MetricsMixin
from ._models import _ModelsMixin
from ._plotting import _PlottingMixin
from ._report import _ReportMixin


class EpwTrendAnalyzer(_MetricsMixin, _ModelsMixin, _PlottingMixin, _ReportMixin):
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
    hourly_by_city : dict
        ``{city: {year: pandas.Series}}`` - the raw hourly dry-bulb
        temperature series for every discovered EPW, cached as a side
        effect of :meth:`compute_metrics` and used by
        :meth:`build_boxplot_figure` to draw the boxplot-per-year figures.
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

        # NOTE: file discovery/classification delegates to
        # pyweatherfiles.epw_utils.classify_epw_files() inside discover_files()
        # (Fase 4, see _metrics.py).

        self.files_df: Optional[pd.DataFrame] = None
        self.daily_df: Optional[pd.DataFrame] = None
        self.hourly_by_city: Dict[str, Dict[int, pd.Series]] = {}
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
    # Orchestration: export and run
    # ------------------------------------------------------------------

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
            export_frames_to_excel(
                {
                    "annual_metrics": annual_df,
                    "city_trends": city_trends_df,
                    "global_trend": pd.DataFrame([asdict(v) for v in global_results.values()]),
                    "coverage_summary": coverage_df,
                },
                xlsx_path,
                index=False,
            )
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

    # ------------------------------------------------------------------
    # Shared internal utilities (used by every mixin)
    # ------------------------------------------------------------------

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

