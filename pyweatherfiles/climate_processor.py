# -*- coding: utf-8 -*-
"""
climate_processor.py
======================

Cleaning, reindexing and gap-filling of raw hourly weather-station series.

This module is a **pre-processing** step meant to run *upstream* of
:class:`~pyweatherfiles.tmy.TMYGenerator` and
:class:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`: it takes a
raw hourly CSV/Excel export from a weather station (which typically has
missing hours, occasional bad readings, and an irregular time index) and
produces a continuous, gap-filled hourly series plus a full quality-control
report, so that the statistical TMY engine and the EPW converter can assume
"clean" input data.

The single public class, :class:`ClimateProcessor`, runs its **entire**
pipeline automatically as soon as it is instantiated (load -> map columns ->
reindex -> fill gaps -> compute statistics); there is no separate "run" step.

Requires the optional dependency ``pvlib`` (used for the physically-based
clear-sky solar radiation gap-filling strategy); install it with
``pip install pvlib``. This module is **not** re-exported from
``pyweatherfiles/__init__.py`` — import it explicitly:
``from pyweatherfiles.climate_processor import ClimateProcessor``.

Example
-------
::

    from pyweatherfiles.climate_processor import ClimateProcessor

    proc = ClimateProcessor(
        file_path="raw_station_data.xlsx",
        lat=37.38, lon=-5.98, alt=15,
    )
    print(proc.summary)  # Before_%/After_%/Gain_% completeness per variable

    # Full 5-sheet Excel report: filled data, summary, gaps, annual/monthly stats
    proc.export_complete_report("quality_report.xlsx")
"""
import pandas as pd
import numpy as np
import time
import os

try:
    import pvlib
except ImportError:
    raise ImportError(
        "The 'pvlib' library is not installed. It is required by ClimateProcessor "
        "for the clear-sky-index solar radiation gap-filling strategy. "
        "Install it with: pip install pvlib  (or: pip install pyweatherfiles[climate])"
    )


