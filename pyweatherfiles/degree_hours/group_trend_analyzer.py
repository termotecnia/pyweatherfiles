# -*- coding: utf-8 -*-
"""
degree_hours/group_trend_analyzer.py
=======================================

:class:`EpwGroupTrendAnalyzer` — runs :class:`~pyweatherfiles.degree_hours.calculator.DegreeHoursCalculator`
over an entire *set* of EPW files (e.g. a whole folder of multi-year
records), automatically classified into named groups (e.g. one per
city/climate) from each filename via a configurable regex, and adds
per-group year-over-year trend statistics plus small-multiples plotting —
ideal for "20 years x N climates, never pooled together" analyses.

Extracted from the former monolithic ``degree_hours.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6); see ``pyweatherfiles/degree_hours/__init__.py``
for the package-level overview of all three classes.
"""

import contextlib
import io
import os
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..session_manager import save_object_session
from .._export_utils import export_frames_to_excel
from .calculator import DegreeHoursCalculator


class EpwGroupTrendAnalyzer:
    """
    Batch degree-hour (and auxiliary climate-variable) analysis across an
    entire set of EPW files, automatically classified into named groups
    (e.g. one group per city/climate) from each EPW's filename, plus
    per-group year-over-year trend statistics and small-multiples plotting.

    Unlike :class:`~pyweatherfiles.degree_hours.EpwBatchAnalyzer` — which
    compares a handful of individually-named EPWs (e.g. "TMY vs. official
    file vs. one real year") in a single MultiIndex table — this class
    targets the opposite situation: *many* EPWs covering *several
    independent climates* over *many years each* (e.g.
    ``longterm_epw/granada_2005.epw`` … ``longterm_epw/seville_2025.epw``),
    where each climate must be analysed on its own — never pooled/averaged
    with another — to expose a genuine multi-year trend (as used for
    Section 3.1 of the manuscript).

    Workflow
    --------
    1. Instantiate with either *epw_dir* (a folder scanned for ``*.epw``)
       or an explicit *epw_paths* list, plus a *filename_pattern* regex
       with named groups ``group`` (the classification key, e.g. city) and
       ``year`` — used to classify every file (:attr:`file_groups`).
    2. Call :meth:`run` to compute, for every file, the requested
       degree-hour *hours_scenarios* (each with its own hour-of-day mask
       and heating/cooling/both mode) plus any *extra_epw_variables*,
       collecting everything into the long-format :attr:`results`
       DataFrame (one row per group-year).
    3. Call :meth:`compute_trends` for the linear year-over-year regression
       of any result column, per group (never pooled) — or
       :meth:`fit_global_trend` for the equivalent *global* fixed-effects
       trend common to every group at once (same estimator as
       :meth:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer.fit_global_model`).
    4. Call :meth:`plot_variable_grid` (one variable, small multiples — one
       subplot per group) or :meth:`plot_overview_grid` (several variables
       combined with every group in a single grid, either "rows=variables,
       columns=groups" or transposed) to visualise.

    Attributes
    ----------
    inputs : dict
        Every constructor argument, stored verbatim for reproducibility and
        inspection (``epw_dir``, ``epw_paths``, ``filename_pattern``,
        ``setpoint_source``, ``hours_scenarios``, ``extra_epw_variables``,
        ``scale_factors``, ``group_order``, ``group_labels``,
        ``group_colors``, ``group_zone``, ``year_override``).
    file_groups : dict
        ``{group: {year: epw_path}}``, populated from *epw_dir*/*epw_paths*
        using *filename_pattern*.
    results : pd.DataFrame or None
        Long-format table, one row per ``(group, year)``, populated by
        :meth:`run`. Columns depend on *hours_scenarios* /
        *extra_epw_variables* (e.g. ``heating_dh_allday``,
        ``cooling_dh_night_0_8h``, ``global_horizontal_radiation_sum``).
    trend_stats_ : dict[str, pd.DataFrame]
        Cache of :meth:`compute_trends` results, keyed by *value_col*; each
        DataFrame is indexed by *group* with columns ``n, slope, intercept,
        r2, pvalue, significant``.
    calculators : dict[str, object]
        ``{"<group>_<year>": DegreeHoursCalculator}`` for every processed
        file, giving access to the full hourly data if needed.

    Example
    -------
    >>> from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer
    >>> analyzer = EpwGroupTrendAnalyzer(
    ...     epw_dir="longterm_epw",
    ...     setpoint_source={"type": "constant", "heating": 20.0, "cooling": 25.0},
    ...     hours_scenarios={
    ...         "allday": {"hours": None, "mode": "both"},
    ...         "night_0_8h": {"hours": list(range(8)), "mode": "cooling"},
    ...     },
    ...     extra_epw_variables={"global_horizontal_radiation": ["sum"]},
    ...     scale_factors={"global_horizontal_radiation_sum": 0.001},
    ... )  # doctest: +SKIP
    >>> df = analyzer.run()  # doctest: +SKIP
    >>> trends = analyzer.compute_trends("heating_dh_allday")  # doctest: +SKIP
    >>> analyzer.plot_variable_grid("heating_dh_allday", ylabel="HDH (°C·h)")  # doctest: +SKIP
    >>> analyzer.plot_overview_grid(
    ...     variables=[
    ...         ("heating_dh_allday", "HDH (°C·h)", "Heating DH"),
    ...         ("cooling_dh_night_0_8h", "Night CDH (°C·h)", "NCDH (night cooling degree hours)"),
    ...     ],
    ...     horizontal=True, transpose=True,
    ... )  # doctest: +SKIP
    """

    _DEFAULT_FILENAME_PATTERN = r'^(?P<group>[a-zA-Z]+)_(?P<year>\d{4})\.epw$'
    _VALID_AGGFUNCS = {'sum', 'mean', 'max', 'min', 'std'}

    def __init__(
        self,
        epw_dir: Optional[str] = None,
        epw_paths: Optional[List[str]] = None,
        filename_pattern: str = _DEFAULT_FILENAME_PATTERN,
        setpoint_source: Optional[Union[str, Dict]] = None,
        hours_scenarios: Optional[Dict[str, Dict]] = None,
        extra_epw_variables: Optional[Dict[str, List[str]]] = None,
        scale_factors: Optional[Dict[str, float]] = None,
        group_order: Optional[List[str]] = None,
        group_labels: Optional[Dict[str, str]] = None,
        group_colors: Optional[Dict[str, str]] = None,
        group_zone: Optional[Dict[str, str]] = None,
        year_override: Optional[int] = None,
    ):
        """
        Parameters
        ----------
        epw_dir : str, optional
            Folder scanned (non-recursively) for ``*.epw`` files. Ignored
            if *epw_paths* is given.
        epw_paths : list of str, optional
            Explicit list of EPW paths to classify/process, instead of
            scanning *epw_dir*.
        filename_pattern : str, optional
            Regex with named groups ``group`` (classification key, e.g.
            city) and ``year`` (4-digit), matched against
            ``os.path.basename(path)``. Default matches
            ``'<group>_<year>.epw'`` (e.g. ``'granada_2005.epw'``). Files
            that do not match are skipped with a warning.
        setpoint_source : str or dict, optional
            Forwarded to every :meth:`~pyweatherfiles.degree_hours.calculator.DegreeHoursCalculator.calculate` call
            (IDF path or setpoint configuration dict). Defaults to
            ``{'type': 'constant', 'heating': 20.0, 'cooling': 25.0}``.
        hours_scenarios : dict, optional
            ``{scenario_label: {'hours': list_of_int_or_None, 'mode':
            'heating'|'cooling'|'both'}}``. One degree-hour calculation is
            run per scenario; results are stored as
            ``heating_dh_<label>`` / ``cooling_dh_<label>`` columns.
            Defaults to a single ``'allday'`` scenario (``mode='both'``,
            all 24 hours).
        extra_epw_variables : dict, optional
            ``{epw_variable_name: [aggfunc, ...]}`` — additional annual
            climate variables to extract alongside degree-hours (e.g.
            ``{'global_horizontal_radiation': ['sum']}``). Supported
            aggfuncs: ``'sum'``, ``'mean'``, ``'max'``, ``'min'``, ``'std'``.
            Columns are named ``<variable>_<aggfunc>``.
        scale_factors : dict, optional
            ``{result_column_name: factor}`` applied by multiplication
            after computation (e.g. convert Wh/m² to kWh/m² with
            ``{'global_horizontal_radiation_sum': 0.001}``).
        group_order : list of str, optional
            Explicit ordering of groups (e.g. coldest-to-warmest climate)
            used by :meth:`run`'s iteration order and by every plotting
            method. Defaults to the sorted group keys discovered.
        group_labels, group_colors, group_zone : dict, optional
            Optional ``{group: display_label / matplotlib_color / zone_tag}``
            maps used purely for display in the plotting methods. Missing
            entries fall back to the raw group key / default color cycle /
            ``''``.
        year_override : int, optional
            If given, overrides the year assigned to every EPW's hourly
            index (forwarded to :class:`~pyweatherfiles.degree_hours.calculator.DegreeHoursCalculator`) instead of
            the year parsed from the filename.

        Raises
        ------
        ValueError
            If neither *epw_dir* nor *epw_paths* is provided.

        Example
        -------
        >>> analyzer = EpwGroupTrendAnalyzer(epw_dir="longterm_epw")  # doctest: +SKIP
        """
        if epw_dir is None and not epw_paths:
            raise ValueError("Provide either 'epw_dir' or 'epw_paths'.")

        if setpoint_source is None:
            setpoint_source = {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}
        if hours_scenarios is None:
            hours_scenarios = {'allday': {'hours': None, 'mode': 'both'}}

        self.inputs: Dict = {
            'epw_dir': epw_dir,
            'epw_paths': list(epw_paths) if epw_paths else None,
            'filename_pattern': filename_pattern,
            'setpoint_source': setpoint_source,
            'hours_scenarios': hours_scenarios,
            'extra_epw_variables': extra_epw_variables or {},
            'scale_factors': scale_factors or {},
            'group_order': list(group_order) if group_order else None,
            'group_labels': group_labels or {},
            'group_colors': group_colors or {},
            'group_zone': group_zone or {},
            'year_override': year_override,
        }

        self.file_groups: Dict[str, Dict[int, str]] = {}
        self.results: Optional[pd.DataFrame] = None
        self.trend_stats_: Dict[str, pd.DataFrame] = {}
        self.calculators: Dict[str, 'DegreeHoursCalculator'] = {}

        self._discover_files()

    # -------------------------------------------------------------------------
    # Discovery / classification
    # -------------------------------------------------------------------------

    def _discover_files(self) -> Dict[str, Dict[int, str]]:
        """Classify every EPW into ``{group: {year: path}}`` via *filename_pattern*."""
        from ..epw_utils import classify_epw_files

        found = classify_epw_files(
            epw_dir=self.inputs['epw_dir'],
            epw_paths=self.inputs['epw_paths'],
            filename_pattern=self.inputs['filename_pattern'],
        )
        self.file_groups = found
        if self.inputs['group_order'] is None:
            self.inputs['group_order'] = sorted(found.keys())
        return found

    # -------------------------------------------------------------------------
    # Core computation
    # -------------------------------------------------------------------------

    def run(self, save_session: bool = True, session_dir: Optional[str] = None) -> pd.DataFrame:
        """
        Compute every requested degree-hour scenario and extra EPW variable
        for every classified file, assembling :attr:`results`.

        Parameters
        ----------
        save_session : bool, optional
            If ``True`` (default), persist a reproducible ``.pkl``/``.json``
            session (inputs summary + results) via
            :func:`~pyweatherfiles.session_manager.save_object_session`.
        session_dir : str, optional
            Directory for the session files. Defaults to *epw_dir* (or the
            directory of the first *epw_paths* entry).

        Returns
        -------
        pd.DataFrame
            Long-format table, one row per ``(group, year)``. Also stored
            in :attr:`results`.

        Raises
        ------
        RuntimeError
            If no EPW file could be processed.

        Example
        -------
        >>> analyzer = EpwGroupTrendAnalyzer(epw_dir="longterm_epw")  # doctest: +SKIP
        >>> df = analyzer.run()  # doctest: +SKIP
        """
        setpoint_source = self.inputs['setpoint_source']
        hours_scenarios = self.inputs['hours_scenarios']
        extra_vars = self.inputs['extra_epw_variables']
        scale = self.inputs['scale_factors']
        year_override = self.inputs['year_override']

        bad_aggs = {
            agg for aggs in extra_vars.values() for agg in aggs
            if agg not in self._VALID_AGGFUNCS
        }
        if bad_aggs:
            raise ValueError(
                f"Unsupported aggfunc(s) {bad_aggs} in extra_epw_variables. "
                f"Valid options: {sorted(self._VALID_AGGFUNCS)}"
            )

        rows: List[Dict] = []
        for group in self.inputs['group_order']:
            years_map = self.file_groups.get(group, {})
            for year in sorted(years_map):
                path = years_map[year]
                calc_key = f"{group}_{year}"
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        calc = DegreeHoursCalculator(path, year=year_override or year)

                        row: Dict = {'group': group, 'year': year}
                        for label, cfg in hours_scenarios.items():
                            hrs = cfg.get('hours')
                            mos = cfg.get('months')
                            mode = cfg.get('mode', 'both')
                            invert_cool = cfg.get('invert_cooling', False)
                            res = calc.calculate(
                                setpoint_source, frequency=['yearly'], mode=mode,
                                hours=hrs, months=mos, invert_cooling=invert_cool,
                                save_session=False,
                            )['yearly']
                            if mode in ('heating', 'both'):
                                row[f'heating_dh_{label}'] = float(res['heating_dh'].sum())
                            if mode in ('cooling', 'both'):
                                row[f'cooling_dh_{label}'] = float(res['cooling_dh'].sum())

                        for var, aggs in extra_vars.items():
                            if var not in calc.epw_data.columns:
                                print(f"[WARNING] '{var}' not found in {calc_key}; skipping.")
                                continue
                            series = calc.epw_data[var]
                            for agg in aggs:
                                col = f'{var}_{agg}'
                                val = float(getattr(series, agg)())
                                row[col] = val * scale.get(col, 1.0)

                    self.calculators[calc_key] = calc
                    rows.append(row)
                    metrics_str = ", ".join(
                        f"{k}={v:.1f}" for k, v in row.items() if k not in ('group', 'year')
                    )
                    print(f"[OK] {group:12s} {year} -> {metrics_str}")
                except Exception as e:
                    print(f"[WARNING] Skipping {group} {year}: {e}")

        if not rows:
            raise RuntimeError("No EPW files could be processed.")

        self.results = pd.DataFrame(rows).sort_values(['group', 'year']).reset_index(drop=True)
        print(f"\n[INFO] EpwGroupTrendAnalyzer.run() completed: {len(self.results)} group-year rows.")

        if save_session:
            _dir = session_dir or self.inputs['epw_dir'] or (
                os.path.dirname(os.path.abspath(self.inputs['epw_paths'][0]))
                if self.inputs['epw_paths'] else os.getcwd()
            )
            try:
                save_object_session(self, "EpwGroupTrendAnalyzer", {
                    'epw_dir': self.inputs['epw_dir'] or '',
                    'n_groups': str(len(self.file_groups)),
                    'n_files': str(sum(len(v) for v in self.file_groups.values())),
                }, session_dir=_dir)
            except Exception as _e:
                print(f"[SESSION] Could not save the session: {_e}")

        return self.results

    # -------------------------------------------------------------------------
    # Trend statistics
    # -------------------------------------------------------------------------

    def compute_trends(self, value_col: str) -> pd.DataFrame:
        """
        Linear year-over-year regression of *value_col*, computed
        independently for every group (never pooled across groups).

        Parameters
        ----------
        value_col : str
            A numeric column of :attr:`results` (e.g. ``'heating_dh_allday'``).

        Returns
        -------
        pd.DataFrame
            Indexed by *group*, columns ``n, slope, intercept, r2, pvalue,
            significant``. Also cached in :attr:`trend_stats_`.

        Raises
        ------
        ValueError
            If :meth:`run` has not been called yet, or *value_col* does not
            exist in :attr:`results`.

        Example
        -------
        >>> analyzer.compute_trends("heating_dh_allday")  # doctest: +SKIP
        """
        if self.results is None:
            raise ValueError("No results yet. Call run() first.")
        if value_col not in self.results.columns:
            raise ValueError(
                f"'{value_col}' not found in results. Available: "
                f"{[c for c in self.results.columns if c not in ('group', 'year')]}"
            )

        from scipy import stats as _stats

        rows = []
        for group in self.inputs['group_order']:
            sub = self.results[self.results['group'] == group].dropna(subset=[value_col])
            if len(sub) < 3:
                rows.append({
                    'group': group, 'n': len(sub), 'slope': np.nan, 'intercept': np.nan,
                    'r2': np.nan, 'pvalue': np.nan, 'significant': False,
                })
                continue
            r = _stats.linregress(
                sub['year'].values.astype(float), sub[value_col].values.astype(float)
            )
            rows.append({
                'group': group, 'n': len(sub), 'slope': r.slope, 'intercept': r.intercept,
                'r2': r.rvalue ** 2, 'pvalue': r.pvalue, 'significant': bool(r.pvalue < 0.05),
            })

        df = pd.DataFrame(rows).set_index('group')
        self.trend_stats_[value_col] = df
        return df

    def fit_global_trend(self, value_col: str):
        """
        Fit a **global** fixed-effects linear trend, ``value_col ~ year +
        C(group)``, across every group at once — unlike :meth:`compute_trends`
        (which fits each group's trend fully independently), this estimates
        the rate of change common to *all* groups after controlling for
        each group's own baseline level (a panel-data/fixed-effects
        estimator, the same technique used for the manuscript's global
        warming-rate estimate). Reuses the exact same estimator as
        :meth:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer.fit_global_model`
        via the shared
        :func:`~pyweatherfiles.trend_stats.fit_fixed_effects_model` (see
        ``INFORME_REVISION_GENERAL.md`` §3.3/Fase 4 — before this method
        existed, only ``EpwTrendAnalyzer`` had a global fixed-effects
        model; ``EpwGroupTrendAnalyzer`` could only fit independent
        per-group regressions via :meth:`compute_trends`).

        Parameters
        ----------
        value_col : str
            A numeric column of :attr:`results` (e.g. ``'heating_dh_allday'``).

        Returns
        -------
        pyweatherfiles.trend_stats.FixedEffectResult
            The fitted model summary. Note the field names are inherited
            from their original city-centric use in ``EpwTrendAnalyzer``:
            ``slope_c_per_year`` here means "slope per year in
            *value_col*'s own units" (not necessarily degrees Celsius —
            e.g. °C·h/year for a degree-hours column), and ``n_cities``
            means "number of groups".

        Raises
        ------
        ValueError
            If :meth:`run` has not been called yet, *value_col* does not
            exist in :attr:`results`, or there are not enough observations
            relative to the number of groups (degrees of freedom exhausted).

        Example
        -------
        >>> analyzer.run()  # doctest: +SKIP
        >>> global_result = analyzer.fit_global_trend("heating_dh_allday")  # doctest: +SKIP
        >>> global_result.slope_c_per_year  # doctest: +SKIP
        """
        if self.results is None:
            raise ValueError("No results yet. Call run() first.")
        if value_col not in self.results.columns:
            raise ValueError(
                f"'{value_col}' not found in results. Available: "
                f"{[c for c in self.results.columns if c not in ('group', 'year')]}"
            )

        from ..trend_stats import fit_fixed_effects_model

        return fit_fixed_effects_model(self.results, target=value_col, group_col='group')

    # -------------------------------------------------------------------------
    # Display helpers (labels/colors/zone tags — purely cosmetic)
    # -------------------------------------------------------------------------

    def _group_label(self, group: str) -> str:
        return self.inputs['group_labels'].get(group, group.capitalize())

    def _group_color(self, group: str, idx: int):
        import matplotlib.pyplot as plt
        colors = self.inputs['group_colors']
        if group in colors:
            return colors[group]
        cycle = plt.rcParams['axes.prop_cycle'].by_key().get('color', ['tab:blue'])
        return cycle[idx % len(cycle)]

    def _group_zone(self, group: str) -> str:
        return self.inputs['group_zone'].get(group, '')

    # -------------------------------------------------------------------------
    # Plotting: single-variable small multiples
    # -------------------------------------------------------------------------

    def _draw_group_subplot(
        self, ax, group, idx, value_col, ylabel, show_ylabel=True, show_xlabel=True,
        horizontal=False, show_group_title=True, tick_labelsize: float = 9.0,
    ):
        """Draw one group's year-by-year bars + its own OLS trend line.

        Parameters
        ----------
        horizontal : bool, optional
            If ``True``, draw horizontal bars (years on the vertical axis,
            *value_col* on the horizontal axis) and the matching trend
            line, instead of the default vertical layout.
        show_group_title : bool, optional
            If ``True`` (default), prefix the subplot title with the
            group's label/zone (e.g. ``"Madrid (D3)"``). Set to ``False``
            when the group is already identified elsewhere (e.g. a row
            annotation in :meth:`plot_overview_grid` with
            ``transpose=True``), so the subplot title only shows the
            trend statistics.
        """
        import matplotlib.ticker as mticker

        sub = self.results[self.results['group'] == group].sort_values('year')
        years = sub['year'].values
        values = sub[value_col].values
        color = self._group_color(group, idx)

        if horizontal:
            ax.barh(years, values, height=0.7, color=color, alpha=0.75, zorder=2)
        else:
            ax.bar(years, values, width=0.7, color=color, alpha=0.75, zorder=2)

        if len(sub) >= 3:
            trends = self.trend_stats_.get(value_col)
            if trends is None or group not in trends.index:
                trends = self.compute_trends(value_col)
            r = trends.loc[group]
            if pd.notna(r['slope']):
                x_line = np.array([years.min(), years.max()], dtype=float)
                y_line = r['intercept'] + r['slope'] * x_line
                if horizontal:
                    ax.plot(y_line, x_line, color='black', linestyle='--', linewidth=1.6, zorder=3)
                else:
                    ax.plot(x_line, y_line, color='black', linestyle='--', linewidth=1.6, zorder=3)
                sig_star = ' *' if r['significant'] else ''
                stats_txt = (
                    f"slope={r['slope']:+.1f}/yr, R²={r['r2']:.2f}, "
                    f"p={r['pvalue']:.3f}{sig_star}"
                )
            else:
                stats_txt = "insufficient data for trend"
        else:
            stats_txt = "insufficient data for trend"

        if show_group_title:
            zone = self._group_zone(group)
            title = f"{self._group_label(group)} ({zone})" if zone else self._group_label(group)
            ax.set_title(f"{title}\n{stats_txt}", fontsize=10.0)
        else:
            ax.set_title(stats_txt, fontsize=10.0)

        if horizontal:
            if show_ylabel:
                ax.set_ylabel('Year', fontsize=10)
            if show_xlabel:
                ax.set_xlabel(ylabel, fontsize=10)
            ax.grid(True, axis='x', alpha=0.3)
            ax.tick_params(axis='both', labelsize=tick_labelsize)
            ax.set_ylim(years.min() - 1, years.max() + 1)
            ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _pos: f"{int(round(y))}"))
        else:
            if show_ylabel:
                ax.set_ylabel(ylabel, fontsize=10)
            if show_xlabel:
                ax.set_xlabel('Year', fontsize=10)
            ax.grid(True, axis='y', alpha=0.3)
            ax.tick_params(axis='both', labelsize=tick_labelsize)
            ax.set_xlim(years.min() - 1, years.max() + 1)
            ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _pos: f"{int(round(x))}"))

    @staticmethod
    def _harmonize_lim(axes_list, axis='y'):
        """Apply the widest (min, max) limits across every axis to all of them.

        Parameters
        ----------
        axis : {'y', 'x'}, optional
            Which axis to harmonise: ``'y'`` (default) for vertical bar
            layouts, ``'x'`` for horizontal bar layouts (where the value
            is plotted on the x-axis).
        """
        if axis == 'x':
            los, his = zip(*(a.get_xlim() for a in axes_list))
        else:
            los, his = zip(*(a.get_ylim() for a in axes_list))
        lo, hi = min(los), max(his)
        for a in axes_list:
            if axis == 'x':
                a.set_xlim(lo, hi)
            else:
                a.set_ylim(lo, hi)

    def plot_variable_grid(
        self,
        value_col: str,
        ylabel: Optional[str] = None,
        suptitle: Optional[str] = None,
        ncols: int = 3,
        tick_labelsize: float = 9.0,
        harmonize_ylim: bool = True,
        out_path: Optional[str] = None,
        show: bool = False,
    ):
        """
        Small-multiples grid for a single result column: one subplot per
        group, each with its own bars + OLS trend line (never pooled).

        Parameters
        ----------
        value_col : str
            Column of :attr:`results` to plot (e.g. ``'heating_dh_allday'``).
        ylabel : str, optional
            Y-axis label. Defaults to *value_col*.
        suptitle : str, optional
            Figure super-title.
        ncols : int, optional
            Number of columns in the subplot grid (default 3).
        tick_labelsize : float, optional
            Font size for axis tick labels (numeric labels). Default ``9.0``.
        harmonize_ylim : bool, optional
            If ``True`` (default), force the same y-axis range on every
            subplot (the union of each group's autoscaled range) so trend
            lines are visually comparable across groups.
        out_path : str, optional
            If given, the figure is saved to this path (``dpi=300``).
        show : bool, optional
            If ``True``, call ``plt.show()``. Default ``False`` (useful in
            batch/headless scripts).

        Returns
        -------
        matplotlib.figure.Figure

        Example
        -------
        >>> analyzer.plot_variable_grid(
        ...     "heating_dh_allday", ylabel="HDH$_{20}$ (°C·h)",
        ...     out_path="fig3a_heating_dh_20_by_city.png",
        ... )  # doctest: +SKIP
        """
        import matplotlib.pyplot as plt

        if self.results is None:
            raise ValueError("No results yet. Call run() first.")

        groups = self.inputs['group_order']
        n = len(groups)
        nrows = int(np.ceil(n / ncols))
        super_cols = max(1, ncols * 2)
        fig = plt.figure(figsize=(4.2 * ncols, 3.6 * nrows))
        gs = fig.add_gridspec(nrows, super_cols)

        axes_used = []
        full_rows = n // ncols
        remainder = n % ncols
        for i, group in enumerate(groups):
            r, c = divmod(i, ncols)
            if r < full_rows or remainder == 0:
                # Regular rows: each logical column spans 2 GridSpec columns.
                c0 = c * 2
            else:
                # Last partial row: center the used slots.
                idx_in_partial_row = c
                partial_width = remainder * 2
                left_pad = (super_cols - partial_width) // 2
                c0 = left_pad + idx_in_partial_row * 2
            ax = fig.add_subplot(gs[r, c0:c0 + 2])
            self._draw_group_subplot(
                ax, group, i, value_col, ylabel or value_col,
                show_ylabel=(c == 0), show_xlabel=True,
                tick_labelsize=tick_labelsize,
            )
            axes_used.append(ax)

        if harmonize_ylim:
            self._harmonize_lim(axes_used, axis='y')

        if suptitle:
            fig.suptitle(suptitle, fontsize=12, y=1.02)
        fig.tight_layout()

        if out_path:
            fig.savefig(out_path, dpi=300, bbox_inches='tight')
            print(f"[FIGURE] Saved -> {out_path}")
        if show:
            plt.show()
        else:
            plt.close(fig)
        return fig

    # -------------------------------------------------------------------------
    # Plotting: multi-variable overview grid
    # -------------------------------------------------------------------------

    def plot_overview_grid(
        self,
        variables: Optional[List[Tuple[str, str, str]]] = None,
        harmonize_ylim: bool = True,
        out_path: Optional[str] = None,
        show: bool = False,
        horizontal: bool = False,
        transpose: bool = False,
    ):
        """
        Overview figure combining several variables and every group in a
        single small-multiples grid (e.g. the manuscript's
        ``fig3_overview_grid_by_city.png``): every cell is a group's own
        bars + OLS trend line for that variable, so the whole indicator
        battery and every climate can be read at a glance without ever
        averaging distinct climates together.

        Parameters
        ----------
        variables : list of (value_col, ylabel, title), optional
            One tuple per variable. Defaults to every numeric column in
            :attr:`results` other than ``'group'``/``'year'``, each
            row/column labelled with its own column name.
        harmonize_ylim : bool, optional
            If ``True`` (default), harmonise the value-axis range across
            all groups for each variable (a trend line dipping below zero
            in one group must not distort the visual scale of the
            others). Applies to the y-axis in the default vertical-bar
            layout, or the x-axis when *horizontal* is ``True``.
        out_path : str, optional
            If given, the figure is saved to this path (``dpi=300``).
        show : bool, optional
            If ``True``, call ``plt.show()``. Default ``False``.
        horizontal : bool, optional
            If ``True``, draw horizontal bars (years on the vertical axis,
            value on the horizontal axis) in every cell instead of the
            default vertical bars.
        transpose : bool, optional
            If ``True``, lay the grid out as *one row per group* and *one
            column per variable* (better suited to a portrait-oriented
            page when there are more groups than variables) instead of
            the default *one row per variable, one column per group*.

        Returns
        -------
        matplotlib.figure.Figure

        Example
        -------
        >>> analyzer.plot_overview_grid(
        ...     variables=[
        ...         ("heating_dh_allday", "HDH$_{20}$ (°C·h)", "HDH$_{base=20°C}$"),
        ...         ("cooling_dh_allday", "CDH$_{25}$ (°C·h)", "CDH$_{base=25°C}$"),
        ...         ("cooling_dh_night_0_8h", "NCDH$_{25}$ (°C·h)", "NCDH (00-08h)"),
        ...     ],
        ...     horizontal=True, transpose=True,
        ...     out_path="fig3_overview_grid_by_city.png",
        ... )  # doctest: +SKIP
        """
        import matplotlib.pyplot as plt

        if self.results is None:
            raise ValueError("No results yet. Call run() first.")

        if variables is None:
            variables = [
                (col, col, col) for col in self.results.columns
                if col not in ('group', 'year')
            ]

        groups = self.inputs['group_order']
        n_groups = len(groups)
        n_vars = len(variables)

        if transpose:
            nrows, ncols = n_groups, n_vars
            figsize = (3.5 * ncols, 2.6 * nrows)
        else:
            nrows, ncols = n_vars, n_groups
            figsize = (3.6 * ncols, 3.2 * nrows)

        fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)

        axes_by_var: List[List] = [[] for _ in range(n_vars)]
        axis_to_harmonize = 'x' if horizontal else 'y'

        for v_idx, (col, ylabel, title) in enumerate(variables):
            for g_idx, group in enumerate(groups):
                r, c = (g_idx, v_idx) if transpose else (v_idx, g_idx)
                ax = axes[r][c]

                self._draw_group_subplot(
                    ax, group, g_idx, col, ylabel,
                    show_ylabel=(c == 0), show_xlabel=(r == nrows - 1),
                    horizontal=horizontal, show_group_title=not transpose,
                )
                axes_by_var[v_idx].append(ax)

                if not transpose and r == 0:
                    zone = self._group_zone(group)
                    group_title = (
                        f"{self._group_label(group)} ({zone})"
                        if zone else self._group_label(group)
                    )
                    ax.set_title(group_title, fontsize=10, fontweight='bold')

            if transpose:
                # Column header (variable name) on top of the first row of
                # each column, above that cell's own trend-stats title.
                top_ax = axes[0][v_idx]
                top_ax.set_title(f"{title}\n{top_ax.get_title()}", fontsize=10.0)
            else:
                # Row label (variable name), rotated, left of the first column.
                axes[v_idx][0].annotate(
                    title, xy=(-0.35, 0.5), xycoords='axes fraction',
                    fontsize=11, fontweight='bold', ha='right', va='center', rotation=90,
                )

            if harmonize_ylim:
                self._harmonize_lim(axes_by_var[v_idx], axis=axis_to_harmonize)

        if transpose:
            # Row label (group name/zone), rotated, left of the first
            # column of each row.
            for g_idx, group in enumerate(groups):
                zone = self._group_zone(group)
                group_title = (
                    f"{self._group_label(group)} ({zone})"
                    if zone else self._group_label(group)
                )
                axes[g_idx][0].annotate(
                    group_title, xy=(-0.22, 0.5), xycoords='axes fraction',
                    fontsize=11, fontweight='bold', ha='right', va='center', rotation=90,
                )

        fig.tight_layout()
        if out_path:
            fig.savefig(out_path, dpi=300, bbox_inches='tight')
            print(f"[FIGURE] Saved -> {out_path}")
        if show:
            plt.show()
        else:
            plt.close(fig)
        return fig

    # -------------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------------

    def export_results(self, output_path: str = 'epw_group_trend_results.csv') -> str:
        """
        Export :attr:`results` (and, if computed, every cached entry of
        :attr:`trend_stats_`) to disk.

        Parameters
        ----------
        output_path : str
            Destination path. ``.xlsx`` writes an Excel workbook (one
            ``'results'`` sheet plus one sheet per cached trend variable);
            any other extension writes :attr:`results` alone as CSV.

        Returns
        -------
        str
            Absolute path to the saved file.

        Raises
        ------
        ValueError
            If :meth:`run` has not been called yet.

        Example
        -------
        >>> analyzer.export_results("climate_trend_variables.xlsx")  # doctest: +SKIP
        """
        if self.results is None:
            raise ValueError("No results to export. Call run() first.")

        if output_path.lower().endswith('.xlsx'):
            sheets = {'results': self.results}
            sheets.update({f'trend_{value_col}': trend_df for value_col, trend_df in self.trend_stats_.items()})
            export_frames_to_excel(sheets, output_path, index={'results': False})
        else:
            self.results.to_csv(output_path, index=False)

        abs_path = os.path.abspath(output_path)
        print(f"[INFO] Results exported to: {abs_path}")
        return abs_path

