# -*- coding: utf-8 -*-
"""
degree_hours/batch_analyzer.py
=================================

:class:`EpwBatchAnalyzer` — runs :class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator`
over *several* EPW files and *several* hour-of-day scenarios at once,
producing a single comparative DataFrame with ``(epw_name, variable)``
MultiIndex columns — ideal for "TMY vs. real years vs. reference file"
tables.

Extracted from the former monolithic ``degree_hours.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6); see ``pyweatherfiles/degree_hours/__init__.py``
for the package-level overview of all three classes.
"""

import os
from typing import Dict, List, Optional, Union

import pandas as pd

from ..session_manager import save_object_session
from .._export_utils import export_frames_to_excel
from .calculator import DegreeHoursCalculator

# Variables whose monthly aggregate is a SUM (energy); all others use MEAN
_RADIATION_VARS = frozenset({
    'global_horizontal_radiation',
    'direct_normal_radiation',
    'diffuse_horizontal_radiation',
    'global_horizontal_illuminance',
    'direct_normal_illuminance',
    'diffuse_horizontal_illuminance',
    'zenith_luminance',
    'horizontal_infrared_radiation_intensity',
    'liquid_precipitation_depth',
})


class EpwBatchAnalyzer:
    """
    Run :class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator` over
    multiple EPW files and compile a comparative monthly summary table.

    For each EPW the following columns are computed:

    - **Heating / cooling degree-hours (all 24 h)** — ``heating_dh_24h``,
      ``cooling_dh_24h``.
    - **Heating / cooling degree-hours (custom hour range)** — e.g.
      ``heating_dh_0-8h``, ``cooling_dh_0-8h``.
    - **EPW climate variables** (monthly sum for radiation/illuminance,
      monthly mean for the rest) — column name = EPW attribute name.

    Attributes
    ----------
    epw_paths : list of str
        Paths to the EPW files being analysed, as passed to the constructor.
    setpoint_source : str or dict
        The IDF path or custom setpoint configuration in use.
    epw_variables : list or dict or None
        The raw *epw_variables* argument as passed to the constructor
        (normalised internally by :meth:`_resolve_epw_variables` when
        :meth:`run` executes).
    hours : list, dict or None
        The raw *hours* argument as passed to the constructor (normalised
        internally by :meth:`_resolve_hours` when :meth:`run` executes).
    zone_name : str or None
        Zone/Space name forwarded to every :meth:`DegreeHoursCalculator.calculate`
        call.
    mode : str
        ``'heating'``, ``'cooling'`` or ``'both'``.
    year : int or None
        Year override forwarded to every :class:`DegreeHoursCalculator`.
    frequencies : list of str
        Aggregation frequencies to compute (subset of ``'hourly'``,
        ``'daily'``, ``'monthly'``, ``'yearly'``).
    start_date, end_date : str or None
        ``'DD/MM'``-formatted period filter forwarded to every calculation.
    results : dict[str, pd.DataFrame] or None
        MultiIndex-column DataFrames ``(epw_name, variable)``, one per
        requested frequency, with months (or hours/days/years) as index.
        Populated after calling :meth:`run`.
    calculators : dict[str, DegreeHoursCalculator]
        Maps EPW base name -> :class:`DegreeHoursCalculator` instance,
        giving access to hourly data and individual results after :meth:`run`.

    Example
    -------
    >>> from pyweatherfiles.degree_hours import EpwBatchAnalyzer
    >>> batch = EpwBatchAnalyzer(
    ...     epw_paths=["city_tmy.epw", "city_met.epw", "city_2005.epw"],
    ...     setpoint_source="building.idf",
    ...     frequencies=["monthly"],
    ... )  # doctest: +SKIP
    >>> results = batch.run()  # doctest: +SKIP
    >>> results["monthly"]["city_tmy"]  # doctest: +SKIP
    """

    def __init__(
        self,
        epw_paths: List[str],
        setpoint_source: Union[str, Dict],
        epw_variables: Optional[Union[List[str], Dict[str, Union[str, List[str]]]]] = None,
        hours: Optional[Union[List[int], List[List[int]], Dict[str, List[int]]]] = None,
        zone_name: Optional[str] = None,
        mode: str = 'both',
        year: Optional[int] = None,
        frequencies: Optional[Union[str, List[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        epw_paths : list of str
            Paths to the EPW files to analyse.
        setpoint_source : str or dict
            IDF file path or custom setpoint configuration dict passed
            directly to :meth:`DegreeHoursCalculator.calculate`.
        epw_variables : list of str  *or*  dict, optional
            Climate variables to include as monthly columns.

            **List form** (backward-compatible)::

                ['global_horizontal_radiation', 'wind_speed']

            One column per variable.  Aggregation is auto-detected:
            *sum* for radiation/energy variables, *mean* for the rest.

            **Dict form** — explicit aggregation(s) per variable::

                {
                    'global_horizontal_radiation': 'sum',
                    'dry_bulb_temperature': ['mean', 'max', 'min'],
                    'wind_speed': 'mean',
                }

            When multiple aggregations are requested the column names become
            ``<variable>_<aggfunc>`` (e.g. ``dry_bulb_temperature_mean``).
            Supported aggregation strings:
            ``'sum'``, ``'mean'``, ``'max'``, ``'min'``, ``'std'``.

            Defaults to ``{'global_horizontal_radiation': 'sum'}``.
            Available variable names: :attr:`DegreeHoursCalculator._EPW_ATTRS`.
        hours : list of int, list of lists of int, dict, optional
            Hours for the degree-hour calculation (any subset of 0-23).
            Can be a single list, a list of lists for multiple scenarios,
            or a dict mapping scenario labels to hour lists.
            Defaults to ``None`` (all 24 hours).
        zone_name : str, optional
            Zone/Space name forwarded to :meth:`DegreeHoursCalculator.calculate`.
        mode : str
            ``'heating'``, ``'cooling'``, or ``'both'`` (default).
        year : int, optional
            Year to assign to EPW data (overrides EPW header).
        frequencies : str or list of str, optional
            Frequencies to compute: ``'hourly'``, ``'daily'``, ``'monthly'``, ``'yearly'``.
            Defaults to ``['monthly']``.
        start_date : str, optional
            Start date in ``'DD/MM'`` format to restrict calculations.
        end_date : str, optional
            End date in ``'DD/MM'`` format to restrict calculations.

        Raises
        ------
        ValueError
            If *epw_paths* is empty.

        Example
        -------
        >>> batch = EpwBatchAnalyzer(
        ...     epw_paths=["city_tmy.epw", "city_met.epw", "city_2005.epw"],
        ...     setpoint_source="building.idf",
        ...     epw_variables={"global_horizontal_radiation": ["sum", "mean"]},
        ...     hours={"morning": list(range(9)), "all_day": list(range(24))},
        ...     mode="both",
        ...     frequencies=["hourly", "daily", "monthly"],
        ...     start_date="01/06", end_date="30/09",
        ... )  # doctest: +SKIP
        """
        if not epw_paths:
            raise ValueError("epw_paths must contain at least one file path.")

        self.epw_paths        = list(epw_paths)
        self.setpoint_source  = setpoint_source
        self.epw_variables    = epw_variables   # stored as-is; resolved in run()
        self.hours            = hours
        self.zone_name        = zone_name
        self.mode             = mode
        self.year             = year
        self.start_date       = start_date
        self.end_date         = end_date

        if frequencies is None:
            frequencies = ['monthly']
        self.frequencies = [frequencies] if isinstance(frequencies, str) else list(frequencies)

        self.results: Optional[Dict[str, pd.DataFrame]] = None
        self.calculators: Dict[str, 'DegreeHoursCalculator'] = {}

    # -------------------------------------------------------------------------

    def _resolve_hours(self) -> Dict[str, Optional[List[int]]]:
        """
        Normalise ``self.hours`` to the canonical internal format::
            {label: list_of_hours_or_None}
        """
        raw = self.hours

        if raw is None:
            return {'24h': None}

        if isinstance(raw, dict):
            return raw

        if isinstance(raw, list):
            if all(isinstance(x, int) for x in raw):
                label = f"{raw[0]}-{raw[-1]+1}h" if raw else "empty"
                return {label: raw}  # type: ignore

            if all(isinstance(x, list) for x in raw):
                res = {}
                for h_list in raw:
                    if not h_list:
                        res["empty"] = []
                        continue
                    if len(h_list) > 1 and h_list == list(range(min(h_list), max(h_list)+1)):
                        label = f"{h_list[0]}-{h_list[-1]+1}h"
                    else:
                        label = "_".join(map(str, h_list)) + "h"
                    res[label] = h_list
                return res

        raise TypeError("hours must be a list of ints, a list of lists, or a dict.")

    def _resolve_epw_variables(
        self,
    ) -> Dict[str, List[str]]:
        """
        Normalise ``self.epw_variables`` to the canonical internal format::

            {variable_name: [aggfunc, ...]}

        ``'auto'`` is a sentinel meaning "pick sum or mean based on variable
        type" (used when the caller supplied a plain list).

        Returns
        -------
        dict
            ``{var: ['aggfunc1', 'aggfunc2', ...]}``
        """
        raw = self.epw_variables

        # Default when nothing is specified
        if raw is None:
            return {'global_horizontal_radiation': ['sum']}

        # Plain list  → auto-detect aggregation, single column per variable
        if isinstance(raw, list):
            return {var: ['auto'] for var in raw}

        # Dict form  → normalise values to lists
        if isinstance(raw, dict):
            resolved: Dict[str, List[str]] = {}
            for var, agg in raw.items():
                if isinstance(agg, str):
                    resolved[var] = [agg]
                else:
                    resolved[var] = list(agg)
            return resolved

        raise TypeError(
            "epw_variables must be a list of strings or a dict "
            "{variable: aggfunc | [aggfunc, ...]}."
        )

    # -------------------------------------------------------------------------

    def run(self, save_session: bool = True, session_dir: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Execute the analysis for every EPW file: for each EPW path, load it
        with :class:`DegreeHoursCalculator` (stored in :attr:`calculators`),
        run :meth:`DegreeHoursCalculator.calculate` once per hour-of-day
        scenario in :attr:`hours` (see :meth:`_resolve_hours`), extract the
        requested :attr:`epw_variables` (see :meth:`_resolve_epw_variables`)
        aggregated at each requested frequency, and finally concatenate
        everything into one MultiIndex-column DataFrame per frequency.

        Parameters
        ----------
        save_session : bool, optional
            If ``True`` (default), persist a reproducible ``.pkl``/``.json``
            session for the analyzer as a whole via
            :func:`~pyweatherfiles.session_manager.save_object_session`.
            Note: this does **not** prevent each internal
            :meth:`DegreeHoursCalculator.calculate` call from also saving
            its own session next to its respective EPW file (that internal
            call always uses its own default of ``save_session=True`` and
            currently cannot be silenced from here).
        session_dir : str, optional
            Directory for the batch session files. Defaults to the
            directory of the first entry in :attr:`epw_paths`.

        Returns
        -------
        dict
            A dictionary mapping each frequency to its corresponding summary
            DataFrame with a two-level column MultiIndex: ``(epw_name, variable)``.
            Also stored in :attr:`results`.

        Raises
        ------
        RuntimeError
            If none of the EPW files in :attr:`epw_paths` could be found or
            processed.

        Example
        -------
        >>> batch = EpwBatchAnalyzer(["city_tmy.epw", "city_2019.epw"], "building.idf", frequencies=["monthly"])  # doctest: +SKIP
        >>> results = batch.run(save_session=False)  # doctest: +SKIP
        >>> results["monthly"].columns.get_level_values("epw").unique()  # doctest: +SKIP
        """
        # Store dataframes grouped by frequency and then by EPW
        # Structure: {freq: {epw_name: dataframe}}
        all_frames_by_freq: Dict[str, Dict[str, pd.DataFrame]] = {
            f: {} for f in self.frequencies
        }
        hours_dict = self._resolve_hours()

        for epw_path in self.epw_paths:
            if not os.path.exists(epw_path):
                print(f"[WARNING] EPW not found, skipping: {epw_path}")
                continue

            epw_name = os.path.splitext(os.path.basename(epw_path))[0]
            print(f"\n{'='*60}\n[BATCH] {epw_name}\n{'='*60}")

            calc = DegreeHoursCalculator(epw_path, year=self.year)
            self.calculators[epw_name] = calc
            var_spec = self._resolve_epw_variables()

            freq_cols: Dict[str, Dict[str, pd.Series]] = {f: {} for f in self.frequencies}

            for h_label, h_list in hours_dict.items():
                # --- Degree-hours calculation -----------------------------------
                res_dict = calc.calculate(
                    self.setpoint_source,
                    frequency=self.frequencies,
                    hours=h_list,
                    mode=self.mode,
                    zone_name=self.zone_name,
                    start_date=self.start_date,
                    end_date=self.end_date,
                )

                # Optional mask for EPW variables
                idx = calc.temperatures.index
                mask = pd.Series(True, index=idx)
                if self.start_date or self.end_date:
                    sd_str = self.start_date or "01/01"
                    ed_str = self.end_date or "31/12"
                    try:
                        sd = pd.to_datetime(f"{calc.year}/{sd_str}", format="%Y/%d/%m")
                        ed = pd.to_datetime(f"{calc.year}/{ed_str}", format="%Y/%d/%m") + pd.Timedelta(days=1, microseconds=-1)
                    except Exception as e:
                        raise ValueError(f"Invalid date format. Use 'DD/MM': {e}")

                    if sd <= ed:
                        mask = mask & ((idx >= sd) & (idx <= ed))
                    else:
                        mask = mask & ((idx >= sd) | (idx <= ed))

                if h_list is not None:
                    mask = mask & idx.hour.isin(h_list)

                for freq in self.frequencies:
                    # Degree hours for this scenario
                    res = res_dict[freq]
                    for col in res.columns:
                        col_name = f"{col}_{h_label}"
                        freq_cols[freq][col_name] = res[col]

                    # Process climate variables
                    freq_code = {'hourly': 'h', 'daily': 'D', 'monthly': 'ME', 'yearly': 'YE'}[freq]

                    for var, aggfuncs in var_spec.items():
                        if var not in calc.epw_data.columns:
                            if freq == self.frequencies[0] and h_label == list(hours_dict.keys())[0]:
                                print(f"[WARNING] Variable '{var}' not in EPW data for {epw_name}.")
                            continue

                        series = calc.epw_data[var].copy()
                        series = series.loc[mask]

                        use_suffix = len(aggfuncs) > 1 or isinstance(self.epw_variables, dict)

                        for agg in aggfuncs:
                            if agg == 'auto':
                                if freq_code == 'h':
                                    aggregated = series
                                else:
                                    aggregated = (
                                        series.resample(freq_code).sum()
                                        if var in _RADIATION_VARS
                                        else series.resample(freq_code).mean()
                                    )
                                col_name = var
                            else:
                                if freq_code == 'h':
                                    aggregated = series
                                else:
                                    aggregated = series.resample(freq_code).agg(agg)
                                col_name = f'{var}_{agg}' if use_suffix else var

                            # Append hour scenario label
                            col_name = f"{col_name}_{h_label}"
                            freq_cols[freq][col_name] = aggregated

            for freq in self.frequencies:
                epw_df = pd.DataFrame(freq_cols[freq])

                # Align indices based on frequency
                if freq == 'monthly':
                    epw_df.index = epw_df.index.month
                    epw_df.index.name = 'month'
                elif freq == 'yearly':
                    epw_df.index = epw_df.index.year
                    epw_df.index.name = 'year'
                else:
                    epw_df.index.name = 'datetime'

                all_frames_by_freq[freq][epw_name] = epw_df

        if not any(all_frames_by_freq.values()):
            raise RuntimeError("No EPW files could be processed.")

        # Concatenate into MultiIndex-column DataFrames
        self.results = {}
        for freq, frames in all_frames_by_freq.items():
            if frames:
                df_concat = pd.concat(frames, axis=1)
                df_concat.columns.names = ['epw', 'variable']
                self.results[freq] = df_concat

        print("\n[BATCH] Analysis completed.")

        # --- Session persistence ---
        if save_session and self.results:
            _first_epw = self.epw_paths[0] if self.epw_paths else "unknown"
            _sp_key = self.setpoint_source if isinstance(self.setpoint_source, str) else "dict_config"
            _inputs = {
                "first_epw": _first_epw,
                "setpoint_source": _sp_key,
                "n_epws": str(len(self.epw_paths)),
            }
            _dir = session_dir or os.path.dirname(os.path.abspath(_first_epw)) or os.getcwd()
            try:
                save_object_session(self, "EpwBatchAnalyzer", _inputs, session_dir=_dir)
            except Exception as _e:
                print(f"[SESSION] Could not save the session: {_e}")

        return self.results

    # -------------------------------------------------------------------------

    def export(self, output_path: str = 'batch_degree_hours.xlsx') -> str:
        """
        Export :attr:`results` to an Excel file.

        For each frequency requested, a combined sheet ``'all_epws_<freq>'`` is
        created. If only one frequency is present, it may create individual
        sheets per EPW (legacy behavior) or group them cleanly.

        Parameters
        ----------
        output_path : str
            Destination file path.

        Returns
        -------
        str
            Absolute path to the saved file.

        Raises
        ------
        ValueError
            If :meth:`run` has not been called yet (no results to export).

        Example
        -------
        >>> batch = EpwBatchAnalyzer(["city_tmy.epw", "city_2019.epw"], "building.idf", frequencies=["monthly"])  # doctest: +SKIP
        >>> batch.run()  # doctest: +SKIP
        >>> batch.export("batch_degree_hours.xlsx")  # doctest: +SKIP
        '/abs/path/batch_degree_hours.xlsx'
        """
        if not self.results:
            raise ValueError("No results to export. Call run() first.")

        sheets: Dict[str, pd.DataFrame] = {}
        for freq, df in self.results.items():
            # Combined sheet for the frequency
            sheets[f'all_epws_{freq}'] = df

            # If there's only one frequency, also create individual EPW sheets
            # (backward compatible layout)
            if len(self.results) == 1:
                for epw_name in df.columns.get_level_values('epw').unique():
                    sheets[epw_name] = df[epw_name]

        export_frames_to_excel(sheets, output_path)

        abs_path = os.path.abspath(output_path)
        print(f"[INFO] Results exported to: {abs_path}")
        return abs_path