class ClimateProcessor:
    """
    Clean, reindex and gap-fill a raw hourly weather-station series, ready
    to be handed off to :class:`~pyweatherfiles.tmy.TMYGenerator` or
    :class:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`.

    The **entire pipeline runs automatically inside** ``__init__`` (see
    :meth:`_process_all`): load the file, auto-detect/rename the 10 canonical
    variable columns, reindex to a continuous hourly ``DatetimeIndex``,
    fill gaps with a variable-specific strategy (see :meth:`_fill_data`), and
    finally compute before/after completeness and 3 quality-control tables.
    There is no separate "run"/"process" method to call afterwards — simply
    read the resulting attributes or call one of the ``export_*`` methods.

    Attributes:
        file_path (str): Path to the raw input CSV/Excel file, as passed to
            the constructor.
        lat (float): Site latitude in degrees, used by ``pvlib`` for the
            clear-sky solar-radiation reference.
        lon (float): Site longitude in degrees.
        alt (float): Site elevation in metres.
        df (pandas.DataFrame): The **final, gap-filled** hourly DataFrame,
            indexed by a continuous hourly ``DatetimeIndex`` named ``'time'``,
            with columns renamed to the canonical short names (see
            :meth:`_map_variables`: ``'Dry-bulb'``, ``'Dew Point'``, ``'RH'``,
            ``'WindDir'``, ``'WindSpeed'``, ``'Pressure'``, ``'GHI'``,
            ``'BHI'``, ``'DHI'``, ``'BNI'`` — only the ones actually found in
            the source file).
        df_before (pandas.DataFrame): A copy of the data **before** gap
            filling (but after column renaming and reindexing), kept to
            compute before/after statistics and the gap tables.
        working_cols (list[str]): The canonical variable names that were
            successfully detected in the source file (subset of the 10 above).
        before_availability (dict[str, float]): Percentage (0-100) of
            non-missing values per column, before filling.
        after_availability (dict[str, float]): Percentage (0-100) of
            non-missing values per column, after filling.
        summary (pandas.DataFrame): One row per variable with
            ``Before_%``/``After_%``/``Gain_%`` completeness columns.
        gaps_df (pandas.DataFrame): One row per gap that was successfully
            interpolated (``Variable``, ``Gap start``, ``Gap end``,
            ``Hours interpolated``).
        annual_stats (pandas.DataFrame): Per year x variable quality-control
            table (total gaps, fully/partially/not filled, hours missing vs.
            filled, average filled hours/day); see :meth:`_calculate_annual_stats`.
        max_gaps_df (pandas.DataFrame): Per year and per month, the single
            largest gap (in hours) for each variable, flagged
            ``FILLED``/``NOT FILLED (>Xh)``; see :meth:`_gaps_stats_periods`.

    Example:
        >>> from pyweatherfiles.climate_processor import ClimateProcessor
        >>> proc = ClimateProcessor("raw_station_data.xlsx", lat=37.38, lon=-5.98, alt=15)  # doctest: +SKIP
        >>> proc.summary  # doctest: +SKIP
          Variable  Before_%  After_%  Gain_%
        0 Dry-bulb      98.2     99.9     1.7
        ...
        >>> proc.export_complete_report("quality_report.xlsx")  # doctest: +SKIP
        'quality_report.xlsx'
    """
    def __init__(self, file_path, lat, lon, alt):
        """Initialise the processor and immediately run the full pipeline
        (load, map, reindex, fill, compute statistics — see
        :meth:`_process_all`).

        Args:
            file_path (str): Path to the raw hourly CSV or Excel file. Excel
                files are assumed to have a units row directly below the
                header (skipped via ``skiprows=[1]``); the first column is
                parsed as a day-first datetime.
            lat (float): Site latitude in degrees (used by ``pvlib`` for the
                clear-sky solar reference in :meth:`_fill_data`).
            lon (float): Site longitude in degrees.
            alt (float): Site elevation in metres above sea level.
        """
        self.file_path = file_path
        self.lat = lat
        self.lon = lon
        self.alt = alt

        # Internal state variables
        self.df = None
        self.df_before = None
        self.working_cols = []
        self.before_availability = {}
        self.after_availability = {}
        self.summary = None
        self.gaps_df = None
        self.annual_stats = None
        self.max_gaps_df = None

        # Execute the full data flow upon instantiation
        self._log("Initializing Climate Processor...")
        self._process_all()

    def _log(self, msg):
        """Print *msg* to the console prefixed with the current wall-clock
        time (``HH:MM:SS``), used for lightweight progress reporting across
        the pipeline.

        Args:
            msg (str): Message to print.
        """
        print(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {msg}")

    def _process_all(self):
        """Run the complete processing pipeline in the correct order:
        :meth:`_load_data` -> :meth:`_map_variables` ->
        :meth:`_calculate_availability_before` -> :meth:`_reindex` ->
        :meth:`_fill_data` -> :meth:`_calculate_availability_after` ->
        :meth:`_generate_statistics_tables`.

        Called automatically once from ``__init__``; not meant to be called
        again directly (re-instantiate :class:`ClimateProcessor` instead if
        you need to re-run the pipeline, e.g. with different lat/lon/alt).
        """
        self._load_data()
        self._map_variables()
        self._calculate_availability_before()
        self._reindex()
        self._fill_data()
        self._calculate_availability_after()
        self._generate_statistics_tables()
        self._log("Internal processing COMPLETED ✓")

    # -------------------------------------------------------
    # 1. LOADING AND MAPPING
    # -------------------------------------------------------
    def _load_data(self):
        """Load ``self.file_path`` (CSV or Excel, auto-detected by
        extension) into ``self.df``, parse the first column as a day-first
        datetime, drop rows with an unparseable timestamp, rename that
        column to ``'time'`` and set it as a sorted index.

        For Excel files, row index 1 (right below the header) is skipped via
        ``skiprows=[1]``, since station exports typically place a units row
        there. A pristine copy is kept in ``self.df_before`` for later
        before/after comparisons.

        Returns:
            None: Populates ``self.df`` and ``self.df_before`` in place.
        """
        self._log("Loading data file...")
        if self.file_path.lower().endswith('.csv'):
            self.df = pd.read_csv(self.file_path)
        else:
            self.df = pd.read_excel(self.file_path, header=0, skiprows=[1])

        self.df.columns = [str(c).strip() for c in self.df.columns]
        col_time = self.df.columns[0]
        self.df[col_time] = pd.to_datetime(self.df[col_time], dayfirst=True, errors='coerce')
        self.df = self.df.dropna(subset=[col_time])
        self.df = self.df.rename(columns={col_time: 'time'})
        self.df = self.df.set_index('time').sort_index()
        self.df_before = self.df.copy()

    def _map_variables(self):
        """Auto-detect and rename the 10 canonical climate-variable columns
        by case-insensitive keyword matching against the source column
        names, populating :attr:`working_cols` with the canonical names that
        were actually found.

        Keyword rules (first matching column wins): ``'Dry-bulb'`` <- 'dry',
        ``'Dew Point'`` <- 'dew', ``'RH'`` <- 'humidity', ``'WindDir'`` <-
        'direction', ``'WindSpeed'`` <- 'speed', ``'Pressure'`` <-
        'pressure', ``'GHI'`` <- 'global', ``'BHI'`` <- both 'beam' and
        'horiz', ``'DHI'`` <- 'diffuse', ``'BNI'`` <- 'normal'.

        Both ``self.df`` and ``self.df_before`` are renamed identically so
        later comparisons stay column-aligned.

        Returns:
            None: Updates ``self.df``, ``self.df_before`` and
            ``self.working_cols`` in place.
        """
        def find_col(df, keywords):
            for col in df.columns:
                col_l = str(col).lower()
                if all(k.lower() in col_l for k in keywords):
                    return col
            return None

        cols_map = {
            'Dry-bulb': find_col(self.df, ['dry']),
            'Dew Point': find_col(self.df, ['dew']),
            'RH': find_col(self.df, ['humidity']),
            'WindDir': find_col(self.df, ['direction']),
            'WindSpeed': find_col(self.df, ['speed']),
            'Pressure': find_col(self.df, ['pressure']),
            'GHI': find_col(self.df, ['global']),
            'BHI': find_col(self.df, ['beam', 'horiz']),
            'DHI': find_col(self.df, ['diffuse']),
            'BNI': find_col(self.df, ['normal']),
        }

        rename_dict = {v: k for k, v in cols_map.items() if v is not None}
        self.df = self.df.rename(columns=rename_dict)
        self.df_before = self.df_before.rename(columns=rename_dict)
        self.working_cols = [k for k, v in cols_map.items() if v is not None]

    def _calculate_availability_before(self):
        """Compute, for each column in :attr:`working_cols`, the percentage
        (0-100) of non-missing values in ``self.df`` **before** gap filling,
        storing the result in :attr:`before_availability`.

        Returns:
            None: Populates ``self.before_availability`` in place.
        """
        for col in self.working_cols:
            self.before_availability[col] = self.df[col].notna().mean() * 100

    def _reindex(self):
        """Reindex both ``self.df`` and ``self.df_before`` onto a continuous
        hourly ``DatetimeIndex`` spanning from the minimum to the maximum
        original timestamp, turning any missing hour into an explicit
        ``NaN`` row (a prerequisite for the gap-detection logic used
        throughout the rest of the pipeline).

        Returns:
            None: Updates ``self.df`` and ``self.df_before`` in place; both
            keep the index name ``'time'``.
        """
        self._log("Reindexing to full hours...")
        full_index = pd.date_range(self.df.index.min(), self.df.index.max(), freq='h')
        self.df = self.df.reindex(full_index)
        self.df_before = self.df_before.reindex(full_index)
        self.df.index.name = 'time'
        self.df_before.index.name = 'time'

    # -------------------------------------------------------
    # 2. FILLING LOGIC (Identical to original)
    # -------------------------------------------------------
    def _fill_data(self):
        """
        Fill gaps in ``self.df`` in place, using a **variable-specific**
        strategy and maximum-gap limit (beyond the limit, the gap is
        deliberately left unfilled so unreliable, over-long interpolations
        are never silently produced):

        - **Pressure**: linear interpolation, limit 72 h.
        - **Dry-bulb / Dew Point temperature**: cubic spline (order 3, via
          :meth:`_spline_limit`), limit 24 h.
        - **Relative humidity (RH)**: reconstructed from temperature and dew
          point via the Magnus formula (``100 * exp(17.625*Td/(243.04+Td)) /
          exp(17.625*T/(243.04+T))``, clipped to [0, 100]) wherever both
          temperatures are available, then any remaining gap is linearly
          interpolated, limit 24 h.
        - **Wind speed**: linear interpolation, limit 3 h.
        - **Wind direction**: linear interpolation, limit 2 h.
        - **Solar radiation (GHI/DHI/BNI)**: short gaps (<=3h) are linearly
          interpolated; medium gaps (3-24h, daytime only, defined as
          clear-sky GHI > 5 W/m2) are filled using the **clear-sky index**
          method: a clearness index ``kt = clip(observed / clear_sky, 0,
          1.2)`` is computed, smoothed with a 24h centred rolling median,
          and re-applied as ``value = clear_sky_reference * smoothed_kt`` —
          this preserves realistic cloudiness patterns instead of a naive
          straight-line interpolation. Night-time gaps are filled with 0.
          The clear-sky reference (GHI/DHI/DNI) for the exact site and
          timestamps is obtained from ``pvlib.location.Location.get_clearsky()``
          (Ineichen-Perez model). Finally, if both GHI and DHI ended up
          available, **BHI is recomputed** as ``max(GHI - DHI, 0)`` to keep
          the three radiation components internally consistent.

        Returns:
            None: Updates ``self.df`` in place. Prints the elapsed wall-clock
            time when done.
        """
        t0 = time.time()

        # 1. Pressure
        if 'Pressure' in self.df.columns:
            self.df['Pressure'] = self.df['Pressure'].interpolate(method='linear', limit=72)

        # 2. Temperatures
        for col in ['Dry-bulb', 'Dew Point']:
            if col in self.df.columns:
                self.df[col] = self._spline_limit(self.df[col], max_gap=24)

        # 3. Humidity
        if 'RH' in self.df.columns and 'Dry-bulb' in self.df.columns and 'Dew Point' in self.df.columns:
            mask = self.df['RH'].isna() & self.df['Dry-bulb'].notna() & self.df['Dew Point'].notna()
            T = self.df.loc[mask, 'Dry-bulb']
            Td = self.df.loc[mask, 'Dew Point']
            self.df.loc[mask, 'RH'] = (100 * np.exp(17.625 * Td / (243.04 + Td)) / np.exp(17.625 * T / (243.04 + T))).clip(0, 100)
            self.df['RH'] = self.df['RH'].interpolate(method='linear', limit=24)

        # 4. Wind
        if 'WindSpeed' in self.df.columns:
            self.df['WindSpeed'] = self.df['WindSpeed'].interpolate(method='linear', limit=3)
        if 'WindDir' in self.df.columns:
            self.df['WindDir'] = self.df['WindDir'].interpolate(method='linear', limit=2)

        # 5. Solar (pvlib)
        location = pvlib.location.Location(self.lat, self.lon, tz='UTC', altitude=self.alt)
        times_utc = self.df.index.tz_localize('UTC') if self.df.index.tz is None else self.df.index
        cs = location.get_clearsky(times_utc)
        GHIc = pd.Series(cs['ghi'].values, index=self.df.index)
        DHIc = pd.Series(cs['dhi'].values, index=self.df.index)
        BNIc = pd.Series(cs['dni'].values, index=self.df.index)
        is_day = GHIc > 5

        for col, ref in [('GHI', GHIc), ('DHI', DHIc), ('BNI', BNIc)]:
            if col not in self.df.columns: continue
            self.df[col] = self.df[col].interpolate(method='linear', limit=3)
            medium_mask = self._gap_size(self.df[col]).between(3, 24) & is_day
            if medium_mask.any():
                kt = (self.df[col] / ref.replace(0, np.nan)).clip(0, 1.2)
                kt_med = kt.rolling(24, min_periods=6, center=True).median()
                self.df.loc[medium_mask, col] = (ref[medium_mask] * kt_med[medium_mask]).clip(0)
            self.df.loc[~is_day, col] = self.df.loc[~is_day, col].fillna(0)

        if {'GHI', 'DHI'}.issubset(self.df.columns):
            self.df['BHI'] = (self.df['GHI'] - self.df['DHI']).clip(lower=0)

        self._log(f"Filling completed in {time.time() - t0:5.1f}s")

    def _calculate_availability_after(self):
        """Compute, for each column in :attr:`working_cols`, the percentage
        (0-100) of non-missing values in ``self.df`` **after** gap filling,
        storing the result in :attr:`after_availability`, and build
        :attr:`summary` (one row per variable with ``Before_%``, ``After_%``
        and ``Gain_%`` columns).

        Returns:
            None: Populates ``self.after_availability`` and ``self.summary``
            in place.
        """
        for col in self.working_cols:
            self.after_availability[col] = self.df[col].notna().mean() * 100

        self.summary = pd.DataFrame({
            'Variable': self.working_cols,
            'Before_%': [self.before_availability[c] for c in self.working_cols],
            'After_%': [self.after_availability[c] for c in self.working_cols],
            'Gain_%': [self.after_availability[c] - self.before_availability[c] for c in self.working_cols]
        })

    def _generate_statistics_tables(self):
        """Build the 3 quality-control tables exposed as public attributes:
        :attr:`gaps_df` (every successfully interpolated gap, via
        :meth:`_gaps_interpolated`), :attr:`annual_stats` (per year x
        variable gap statistics, via :meth:`_calculate_annual_stats`) and
        :attr:`max_gaps_df` (largest gap per year/month and variable, via
        :meth:`_gaps_stats_periods`).

        Returns:
            None: Populates ``self.gaps_df``, ``self.annual_stats`` and
            ``self.max_gaps_df`` in place.
        """
        self._log("Calculating statistical tables...")
        # 1. Gaps_df
        records = []
        for col in self.working_cols:
            if col in self.df.columns and col in self.df_before.columns:
                records.extend(self._gaps_interpolated(self.df_before, self.df, col))
        self.gaps_df = pd.DataFrame(records)

        # 2. Annual Stats
        self.annual_stats = self._calculate_annual_stats(self.df_before, self.df, self.working_cols)

        # 3. Max Gaps
        self.max_gaps_df = self._gaps_stats_periods(self.df_before, self.working_cols)

    # -------------------------------------------------------
    # 3. AUXILIARY FUNCTIONS (Exactly original logic)
    # -------------------------------------------------------
    def _gap_size(self, series):
        """For every position in *series*, return the total length (in
        rows/hours) of the contiguous ``NaN`` run it belongs to (0 for
        non-missing positions), used to decide which gap-filling strategy
        applies (short vs. medium vs. unfillable) at each timestamp.

        Args:
            series (pandas.Series): Series to analyse (same index as
                ``self.df``).

        Returns:
            pandas.Series: Same index as *series*; each ``NaN`` position
            holds the size of its gap, non-``NaN`` positions hold 0.
        """
        is_nan = series.isna()
        gap_id = (~is_nan).cumsum()
        return is_nan.groupby(gap_id).transform('sum').where(is_nan, 0)

    def _spline_limit(self, series, max_gap):
        """Fill gaps in *series* with a cubic spline (order 3), but only for
        gaps whose size is between 1 and *max_gap* hours (inclusive); longer
        gaps are left untouched (still ``NaN``) rather than risking a wild
        spline extrapolation over a long missing stretch.

        Args:
            series (pandas.Series): Series to fill (e.g. dry-bulb
                temperature).
            max_gap (int): Maximum gap length, in hours, eligible for
                spline interpolation.

        Returns:
            pandas.Series: A copy of *series* with eligible gaps filled.
        """
        s = series.copy()
        gaps = self._gap_size(s)
        mask_gap = (gaps > 0) & (gaps <= max_gap)
        if not mask_gap.any():
            return s
        s_spline = s.interpolate(method='spline', order=3, limit=max_gap, limit_direction='both')
        s.loc[mask_gap] = s_spline.loc[mask_gap]
        return s

    def _gaps_interpolated(self, original, filled, var_name):
        """List every contiguous run of hours where *var_name* was missing
        in *original* but is now present in *filled* (i.e. every gap that
        **was** successfully interpolated), as a list of row dicts ready to
        be turned into :attr:`gaps_df`.

        Args:
            original (pandas.DataFrame): Data before gap filling (typically
                ``self.df_before``).
            filled (pandas.DataFrame): Data after gap filling (typically
                ``self.df``).
            var_name (str): Column/canonical variable name to analyse.

        Returns:
            list[dict]: One dict per filled gap, with keys ``'Variable'``,
            ``'Gap start'``, ``'Gap end'`` and ``'Hours interpolated'``.
            Empty list if *var_name* had no gaps that got filled.
        """
        s0 = original[var_name]
        s1 = filled[var_name]
        mask = s0.isna() & s1.notna()
        out = []
        if not mask.any(): return out
        is_gap = mask.to_numpy()
        idx = filled.index.to_numpy()
        n = len(filled)
        i = 0
        while i < n:
            if is_gap[i]:
                j = i
                while j < n and is_gap[j]: j += 1
                out.append({'Variable': var_name, 'Gap start': idx[i], 'Gap end': idx[j - 1], 'Hours interpolated': j - i})
                i = j
            else:
                i += 1
        return out

    def _calculate_annual_stats(self, df_before, df, working_cols):
        """Build the per-year x per-variable gap-quality table exposed as
        :attr:`annual_stats`.

        For every variable, every contiguous ``NaN`` run in *df_before* is
        classified as ``'Complete'`` (fully filled in *df*), ``'Not filled'``
        (still entirely missing in *df*) or ``'Partial'`` (some hours filled,
        some not), then aggregated by the calendar year of the gap's start.

        Args:
            df_before (pandas.DataFrame): Data before gap filling.
            df (pandas.DataFrame): Data after gap filling.
            working_cols (list[str]): Canonical variable names to analyse
                (typically ``self.working_cols``).

        Returns:
            pandas.DataFrame: Indexed by ``(year, Variable)``, with columns
            ``Total_Gaps``, ``Filled_100%``, ``Partial_Fills``,
            ``Not_Filled``, ``Orig_Missing_Hours``, ``Filled_Hours``,
            ``Still_Empty_Hours``, ``Days_in_year`` and
            ``Avg_filled_h/day``. Empty DataFrame if no variable had any
            gap at all.
        """
        stats_list = []
        for col in working_cols:
            if col not in df_before.columns: continue

            s_before = df_before[col]
            s_after = df[col]

            is_nan_before = s_before.isna()
            if not is_nan_before.any(): continue

            gap_id = (~is_nan_before).cumsum()
            df_nans = pd.DataFrame({
                'time': s_before[is_nan_before].index,
                'gap_id': gap_id[is_nan_before].values,
                'is_nan_after': s_after[is_nan_before].isna().values
            })

            gap_agg = df_nans.groupby('gap_id').agg(
                start_time=('time', 'first'),
                size_before=('time', 'count'),
                nans_after=('is_nan_after', 'sum')
            )

            gap_agg['year'] = gap_agg['start_time'].dt.year

            def classify_gap(row):
                if row['nans_after'] == 0:
                    return 'Complete'
                elif row['nans_after'] == row['size_before']:
                    return 'Not filled'
                else:
                    return 'Partial'

            gap_agg['status'] = gap_agg.apply(classify_gap, axis=1)

            for year, group in gap_agg.groupby('year'):
                total_gaps = len(group)
                filled = len(group[group['status'] == 'Complete'])
                not_filled = len(group[group['status'] == 'Not filled'])
                partials = len(group[group['status'] == 'Partial'])

                original_hours = group['size_before'].sum()
                remaining_hours = group['nans_after'].sum()
                filled_hours = original_hours - remaining_hours

                stats_list.append({
                    'year': year,
                    'Variable': col,
                    'Total_Gaps': total_gaps,
                    'Filled_100%': filled,
                    'Partial_Fills': partials,
                    'Not_Filled': not_filled,
                    'Orig_Missing_Hours': original_hours,
                    'Filled_Hours': filled_hours,
                    'Still_Empty_Hours': remaining_hours
                })

        df_stats = pd.DataFrame(stats_list)
        if df_stats.empty: return df_stats

        df_stats = df_stats.set_index(['year', 'Variable'])
        df_stats['Days_in_year'] = [366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365 for y in df_stats.index.get_level_values(0)]
        df_stats['Avg_filled_h/day'] = (df_stats['Filled_Hours'] / df_stats['Days_in_year']).round(2)

        return df_stats

    def _gaps_stats_periods(self, df_before, working_cols):
        """Build the per-year and per-month "largest gap" table exposed as
        :attr:`max_gaps_df`.

        For every variable, every contiguous ``NaN`` run in *df_before* is
        located; the single largest one within each calendar year, and
        separately within each calendar month (aggregated across all years),
        is recorded and flagged ``FILLED`` or ``NOT FILLED (>Xh)`` against
        that variable's specific gap-size limit (see the hard-coded
        ``interpolation_limits`` matching :meth:`_fill_data`'s per-variable
        limits).

        Args:
            df_before (pandas.DataFrame): Data before gap filling.
            working_cols (list[str]): Canonical variable names to analyse.

        Returns:
            pandas.DataFrame: One row per (variable, period) with columns
            ``Variable``, ``Type`` (``'YEAR'`` or ``'MONTH'``), ``Period``
            (the year number or month number 1-12), ``Max_gap_hours``,
            ``Start``, ``End`` and ``Fill_Status``.
        """
        max_gaps = []
        interpolation_limits = {'Pressure': 72, 'Dry-bulb': 24, 'Dew Point': 24, 'RH': 24,
                                'WindSpeed': 3, 'WindDir': 2, 'GHI': 24, 'BHI': 24, 'DHI': 24, 'BNI': 24}

        for col in working_cols:
            if col not in df_before.columns: continue
            s = df_before[col]
            is_nan = s.isna()

            gap_id = (~is_nan).cumsum()[is_nan]
            if gap_id.empty: continue

            gap_sizes = gap_id.value_counts().sort_index()
            gap_starts = s[is_nan].reset_index().groupby(gap_id.values).first()['time']
            gap_ends = s[is_nan].reset_index().groupby(gap_id.values).last()['time']

            gaps_info = pd.DataFrame({'size': gap_sizes.values, 'start': gap_starts.values, 'end': gap_ends.values})
            gaps_info['year'] = gaps_info['start'].dt.year
            gaps_info['month'] = gaps_info['start'].dt.month
            limit = interpolation_limits.get(col, 0)

            for y, group in gaps_info.groupby('year'):
                idx_max = group['size'].idxmax()
                row = group.loc[idx_max]
                size = int(row['size'])
                status = "FILLED" if size <= limit else f"NOT FILLED (>{limit}h)"
                max_gaps.append({'Variable': col, 'Type': 'YEAR', 'Period': y, 'Max_gap_hours': size, 'Start': row['start'], 'End': row['end'], 'Fill_Status': status})

            for m, group in gaps_info.groupby('month'):
                idx_max = group['size'].idxmax()
                row = group.loc[idx_max]
                size = int(row['size'])
                status = "FILLED" if size <= limit else f"NOT FILLED (>{limit}h)"
                max_gaps.append({'Variable': col, 'Type': 'MONTH', 'Period': m, 'Max_gap_hours': size, 'Start': row['start'], 'End': row['end'], 'Fill_Status': status})

        return pd.DataFrame(max_gaps)

    # -------------------------------------------------------
    # 4. THE 3 REQUESTED PUBLIC METHODS (Generating XLSX)
    # -------------------------------------------------------
    def export_filled_data(self, output_name='FILLED_Data.xlsx'):
        """Export only the final, gap-filled hourly data (:attr:`df`,
        restricted to :attr:`working_cols`) to a single-sheet Excel file.

        Args:
            output_name (str, optional): Output ``.xlsx`` path. Defaults to
                ``'FILLED_Data.xlsx'``.

        Returns:
            str: *output_name*, for convenient chaining/printing.

        Example:
            >>> proc.export_filled_data("filled.xlsx")  # doctest: +SKIP
            'filled.xlsx'
        """
        self._log(f"Saving {output_name}...")
        self.df[self.working_cols].reset_index().to_excel(output_name, index=False)
        return output_name

    def export_annual_statistics(self, output_name='ANNUAL_STATISTICS.xlsx'):
        """Export the quality-control report to a 2-sheet Excel file:
        :attr:`annual_stats` (sheet ``'annual_stats'``) and
        :attr:`max_gaps_df` (sheet ``'max_gaps'``). Empty tables are
        skipped.

        Args:
            output_name (str, optional): Output ``.xlsx`` path. Defaults to
                ``'ANNUAL_STATISTICS.xlsx'``.

        Returns:
            str: *output_name*, for convenient chaining/printing.

        Example:
            >>> proc.export_annual_statistics("quality.xlsx")  # doctest: +SKIP
            'quality.xlsx'
        """
        self._log(f"Saving {output_name}...")
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            if not self.annual_stats.empty:
                self.annual_stats.to_excel(writer, sheet_name='annual_stats')
            if not self.max_gaps_df.empty:
                self.max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)
        return output_name

    def export_complete_report(self, output_name='FILLED_with_gaps_report.xlsx'):
        """Export the full, 5-sheet quality-control Excel workbook: filled
        data (``'filled'``), completeness summary (``'summary'``), the list
        of interpolated gaps (``'gaps'``), annual statistics
        (``'annual_stats'``) and the largest-gap-per-period table
        (``'max_gaps'``). This is the recommended one-stop export for
        auditing a station's data-quality journey end to end.

        Args:
            output_name (str, optional): Output ``.xlsx`` path. Defaults to
                ``'FILLED_with_gaps_report.xlsx'``.

        Returns:
            str: *output_name*, for convenient chaining/printing.

        Example:
            >>> proc.export_complete_report("full_report.xlsx")  # doctest: +SKIP
            'full_report.xlsx'
        """
        self._log(f"Saving {output_name}...")
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            self.df[self.working_cols].reset_index().to_excel(writer, sheet_name='filled', index=False)
            if self.summary is not None:
                self.summary.to_excel(writer, sheet_name='summary', index=False)
            if not self.gaps_df.empty:
                self.gaps_df.to_excel(writer, sheet_name='gaps', index=False)
            if not self.annual_stats.empty:
                self.annual_stats.to_excel(writer, sheet_name='annual_stats')
            if not self.max_gaps_df.empty:
                self.max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)
        return output_name


