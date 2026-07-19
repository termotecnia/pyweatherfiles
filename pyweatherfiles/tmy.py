# -*- coding: utf-8 -*-
"""
==============================================================================
      COMPLETE SCRIPT FOR TMY GENERATION (VERSION 4.10 - Unified Method)
==============================================================================
Methodology: Sandia TMY3, with selectable CDF calculation methods.

Changelog::

    v4.10:
    - Refactored public step methods to align precisely with Sandia 7-step
      process (sandia_step_1 to sandia_step_7).
    - Added fine-grained validation dataframes (validation_step1 to
      validation_step6).
    - Deprecated old step_1 through step_4 methods (they now wrap the new
      methods and emit warnings).
    - Fixed the previous discrepancy where validation_st2_summary_fs_ranking
      actually contained candidates in proximity order. Now validation_step2
      is strict FS order, and validation_step3 contains the proximity order.

    v4.09:
    - Added get_candidate_stats(month): returns a DataFrame with T_air and
      GHI statistics (mean, diff vs. long-term, percentile) for each of the
      top-5 candidate years of a given month.
    - Added analyze_selection(months, temp_diff_threshold): audits the TMY
      month selection, flags months where the selected year deviates from
      the long-term temperature mean beyond the given threshold.
    - Added correct_selection_by_temperature(months, temp_diff_threshold,
      regenerate): automatically replaces anomalous selections with the
      top-5 candidate that minimises the absolute difference to the
      long-term mean, and optionally regenerates the TMY in-place.
    - Added plot_monthly_trend(months, variable): plots the long-term yearly
      trend for each month with TMY-selected year highlighted by a star.
    - Added plot_monthly_series(months, variable): overlays daily series for
      all years on the same axes, highlighting the TMY-selected year in red.
    - Added compare_tmy_versions(other_tmy_df, ...): side-by-side comparison
      of two TMY DataFrames for specified months.

    v4.08:
    - The plot_smoothing_comparison method now displays the hours and
      s_factor parameters used for smoothing directly in the title of each
      subplot, improving traceability.
    - The smoothing_config is now stored as a class attribute
      (self.smoothing_config) during Step 4 to make it accessible to the
      plotting function.

Author: Gemini AI & Project Contributor
Date: November 4, 2025
"""

# --- LIBRARY IMPORTS ---
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, UnivariateSpline
import matplotlib.pyplot as plt
import os
import warnings
import copy
from .session_manager import save_object_session


# ==============================================================================
#                MAIN CLASS: TMYGenerator
# ==============================================================================

class TMYGenerator:
    """
    A class to generate a Typical Meteorological Year (TMY) from historical
    weather data, using one of several selectable methodologies.

    This is the core class of the ``pyweatherfiles`` package: it implements
    the Sandia National Laboratories TMY generation method (Hall et al.,
    1978), with additional support for NREL's TMY3 weighting scheme (Wilcox
    & Marion, 2008). The method is structured in **7 sequential steps**
    (:meth:`sandia_step_1_load_and_prepare` through
    :meth:`sandia_step_7_smooth_junctions`), orchestrated by
    :meth:`generate_tmy`:

    1. **Load & prepare** — read the source file, map columns, resample to
       hourly (if applicable) and compute the daily aggregates required by
       the weighting scheme.
    2. **Finkelstein-Schafer (FS) candidate selection** — for each calendar
       month, rank all available years by how closely their empirical CDF
       matches the long-term CDF, keeping the 5 best candidates.
    3. **Proximity ranking** — re-order the 5 FS candidates by closeness of
       their monthly mean/median temperature and GHI to the long-term
       statistics (Sawaqed et al., 2005).
    4. **Persistence filtering & final selection** — exclude candidates
       with atypical runs of consecutive extreme days (either via a
       deterministic ``'sequential'`` exclusion process or a weighted
       ``'score'``), then pick the best-ranked survivor (steps 4 and 5 of
       the original Sandia methodology).
    5. **Raw TMY assembly** — concatenate the 12 selected months (one
       source year each) into a single synthetic year.
    6. **Junction smoothing** — fit a smoothing spline across each of the
       11 month-to-month junctions (using hourly data) to remove abrupt
       discontinuities, while leaving solar radiation untouched.

    Deprecated aliases (``step_1_load_and_prepare_data``,
    ``step_2_select_candidate_months``, ``step_3_apply_persistence``,
    ``step_4_create_and_smooth_tmy``) and compatibility properties for the
    old ``validation_st*`` attribute names are kept for backward
    compatibility; they simply delegate to the ``sandia_step_*``
    counterparts and emit a ``DeprecationWarning``.

    Attributes:
        file_path (str): Path to the source CSV/Excel file, as passed to
            the constructor.
        hourly_file_path (str or None): Optional additional hourly source
            file (see constructor).
        cdf_method (str): ``'daily'`` or ``'hourly'`` — resolution used for
            the Finkelstein-Schafer CDF comparison in Step 2.
        data_frequency (str): ``'hourly'`` or ``'daily'`` — resolution of
            the source file itself.
        weighting_method (str): ``'sandia'`` or ``'tmy3'`` — which default
            variable-weight table is used.
        weights (dict): Effective per-variable weights used for the
            weighted FS statistic (either the method-specific defaults or
            the user-supplied override).
        years_to_include (iterable or None): Restricts the analysis to a
            subset of calendar years, as passed to the constructor.
        missing_data_threshold (float): Minimum fraction of valid data
            points (0-1) a candidate month must have to avoid exclusion in
            Step 2.
        plotting_position_method (str): ``'hazen'``, ``'weibull'`` or
            ``'california'`` — empirical CDF plotting-position formula.
        base_mapping (dict): The subset of the column mapping derived only
            from the explicit ``col_*``/``datetime_col`` constructor
            arguments (used by :meth:`export_tmy` to restore original
            column names).
        column_mapping (dict): The full effective column-name mapping
            (``base_mapping`` merged with legacy shortcuts and any
            *column_mapping* override), applied when loading the source
            file(s).
        df_hourly (pandas.DataFrame or None): Hourly source data after Step
            1 (``None`` if ``data_frequency='daily'`` and no
            *hourly_file_path* was given).
        df_daily (pandas.DataFrame or None): Daily source data / aggregates
            after Step 1.
        excluded_months (list[tuple[int, int]]): ``(year, month)`` pairs
            excluded in Step 2 due to insufficient data completeness.
        excluded_months_initial (list[tuple[int, int]]): ``(year, month)``
            pairs excluded in Step 1 while filtering the separate hourly
            file to the months present in the daily file.
        candidate_months_pre_proximity (dict[int, list[int]]): Top-5 FS
            candidate years per calendar month, in FS order (before Step 3).
        candidate_months (dict[int, list[int]]): Top-5 candidate years per
            calendar month, re-ordered by proximity (after Step 3); this is
            the list Steps 4-5 operate on.
        fs_ranking_results (dict[int, list[dict]]): Per-month list of dicts
            with the FS/proximity metrics of each of the 5 candidates.
        selected_months (dict[int, int] or None): The single, final source
            year chosen for each calendar month (populated by Steps 4-5, or
            directly by :meth:`_select_months_by_fs_rank` when
            ``use_persistence=False``).
        persistence_thresholds (tuple[float, float] or None): The
            ``(lower, upper)`` percentile thresholds used to define
            "runs" in the persistence step.
        min_run_length (int or None): Minimum number of consecutive days to
            count as a persistence "run".
        tmy_raw (pandas.DataFrame or None): The assembled-but-unsmoothed TMY
            (after Step 6).
        tmy_final (pandas.DataFrame or None): The final TMY, smoothed at
            month junctions if hourly data was available (after Step 7).
            This is what :meth:`export_tmy` writes to disk.
        smoothing_config (dict or None): Per-junction smoothing parameters
            actually used in Step 7 (``hours_before``/``hours_after``/
            ``s_factor``, plus the auto-computed spline residual when
            applicable).
        save_validation_dfs (bool): Whether the ``validation_step*``
            diagnostic DataFrames are populated as the workflow runs.
        save_session (bool): Whether a reproducible ``.pkl``/``.json``
            session is saved automatically at the end of Step 7.
        session_dir (str or None): Directory for the session files (see
            :mod:`~pyweatherfiles.session_manager`).
        figures_data (dict): Maps a figure title to
            ``{'fig': matplotlib.figure.Figure, 'data': pandas.DataFrame}``
            for every ``plot_*`` call made with ``save_figure_data=True``.
        validation_step2_fs_ranking_by_month (dict[int, pandas.DataFrame]):
            Full (all-years) FS ranking table per month.
        validation_step2_summary_fs_ranking (pandas.DataFrame or None):
            Summary of the top-5 FS candidates for every month.
        validation_step3_proximity_ranking (pandas.DataFrame or None):
            Summary of the top-5 candidates re-ordered by proximity, with
            their normalised/raw deviation metrics.
        validation_step4_df_persistence_decision (pandas.DataFrame or dict):
            Persistence decision details (``'score'`` method) across all
            months, concatenated into one table.
        validation_step4_persistence_sequential_details (dict[int, pandas.DataFrame] or None):
            Per-month exclusion-pass details (``'sequential'`` method).
        validation_step4_persistence_score_details (dict[int, pandas.DataFrame] or None):
            Per-month scoring details (``'score'`` method).
        validation_step5_selected_months_summary (pandas.DataFrame or None):
            Simple ``Month -> Selected_Year`` summary table.
        validation_step6_tmy_composition (pandas.DataFrame or None):
            Detailed TMY composition table merging FS, proximity and
            persistence stats for each selected month.
        validation_full_summary (pandas.DataFrame or None): One-row-per-month
            consolidated summary across all steps (populated by
            :meth:`generate_full_summary`).
        validation_selection_analysis (pandas.DataFrame or None): Flagged
            selection-audit table (populated by :meth:`analyze_selection`).

    Example:
        >>> from pyweatherfiles import tmy
        >>> gen = tmy.TMYGenerator(
        ...     file_path="weather_data.csv",
        ...     cdf_method="daily",
        ...     data_frequency="hourly",
        ...     weighting_method="sandia",
        ... )  # doctest: +SKIP
        >>> gen.generate_tmy(use_persistence=True)  # doctest: +SKIP
        >>> gen.export_tmy("tmy_output.csv")  # doctest: +SKIP
    """

    def __init__(self, file_path, cdf_method='daily', years_to_include=None, weights=None, 
                 column_mapping=None, data_frequency='hourly', weighting_method='sandia', 
                 save_validation_dfs=True, hourly_file_path=None, missing_data_threshold=0.9, 
                 plotting_position_method='hazen',
                 datetime_col='time',
                 col_temp='T_air',
                 col_dew='T_dew',
                 col_wind='Wind_speed',
                 col_ghi='GHI',
                 col_dni='DNI',
                 save_session=True,
                 session_dir=None):
        """
        Initializes the TMYGenerator.

        Args:
            file_path (str): The path to the input CSV file.
            cdf_method (str): The method for CDF calculation. Must be one of:
                'daily' (default): Uses daily aggregated data.
                'hourly': Uses full hourly data (computationally intensive).
            years_to_include (iterable, optional): Years to include. If None, all are used.
            weights (dict, optional): Custom weights for FS statistic calculation.
            column_mapping (dict, optional): Maps input column names to standard names.
            data_frequency (str, optional): Frequency of the input data. 'hourly' (default) or 'daily'.
            weighting_method (str, optional): The weighting scheme to use. 'sandia' (default) or 'tmy3'.
            save_validation_dfs (bool, optional): Whether to save validation dataframes.
            hourly_file_path (str, optional): Path to hourly data file. When data_frequency='daily',
                this allows generating the final TMY from hourly data after selecting months based
                on daily analysis. Only months available in the daily file will be used.
            missing_data_threshold (float, optional): Threshold for missing data to exclude a month. Default is 0.9.
            plotting_position_method (str, optional): The method for calculating CDF plotting positions.
                Must be one of: 'california', 'hazen', 'weibull'. Default is 'hazen'.
            datetime_col (str, optional): Name of the datetime column. Default is 'time'.
            col_temp (str, optional): Name of the air temperature column. Default is 'T_air'.
            col_dew (str, optional): Name of the dew point temperature column. Default is 'T_dew'.
            col_wind (str, optional): Name of the wind speed column. Default is 'Wind_speed'.
            col_ghi (str, optional): Name of the global horizontal irradiance column. Default is 'GHI'.
            col_dni (str, optional): Name of the direct normal irradiance column. Default is 'DNI'.
        """
        self.file_path = file_path
        self.hourly_file_path = hourly_file_path
        self.missing_data_threshold = missing_data_threshold
        self.excluded_months = [] # Store months excluded due to insufficient data
        self.excluded_months_initial = [] # Store months excluded during data loading (Step 1)
        
        # Dictionary to store generated figures and their underlying data
        # Structure: { 'Figure Name': { 'fig': matplotlib.figure.Figure, 'data': pd.DataFrame } }
        self.figures_data = {}

        # Validate data frequency
        valid_frequencies = ['hourly', 'daily']
        if data_frequency not in valid_frequencies:
            raise ValueError(f"Invalid data_frequency '{data_frequency}'. Must be one of {valid_frequencies}")
        self.data_frequency = data_frequency

        # Validate plotting position method
        valid_pp_methods = ['california', 'hazen', 'weibull']
        if plotting_position_method not in valid_pp_methods:
            raise ValueError(f"Invalid plotting_position_method '{plotting_position_method}'. Must be one of {valid_pp_methods}")
        self.plotting_position_method = plotting_position_method
        if self.plotting_position_method != 'california':
            print(f"Using '{self.plotting_position_method}' plotting position for CDF calculation.")

        # Validate and set the CDF calculation method
        # Validate and set the CDF calculation method
        valid_methods = ['daily', 'hourly']
        if cdf_method not in valid_methods:
            raise ValueError(f"Invalid cdf_method '{cdf_method}'. Must be one of {valid_methods}")

        if self.data_frequency == 'daily' and cdf_method == 'hourly':
            raise ValueError("Cannot use cdf_method='hourly' with data_frequency='daily'.")

        self.cdf_method = cdf_method

        # Validate weighting method
        valid_weighting = ['sandia', 'tmy3']
        if weighting_method not in valid_weighting:
            raise ValueError(f"Invalid weighting_method '{weighting_method}'. Must be one of {valid_weighting}")
        self.weighting_method = weighting_method

        self.years_to_include = years_to_include

        # Set default weights based on the chosen method
        if weights is None:  # Only set defaults if user didn't provide custom weights
            if self.cdf_method == 'hourly':
                if self.weighting_method == 'tmy3':
                    default_weights = {
                        'T_air': 4 / 20, 'T_dew': 4 / 20,
                        'Wind_speed': 2 / 20, 'GHI': 5 / 20, 'DNI': 5 / 20
                    }
                else:  # 'sandia' default
                    default_weights = {
                        'T_air': 4 / 24, 'T_dew': 4 / 24,
                        'Wind_speed': 4 / 24, 'GHI': 12 / 24
                    }
            else:
                if self.weighting_method == 'tmy3':
                    # Weights based on NREL TMY3 / User provided Picture1.png
                    default_weights = {
                        'T_air_max': 1 / 20, 'T_air_min': 1 / 20, 'T_air_mean': 2 / 20,
                        'T_dew_max': 1 / 20, 'T_dew_min': 1 / 20, 'T_dew_mean': 2 / 20,
                        'Wind_speed_max': 1 / 20, 'Wind_speed_mean': 1 / 20,
                        'GHI_sum': 5 / 20, 'DNI_sum': 5 / 20
                    }
                else:  # 'sandia' default
                    # Detailed Sandia weights from Picture1.png
                    default_weights = {
                        'T_air_max': 1 / 24, 'T_air_min': 1 / 24, 'T_air_mean': 2 / 24,
                        'T_dew_max': 1 / 24, 'T_dew_min': 1 / 24, 'T_dew_mean': 2 / 24,
                        'Wind_speed_max': 2 / 24, 'Wind_speed_mean': 2 / 24,
                        'GHI_sum': 12 / 24
                        # DNI is excluded for Sandia
                    }
            self.weights = default_weights
        else:
            self.weights = weights

        # Base mapping from explicit column arguments
        self.base_mapping = {
            datetime_col: 'time',
            col_temp: 'T_air',
            col_dew: 'T_dew',
            col_wind: 'Wind_speed',
            col_ghi: 'GHI',
            col_dni: 'DNI'
        }
        # Only keep entries where the name actually differs from the target
        self.base_mapping = {k: v for k, v in self.base_mapping.items() if k != v}

        default_mapping = {'temp': 'T_air', 'dwpt': 'T_dew', 'wspd': 'Wind_speed'}
        self.column_mapping = {**self.base_mapping, **default_mapping, **(column_mapping or {})}

        self.df_hourly = None
        self.df_daily = None
        self.candidate_months = None
        self.fs_ranking_results = {}
        self.selected_months = None
        self.tmy_raw = None
        self.tmy_final = None
        self.persistence_thresholds = None
        self.min_run_length = None

        self.validation_step2_fs_ranking_by_month = {}
        self.validation_step2_summary_fs_ranking = None
        self.validation_step3_proximity_ranking = None
        self.validation_step4_df_persistence_decision = {}
        self.validation_step4_persistence_sequential_details = None
        self.validation_step4_persistence_score_details = None
        self.validation_step5_selected_months_summary = None
        self.validation_step6_tmy_composition = None
        self.candidate_months_pre_proximity = None
        self.smoothing_config = None  # Attribute to store the used smoothing config
        self.save_validation_dfs = save_validation_dfs
        self.validation_full_summary = None        # Generated by generate_full_summary()
        self.validation_selection_analysis = None  # Generated by analyze_selection()
        # Session persistence
        self.save_session = save_session
        self.session_dir = session_dir

    # --- BACKWARD COMPATIBILITY PROPERTIES ---
    # These properties exist solely so that code written against pre-4.10
    # versions of this class (which used the ``validation_st2_*``/
    # ``validation_st3_*``/``validation_st4_*`` attribute names) keeps
    # working transparently: reading/writing them redirects to the current
    # ``validation_step*`` attribute described in the class docstring.

    @property
    def validation_st2_df_fs_ranking_by_month(self):
        """dict[int, pandas.DataFrame]: Deprecated alias for
        :attr:`validation_step2_fs_ranking_by_month`."""
        return self.validation_step2_fs_ranking_by_month

    @validation_st2_df_fs_ranking_by_month.setter
    def validation_st2_df_fs_ranking_by_month(self, value):
        self.validation_step2_fs_ranking_by_month = value

    @property
    def validation_st2_summary_fs_ranking(self):
        """pandas.DataFrame or None: Deprecated alias for
        :attr:`validation_step3_proximity_ranking` (kept under its
        historical name; the top-5 candidates it stores were already in
        proximity order in the original implementation)."""
        # Maps to proximity ranking since originally it stored the top 5 in proximity order
        return self.validation_step3_proximity_ranking

    @validation_st2_summary_fs_ranking.setter
    def validation_st2_summary_fs_ranking(self, value):
        self.validation_step3_proximity_ranking = value

    @property
    def validation_st3_df_persistence_decision(self):
        """pandas.DataFrame or dict: Deprecated alias for
        :attr:`validation_step4_df_persistence_decision`."""
        return self.validation_step4_df_persistence_decision

    @validation_st3_df_persistence_decision.setter
    def validation_st3_df_persistence_decision(self, value):
        self.validation_step4_df_persistence_decision = value

    @property
    def validation_st3_persistence_sequential_details(self):
        """dict[int, pandas.DataFrame] or None: Deprecated alias for
        :attr:`validation_step4_persistence_sequential_details`."""
        return self.validation_step4_persistence_sequential_details

    @validation_st3_persistence_sequential_details.setter
    def validation_st3_persistence_sequential_details(self, value):
        self.validation_step4_persistence_sequential_details = value

    @property
    def validation_st3_persistence_score_details(self):
        """dict[int, pandas.DataFrame] or None: Deprecated alias for
        :attr:`validation_step4_persistence_score_details`."""
        return self.validation_step4_persistence_score_details

    @validation_st3_persistence_score_details.setter
    def validation_st3_persistence_score_details(self, value):
        self.validation_step4_persistence_score_details = value

    @property
    def validation_st4_df_tmy_composition(self):
        """pandas.DataFrame or None: Deprecated alias for
        :attr:`validation_step6_tmy_composition`."""
        return self.validation_step6_tmy_composition

    @validation_st4_df_tmy_composition.setter
    def validation_st4_df_tmy_composition(self, value):
        self.validation_step6_tmy_composition = value

    # --- PRIVATE METHODS (INTERNAL LOGIC) ---

    def _load_and_prepare_real_data(self):
        """Loads and prepares the raw weather data from the source file."""
        print(f"Loading and preparing data from '{self.file_path}'...")
        if self.file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(self.file_path)
        else:
            df = pd.read_csv(self.file_path)

        # Apply column mapping immediately to ensure 'time' and other keys are available
        df = df.rename(columns=self.column_mapping)

        df['time'] = pd.to_datetime(df['time'], errors='coerce', utc=True)
        df.dropna(subset=['time'], inplace=True)
        df.set_index('time', inplace=True)
        assert isinstance(df.index, pd.DatetimeIndex), "ERROR: The 'time' column could not be converted to a DatetimeIndex."

        available_years = sorted(df.index.year.unique())
        if self.years_to_include is not None:
            print(f"Filtering data to include only the years: {list(self.years_to_include)}")
            missing_years = set(self.years_to_include) - set(available_years)
            if missing_years: raise ValueError(f"Requested years not found: {sorted(list(missing_years))}. Available years: {available_years}")
            df = df[df.index.year.isin(self.years_to_include)]
        else:
            print(f"Using all available years in the file: {available_years}")

        if self.data_frequency == 'hourly':
            required_internal_cols = ['T_air', 'T_dew', 'Wind_speed']
            missing_cols = [col for col in required_internal_cols if col not in df.columns]
            if missing_cols: raise ValueError(f"ERROR: Essential columns are missing after mapping: {missing_cols}")

        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        if self.data_frequency == 'hourly':
            print("Resampling data to hourly frequency and interpolating gaps...")
            df = df.resample('h').mean().interpolate(method='linear')

            if 'GHI' not in df.columns:
                print("\nWARNING: 'GHI' data not found. A placeholder column of zeros has been created.")
                df['GHI'] = 0.0

            self.df_hourly = df[['T_air', 'T_dew', 'Wind_speed', 'GHI']]
            if 'DNI' in df.columns:
                self.df_hourly = self.df_hourly.assign(DNI=df['DNI'])
            
            # --- FIX: Clip negative irradiance and wind values to 0 ---
            for col in ['GHI', 'DNI', 'Wind_speed']:
                if col in self.df_hourly.columns:
                    negative_count = (self.df_hourly[col] < 0).sum()
                    if negative_count > 0:
                        print(f"  Note: {negative_count} negative values found in '{col}'. Clipping to 0.")
                        self.df_hourly[col] = self.df_hourly[col].clip(lower=0)

            # --- Detailed Aggregation Logic for Hourly Data (Sandia & TMY3) ---
            if self.weighting_method in ['tmy3', 'sandia']:
                print(f"Calculating daily aggregations for weighting method: {self.weighting_method}...")
                # Prepare daily dataframe with specific metrics
                daily_agg = pd.DataFrame(index=df.resample('D').mean().index)

                # Temperature
                daily_agg['T_air_mean'] = df['T_air'].resample('D').mean()
                daily_agg['T_air_max'] = df['T_air'].resample('D').max()
                daily_agg['T_air_min'] = df['T_air'].resample('D').min()

                # Dew Point
                daily_agg['T_dew_mean'] = df['T_dew'].resample('D').mean()
                daily_agg['T_dew_max'] = df['T_dew'].resample('D').max()
                daily_agg['T_dew_min'] = df['T_dew'].resample('D').min()

                # Wind Speed
                daily_agg['Wind_speed_mean'] = df['Wind_speed'].resample('D').mean()
                daily_agg['Wind_speed_max'] = df['Wind_speed'].resample('D').max()

                # GHI
                daily_agg['GHI_sum'] = df['GHI'].resample('D').sum()

                # DNI (Only for TMY3)
                if self.weighting_method == 'tmy3':
                    if 'DNI' in df.columns:
                        daily_agg['DNI_sum'] = df['DNI'].resample('D').sum()
                    else:
                        print("\nWARNING: 'DNI' column missing for TMY3 method. Assuming 0.")
                        daily_agg['DNI_sum'] = 0.0

                self.df_daily = daily_agg
                print(f"DEBUG: df_daily columns created: {self.df_daily.columns.tolist()}")

        else:
            print("Processing daily data...")
            # For daily data, we don't resample to hourly.
            self.df_hourly = None

            # For daily data with custom weights/variables (like Madrid dataset),
            # we allow any columns that result from the mapping.
            # We just verify that we have at least some data.
            if df.empty:
                raise ValueError("The input dataframe is empty after loading.")

            self.df_daily = df.copy()

            # Warn if standard columns are missing, but don't error out if using custom method
            missing_standard = [c for c in ['T_air', 'T_dew', 'Wind_speed'] if c not in df.columns]
            if missing_standard and self.weighting_method not in ['tmy3', 'sandia']:  # these methods use different columns
                print(f"Note: Standard columns {missing_standard} not found. Assuming custom variable configuration.")

            if 'GHI' not in df.columns and 'GHI_sum' not in df.columns:
                # Try to find a GHI-like column or warn
                print("\nWARNING: No 'GHI' or 'GHI_sum' column found. Ensure your weights align with available columns.")

            if self.weighting_method in ['tmy3', 'sandia']:
                required_keys = [k for k in self.weights.keys()]
                missing_keys = [col for col in required_keys if col not in self.df_daily.columns]
                if missing_keys:
                    print(f"\nWARNING: {self.weighting_method} method selected but components {missing_keys} are missing in daily data.")
                    print("Ensure your input file or column mapping provides these.")

        # --- Load hourly data from separate file if provided ---
        if self.hourly_file_path is not None:
            print(f"\nLoading hourly data from '{self.hourly_file_path}'...")
            
            # Load hourly file
            if self.hourly_file_path.endswith(('.xlsx', '.xls')):
                df_hourly_source = pd.read_excel(self.hourly_file_path)
            else:
                df_hourly_source = pd.read_csv(self.hourly_file_path)
            
            # Apply column mapping
            df_hourly_source = df_hourly_source.rename(columns=self.column_mapping)
            
            # Process datetime index
            df_hourly_source['time'] = pd.to_datetime(df_hourly_source['time'], errors='coerce', utc=True)
            df_hourly_source.dropna(subset=['time'], inplace=True)
            df_hourly_source.set_index('time', inplace=True)
            
            # Filter to same years as primary data
            if self.years_to_include is not None:
                df_hourly_source = df_hourly_source[df_hourly_source.index.year.isin(self.years_to_include)]
            
            # Convert columns to numeric
            for col in df_hourly_source.columns:
                df_hourly_source[col] = pd.to_numeric(df_hourly_source[col], errors='coerce')
            
            # Resample to hourly and interpolate
            print("Resampling hourly data and interpolating gaps...")
            df_hourly_source = df_hourly_source.resample('h').mean().interpolate(method='linear')
            
            # Get available months from daily data to filter hourly data
            if self.df_daily is not None:
                available_months_in_daily = set(self.df_daily.index.to_period('M'))
                print(f"Filtering hourly data to only include months available in daily data...")
                
                # Filter hourly data to only include months present in daily data
                hourly_periods = df_hourly_source.index.to_period('M')
                mask = hourly_periods.isin(available_months_in_daily)
                
                excluded_count = (~mask).sum()
                if excluded_count > 0:
                    print(f"  Excluded {excluded_count} hourly records from months not in daily file.")
                    
                    # Store excluded months for reporting
                    excluded_data = df_hourly_source[~mask]
                    excluded_periods = excluded_data.index.to_period('M').unique()
                    for p in excluded_periods:
                        self.excluded_months_initial.append((p.year, p.month))
                    
                    # Sort uniquely
                    self.excluded_months_initial = sorted(list(set(self.excluded_months_initial)))

                df_hourly_source = df_hourly_source[mask]
            
            # Ensure required columns exist
            required_hourly_cols = ['T_air', 'T_dew', 'Wind_speed']
            missing_hourly_cols = [col for col in required_hourly_cols if col not in df_hourly_source.columns]
            if missing_hourly_cols:
                raise ValueError(f"ERROR: Essential columns missing in hourly file: {missing_hourly_cols}")
            
            if 'GHI' not in df_hourly_source.columns:
                print("\nWARNING: 'GHI' not found in hourly file. Creating placeholder column of zeros.")
                df_hourly_source['GHI'] = 0.0
            
            # Store hourly data — keep ALL columns from the source file so that
            # extra variables are available for export in export_tmy().
            # Core columns (T_air, T_dew, Wind_speed, GHI) are already validated above.
            self.df_hourly = df_hourly_source.copy()
            # Ensure GHI placeholder is present if it was just added
            # (already done above, but copy() will carry it over)
            
            # --- FIX: Clip negative irradiance and wind values to 0 ---
            for col in ['GHI', 'DNI', 'Wind_speed']:
                if col in self.df_hourly.columns:
                    negative_count = (self.df_hourly[col] < 0).sum()
                    if negative_count > 0:
                        print(f"  Note: {negative_count} negative values found in '{col}' (hourly file). Clipping to 0.")
                        self.df_hourly[col] = self.df_hourly[col].clip(lower=0)
            
            print(f"Hourly data loaded successfully with {len(self.df_hourly)} records.")

        print("Real data loaded and prepared.")

    def _compute_cdf(self, series):
        """Computes the Cumulative Distribution Function (CDF) of a data series."""
        if self.plotting_position_method == 'hazen':
            return np.sort(series), (np.arange(1, len(series) + 1) - 0.5) / len(series)
        elif self.plotting_position_method == 'weibull':
            return np.sort(series), np.arange(1, len(series) + 1) / (len(series) + 1)
        else: # 'california' (previous default)
            return np.sort(series), np.arange(1, len(series) + 1) / len(series)

    def _compute_interpolated_cdf(self, series1, series2, num_points=200):
        """
        Computes interpolated CDFs for two series on a common axis.
        
        This method is used for visualization to ensure both CDFs are plotted
        on the same x-axis, making them directly comparable. The interpolation
        approach matches what is used in the FS statistic calculation.
        
        Args:
            series1: First data series (e.g., long-term data)
            series2: Second data series (e.g., TMY data)
            num_points (int): Number of interpolation points (default: 200)
            
        Returns:
            tuple: (common_x, interp_cdf1, interp_cdf2)
                - common_x: Common x-axis values
                - interp_cdf1: Interpolated CDF for series1
                - interp_cdf2: Interpolated CDF for series2
        """
        vals1, cdf1 = self._compute_cdf(series1)
        vals2, cdf2 = self._compute_cdf(series2)
        
        common_x = np.linspace(
            min(series1.min(), series2.min()),
            max(series1.max(), series2.max()),
            num=num_points
        )
        
        interp_cdf1 = np.interp(common_x, vals1, cdf1, left=0, right=1)
        interp_cdf2 = np.interp(common_x, vals2, cdf2, left=0, right=1)
        
        return common_x, interp_cdf1, interp_cdf2

    def _calculate_fs_statistic(self, candidate_series, long_term_series, return_details=False):
        """Calculates the Finkelstein-Schafer (FS) statistic between two series."""
        # Calculate CDFs
        cand_vals, cand_cdf = self._compute_cdf(candidate_series)
        lt_vals, lt_cdf = self._compute_cdf(long_term_series)

        # -- FS Calculation based on discrete sum over N days (Candidate data points) --
        # Formula: FS = (1/N) * sum(|CDF_cand(x_d) - CDF_lt(x_d)|)
        # where N is number of days (or points) in candidate set.
        
        N = len(candidate_series)
        
        # Interpolate Long-Term CDF to find probabilities at Candidate values
        # We compare the Candidate CDF value at x (which is k/N) with Long-Term CDF at x.
        interp_lt_cdf_at_cand = np.interp(cand_vals, lt_vals, lt_cdf, left=0, right=1)
        
        # Calculate FS
        fs = np.sum(np.abs(cand_cdf - interp_lt_cdf_at_cand)) / N

        if return_details:
            # For visualization, we keep the smooth interpolation on a common axis
            common_x = np.linspace(min(candidate_series.min(), long_term_series.min()),
                                   max(candidate_series.max(), long_term_series.max()), num=200)
            interp_cand_cdf_vis = np.interp(common_x, cand_vals, cand_cdf, left=0, right=1)
            interp_lt_cdf_vis = np.interp(common_x, lt_vals, lt_cdf, left=0, right=1)
            
            return fs, common_x, interp_lt_cdf_vis, interp_cand_cdf_vis, (lt_vals, lt_cdf), (cand_vals, cand_cdf)
            
        return fs

    def _generate_ranking_table_for_month(self, month, analysis_df):
        """Helper to generate detailed FS ranking table for a month."""
        long_term_data_month = analysis_df[analysis_df.index.month == month]
        all_years = analysis_df.index.year.unique()

        ranking_data = []
        for year in all_years:
            candidate_data_year = long_term_data_month[long_term_data_month.index.year == year]
            if candidate_data_year.empty: continue

            # Basic completeness check (replicated/simplified here for ranking table generation)
            # If we are calling this from _select_candidate_months, we might have already filtered.
            # But validation usually shows all available years.

            row = {'Year': year}
            total_w_fs = 0

            for var, weight in self.weights.items():
                fs_val = self._calculate_fs_statistic(candidate_data_year[var], long_term_data_month[var])
                weighted_fs = fs_val * weight
                row[f'FS_{var}'], row[f'Weight_{var}'], row[f'W_FS_{var}'] = fs_val, weight, weighted_fs
                total_w_fs += weighted_fs
            row['Total_W_FS'] = total_w_fs
            ranking_data.append(row)

        df_ranking = pd.DataFrame(ranking_data).sort_values('Total_W_FS').reset_index(drop=True)
        df_ranking['Rank'] = df_ranking.index + 1

        ordered_columns = ['Year']
        for var in self.weights.keys():
            ordered_columns.extend([f'FS_{var}', f'Weight_{var}', f'W_FS_{var}'])
        ordered_columns.extend(['Total_W_FS', 'Rank'])

        # Filter only existing columns just in case
        ordered_columns = [c for c in ordered_columns if c in df_ranking.columns]

        return df_ranking[ordered_columns]

    def _run_fs_selection(self, completeness_threshold=None):
        """
        Step 2: Selects top 5 candidate months based on FS statistic.
        """
        if completeness_threshold is None:
            completeness_threshold = self.missing_data_threshold

        print(f"Step 2: Calculating FS statistics using '{self.cdf_method}' method...")

        # Determine which dataframe to use for the analysis
        analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily
        if self.cdf_method == 'hourly':
            print("WARNING: This process is computationally intensive and may take a long time.")

        all_years = analysis_df.index.year.unique()
        candidate_months = {}
        self.fs_ranking_results = {}
        self.excluded_months = list(self.excluded_months_initial)  # Reset excluded months list with those from Step 1

        for month in range(1, 13):
            # Calculate full ranking details if requested for validation OR if we need them for selection
            # To optimize, we can generate the full table once per month.

            if self.save_validation_dfs:
                # Generate detailed table
                df_full_ranking = self._generate_ranking_table_for_month(month, analysis_df)
                self.validation_step2_fs_ranking_by_month[month] = df_full_ranking

                # Extract the simple list for candidate selection from this detailed table
                # Filter based on completeness if necessary?
                # _generate_ranking_table_for_month doesn't strictly enforce completeness check
                # which is done in the loop below.

                # Actually, to strictly follow the current logic where we skip insufficient data years:
                # Let's keep the existing loop for 'selection' to ensure consistency with completeness checks,
                # Unless we move completeness logic into the helper.
                pass

            monthly_results = []
            long_term_data_month = analysis_df[analysis_df.index.month == month]

            for year in all_years:
                candidate_data = long_term_data_month[long_term_data_month.index.year == year]
                if candidate_data.empty: continue

                # Check for completeness
                days_in_month = pd.Period(f'{year}-{month}-01').days_in_month
                expected_points = days_in_month * 24 if self.cdf_method == 'hourly' else days_in_month
                
                valid_cols = [col for col in self.weights.keys() if col in candidate_data.columns]
                if not valid_cols:
                    valid_cols = candidate_data.columns
                actual_points = candidate_data[valid_cols].notna().all(axis=1).sum()

                if actual_points / expected_points < completeness_threshold:
                    print(f"  Skipping {year}-{month:02d}: Insufficient data ({actual_points}/{expected_points} points)")
                    self.excluded_months.append((year, month))
                    continue

                # If we already calculated for validation, we could retrieve from there, but
                # for now let's just re-calc or rely on the loop for simplicity and robustness.
                w_fs = sum(weight * self._calculate_fs_statistic(candidate_data[var], long_term_data_month[var]) for var, weight in self.weights.items())
                monthly_results.append({'year': year, 'Total_W_FS': w_fs})

            top_5 = sorted(monthly_results, key=lambda x: x['Total_W_FS'])[:5]
            self.fs_ranking_results[month] = top_5
            candidate_months[month] = [res['year'] for res in top_5]
            print(f"  Month {month}: Selected candidates -> {candidate_months[month]}")

        self.candidate_months_pre_proximity = candidate_months

        if self.excluded_months:
            print("\n" + "="*50)
            print(f"WARNING: The following months were excluded due to missing data (Threshold: {completeness_threshold}):")
            for y, m in self.excluded_months:
                print(f"  - {y}-{m:02d}")
            print("="*50 + "\n")

        # Generate summary DF if requested
        if self.save_validation_dfs:
            self._generate_summary_fs_ranking()

    def _validate_proximity_normalization_method(self, normalization_method):
        """Validates and normalizes the proximity normalization method string."""
        if normalization_method is None:
            normalization_method = 'std'

        method = str(normalization_method).strip().lower()
        if method == 'sawaqed':
            warnings.warn("'sawaqed' is deprecated for proximity normalization. Use 'weighted' instead.", DeprecationWarning, stacklevel=3)
            method = 'weighted'

        valid_methods = {'std', 'long_term_mean', 'range', 'weighted', 'no_normalization'}
        if method not in valid_methods:
            raise ValueError(f"Invalid normalization_method '{normalization_method}'. Must be one of {sorted(valid_methods)}")
        return method

    def _resolve_proximity_weights(self, normalization_weights):
        """Returns validated proximity weights for the 'weighted' proximity method."""
        default_weights = {
            't_mean': 0.30,
            't_median': 0.20,
            'ghi_mean': 0.30,
            'ghi_median': 0.20
        }

        if normalization_weights is None:
            return default_weights

        expected_keys = set(default_weights.keys())
        provided_keys = set(normalization_weights.keys())

        missing_keys = expected_keys - provided_keys
        extra_keys = provided_keys - expected_keys
        if missing_keys or extra_keys:
            raise ValueError(
                "Invalid normalization_weights keys. "
                f"Expected exactly {sorted(expected_keys)}, got {sorted(provided_keys)}."
            )

        resolved = {k: float(v) for k, v in normalization_weights.items()}
        if any(v < 0 for v in resolved.values()):
            raise ValueError("All normalization_weights values must be >= 0.")

        total = sum(resolved.values())
        if not np.isclose(total, 1.0, atol=1e-9):
            raise ValueError(f"normalization_weights must sum to 1.0. Current sum is {total}.")

        return resolved

    def _safe_denominator(self, value):
        """Protects proximity normalization from zero/NaN denominators."""
        if pd.isna(value) or value == 0:
            return 1.0
        return float(value)

    def _run_proximity_ranking(self, normalization_method='std', normalization_weights=None):
        """
        Step 3: Proximity Ranking (Sawaqed et al. 2005)
        Re-orders the top 5 candidates based on the deviation of their monthly
        mean and median Temperature and GHI from the long-term history.
        """
        method = self._validate_proximity_normalization_method(normalization_method)
        weights = self._resolve_proximity_weights(normalization_weights) if method == 'weighted' else None

        print(f"Step 3: Applying Proximity Ranking to re-order top 5 candidates (method='{method}')...")
        if method == 'weighted':
            print(f"  Proximity weights: {weights}")
        
        # Calculate Long-Term Stats for all months first for efficiency
        # We need Mean and Median for T_air and GHI
        
        # Determine variable names in df_daily
        t_col = 'T_air' if 'T_air' in self.df_daily.columns else 'T_air_mean'
        ghi_col = 'GHI' if 'GHI' in self.df_daily.columns else 'GHI_sum'

        if t_col not in self.df_daily.columns or ghi_col not in self.df_daily.columns:
            print(f"  WARNING: Proximity ranking requires Temp and GHI. Found {self.df_daily.columns.tolist()}. Skipping re-ordering.")
            self.candidate_months = self.candidate_months_pre_proximity
            if self.save_validation_dfs:
                self.validation_step3_proximity_ranking = self.validation_step2_summary_fs_ranking
            return

        candidate_months = {}

        for month in range(1, 13):
            candidates = self.candidate_months_pre_proximity.get(month, [])
            if not candidates: continue
            
            # Long-term stats for the month (using all available years in df_daily)
            lt_data_month = self.df_daily[self.df_daily.index.month == month]
            
            lt_t_mean = lt_data_month[t_col].mean()
            lt_t_median = lt_data_month[t_col].median()
            lt_t_std = lt_data_month[t_col].std()

            lt_ghi_mean = lt_data_month[ghi_col].mean()
            lt_ghi_median = lt_data_month[ghi_col].median()
            lt_ghi_std = lt_data_month[ghi_col].std()
            lt_t_range = lt_data_month[t_col].max() - lt_data_month[t_col].min()
            lt_ghi_range = lt_data_month[ghi_col].max() - lt_data_month[ghi_col].min()

            if method == 'std' or method == 'weighted':
                den_t = self._safe_denominator(lt_t_std)
                den_ghi = self._safe_denominator(lt_ghi_std)
            elif method == 'long_term_mean':
                den_t = self._safe_denominator(abs(lt_t_mean))
                den_ghi = self._safe_denominator(abs(lt_ghi_mean))
            elif method == 'range':
                den_t = self._safe_denominator(lt_t_range)
                den_ghi = self._safe_denominator(lt_ghi_range)
            else:  # 'no_normalization'
                den_t = 1.0
                den_ghi = 1.0
            
            ranking_details = []
            
            for year in candidates:
                cand_data = lt_data_month[lt_data_month.index.year == year]
                
                if cand_data.empty: 
                    ranking_details.append({'Year': year, 'Max_Error': np.inf})
                    continue

                # Candidate stats
                c_t_mean = cand_data[t_col].mean()
                c_t_median = cand_data[t_col].median()
                c_ghi_mean = cand_data[ghi_col].mean()
                c_ghi_median = cand_data[ghi_col].median()
                
                # Deviations (Absolute Errors)
                err_t_mean = abs(c_t_mean - lt_t_mean)
                err_t_median = abs(c_t_median - lt_t_median)
                err_ghi_mean = abs(c_ghi_mean - lt_ghi_mean)
                err_ghi_median = abs(c_ghi_median - lt_ghi_median)

                # Normalized deviations according to the selected denominator method.
                n_err_t_mean = err_t_mean / den_t
                n_err_t_median = err_t_median / den_t
                n_err_ghi_mean = err_ghi_mean / den_ghi
                n_err_ghi_median = err_ghi_median / den_ghi

                if method == 'weighted':
                    weighted_score = (
                        weights['t_mean'] * n_err_t_mean +
                        weights['t_median'] * n_err_t_median +
                        weights['ghi_mean'] * n_err_ghi_mean +
                        weights['ghi_median'] * n_err_ghi_median
                    )
                    proximity_score = weighted_score
                else:
                    weighted_score = np.nan
                    proximity_score = max(n_err_t_mean, n_err_t_median, n_err_ghi_mean, n_err_ghi_median)
                
                ranking_details.append({
                    'Year': year,
                    'Max_Error': proximity_score,
                    'Proximity_Score': proximity_score,
                    'Proximity_Method': method,
                    'Den_T': den_t,
                    'Den_GHI': den_ghi,
                    'Weighted_Score': weighted_score,
                    'Raw_Err_T_Mean': err_t_mean,
                    'Raw_Err_T_Med': err_t_median,
                    'Raw_Err_GHI_Mean': err_ghi_mean,
                    'Raw_Err_GHI_Med': err_ghi_median,
                    'Norm_Err_T_Mean': n_err_t_mean,
                    'Norm_Err_T_Med': n_err_t_median,
                    'Norm_Err_GHI_Mean': n_err_ghi_mean,
                    'Norm_Err_GHI_Med': n_err_ghi_median
                })
            
            # Sort candidates by proximity score (ascending)
            # Rank 1 = Lowest Max Error
            sorted_details = sorted(ranking_details, key=lambda x: x['Max_Error'])
            
            # Update the candidate list for this month with the new order
            sorted_candidates = [item['Year'] for item in sorted_details]
            candidate_months[month] = sorted_candidates
            
            # Update fs_ranking_results to reflect new order and store ranking metric
            # We preserve the FS score but re-order the list
            current_fs_results = self.fs_ranking_results.get(month, [])
            new_fs_results = []
            for item in sorted_details:
                year = item['Year']
                # Find original FS data
                orig_data = next((x for x in current_fs_results if x['year'] == year), {'Total_W_FS': np.nan})
                new_entry = orig_data.copy()
                new_entry.update(item) # Add the error stats
                new_fs_results.append(new_entry)
            
            self.fs_ranking_results[month] = new_fs_results
            
            print(f"  Month {month}: Re-ordered by Proximity -> {sorted_candidates}")

        self.candidate_months = candidate_months

        if self.save_validation_dfs:
            self._generate_proximity_summary()

    def _generate_summary_fs_ranking(self):
        """Generates the summary dataframe of Top 5 candidates for all months."""
        all_months_data = []
        analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily

        for month in range(1, 13):
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            top_5_data = self.fs_ranking_results.get(month, [])

            # Retrieve detailed stats for these top 5
            # We can re-calculate or look up in validation_st2_df_fs_ranking_by_month if it exists

            long_term_data_month = analysis_df[analysis_df.index.month == month]

            for rank, item in enumerate(top_5_data):
                year = item['year']
                row = {'Month': month_name, 'Year': year, 'Total_W_FS': item['Total_W_FS'], 'Rank': rank + 1}

                candidate_data_year = long_term_data_month[long_term_data_month.index.year == year]
                for var, weight in self.weights.items():
                    fs_val = self._calculate_fs_statistic(candidate_data_year[var], long_term_data_month[var])
                    weighted_fs = fs_val * weight
                    row[f'FS_{var}'] = fs_val
                    row[f'Weight_{var}'] = weight
                    row[f'W_FS_{var}'] = weighted_fs

                all_months_data.append(row)

        ordered_columns = ['Month', 'Year']
        for var in self.weights.keys():
            ordered_columns.extend([f'FS_{var}', f'Weight_{var}', f'W_FS_{var}'])
        ordered_columns.extend(['Total_W_FS', 'Rank'])

        df_summary = pd.DataFrame(all_months_data)[ordered_columns].set_index(['Month', 'Year'])
        self.validation_step2_summary_fs_ranking = df_summary

    def _generate_proximity_summary(self):
        """Generates the summary dataframe of Top 5 candidates ordered by Proximity."""
        all_months_data = []
        for month in range(1, 13):
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            top_5_data = self.fs_ranking_results.get(month, [])
            for rank, item in enumerate(top_5_data):
                row = {
                    'Month': month_name, 
                    'Year': item['Year'], 
                    'Prox_Rank': rank + 1,
                    'Max_Error': item.get('Max_Error', np.nan),
                    'Proximity_Score': item.get('Proximity_Score', np.nan),
                    'Proximity_Method': item.get('Proximity_Method', np.nan),
                    'Den_T': item.get('Den_T', np.nan),
                    'Den_GHI': item.get('Den_GHI', np.nan),
                    'Weighted_Score': item.get('Weighted_Score', np.nan),
                    'Raw_Err_T_Mean': item.get('Raw_Err_T_Mean', np.nan),
                    'Raw_Err_T_Med': item.get('Raw_Err_T_Med', np.nan),
                    'Raw_Err_GHI_Mean': item.get('Raw_Err_GHI_Mean', np.nan),
                    'Raw_Err_GHI_Med': item.get('Raw_Err_GHI_Med', np.nan),
                    'Norm_Err_T_Mean': item.get('Norm_Err_T_Mean', np.nan),
                    'Norm_Err_T_Med': item.get('Norm_Err_T_Med', np.nan),
                    'Norm_Err_GHI_Mean': item.get('Norm_Err_GHI_Mean', np.nan),
                    'Norm_Err_GHI_Med': item.get('Norm_Err_GHI_Med', np.nan),
                    'Total_W_FS': item.get('Total_W_FS', np.nan)
                }
                all_months_data.append(row)
        
        if all_months_data:
            df_summary = pd.DataFrame(all_months_data).set_index(['Month', 'Year'])
            self.validation_step3_proximity_ranking = df_summary

    def _calculate_run_stats(self, series, upper_threshold, lower_threshold, min_run_length):
        """Calculates the frequency and maximum duration of persistence runs."""
        is_above = series > upper_threshold
        is_below = series < lower_threshold

        def get_run_info(condition_series):
            if not condition_series.any():
                return 0, 0
            groups = (condition_series != condition_series.shift()).cumsum()[condition_series]
            run_lengths = groups.value_counts()
            valid_run_lengths = run_lengths[run_lengths >= min_run_length]
            num_runs = len(valid_run_lengths)
            max_len = valid_run_lengths.max() if num_runs > 0 else 0
            return num_runs, int(max_len)

        above_freq, above_dur = get_run_info(is_above)
        below_freq, below_dur = get_run_info(is_below)
        total_freq = above_freq + below_freq
        max_dur = max(above_dur, below_dur)
        return total_freq, max_dur

    def _apply_persistence_scoring(self, persistence_weights):
        """Applies the persistence criteria using a scoring system."""
        print("\nApplying persistence criteria based on scoring...")
        selected_months = {}
        persistence_decisions_list = []
        if self.save_validation_dfs:
            self.validation_step4_persistence_score_details = {}
            self.validation_step4_persistence_sequential_details = None

        for month in range(1, 13):
            candidates = self.candidate_months.get(month, [])
            if not candidates: continue

            long_term_month_data = self.df_daily[self.df_daily.index.month == month]
            if long_term_month_data.empty: continue

            lower_p, upper_p = self.persistence_thresholds

            # Helper to get column
            t_col = 'T_air' if 'T_air' in long_term_month_data.columns else 'T_air_mean'
            ghi_col = 'GHI' if 'GHI' in long_term_month_data.columns else 'GHI_sum'

            if t_col not in long_term_month_data.columns or ghi_col not in long_term_month_data.columns:
                print(f"  Warning: Persistence analysis requires Temp and GHI. Found {long_term_month_data.columns.tolist()[:5]}... Skipping.")
                continue

            t_air_upper, t_air_lower = long_term_month_data[t_col].quantile([upper_p, lower_p])
            ghi_lower = long_term_month_data[ghi_col].quantile(lower_p)

            candidate_scores = []
            for year in candidates:
                candidate_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
                if candidate_data.empty: continue

                fs_stats = next((item for item in self.fs_ranking_results.get(month, []) if item['year'] == year), None)
                if not fs_stats: continue
                total_w_fs = fs_stats['Total_W_FS']

                t_air_freq, t_air_dur = self._calculate_run_stats(candidate_data[t_col], t_air_upper, t_air_lower, self.min_run_length)
                ghi_freq, ghi_dur = self._calculate_run_stats(candidate_data[ghi_col], np.inf, ghi_lower, self.min_run_length)

                w_t_dur = persistence_weights['w_t_longest_run']
                w_t_freq = persistence_weights['w_t_total_runs']
                w_ghi_dur = persistence_weights['w_ghi_longest_run']
                w_ghi_freq = persistence_weights['w_ghi_total_runs']

                prod_t_dur = w_t_dur * t_air_dur
                prod_t_freq = w_t_freq * t_air_freq
                prod_ghi_dur = w_ghi_dur * ghi_dur
                prod_ghi_freq = w_ghi_freq * ghi_freq

                score = total_w_fs + prod_t_dur + prod_t_freq + prod_ghi_dur + prod_ghi_freq

                candidate_scores.append({
                    'Year': year, 
                    'WT_FS': total_w_fs,
                    'T_Max_Len': t_air_dur, 'W_T_Max_Len': w_t_dur, 'Prod_T_Max_Len': prod_t_dur,
                    'T_TotalRuns': t_air_freq, 'W_T_TotalRuns': w_t_freq, 'Prod_T_TotalRuns': prod_t_freq,
                    'GHI_Max_Len': ghi_dur, 'W_GHI_Max_Len': w_ghi_dur, 'Prod_GHI_Max_Len': prod_ghi_dur,
                    'GHI_TotalRuns': ghi_freq, 'W_GHI_TotalRuns': w_ghi_freq, 'Prod_GHI_TotalRuns': prod_ghi_freq,
                    'Score': score
                })

            if not candidate_scores: continue

            df_decision = pd.DataFrame(candidate_scores).sort_values('Score').reset_index(drop=True)
            df_decision['Rank'] = df_decision.index + 1
            df_decision['Year'] = df_decision['Year'].astype(int)

            if self.save_validation_dfs:
                self.validation_step4_persistence_score_details[month] = df_decision.copy()
                
                # Also populate the old fallback for backward compatibility if needed, 
                # but adding 'Month' column as expected by validate_persistence_selection fallback
                df_for_concat = df_decision.copy()
                df_for_concat.insert(0, 'Month', month)
                persistence_decisions_list.append(df_for_concat)

            best_choice = df_decision.iloc[0]['Year'].astype(int)
            selected_months[month] = best_choice
            print(f"  Month {month}: Selected Year -> {int(best_choice)} (Score: {df_decision.iloc[0]['Score']:.4f})")

        if self.save_validation_dfs and persistence_decisions_list:
            self.validation_step4_df_persistence_decision = pd.concat(persistence_decisions_list, ignore_index=True)

        self.selected_months = selected_months

    def _apply_persistence_sequential_exclusion(self, zero_run_method='eliminate_worst_ranked'):
        """
        Applies the persistence criteria using the sequential iterative exclusion method.
        
        Args:
             zero_run_method (str): Methodology for handling candidates with zero runs in Pass 3.
                 Options: 'eliminate_worst_ranked' (default), 'eliminate_all', 'eliminate_none'.
        
        PERSISTENCE PROCESS (Step 4 & 5 - Sequential Exclusion):
        ========================================================
        
        Start from the 5 candidate years already ranked by Proximity in Step 3.
        
        STEP 4: COMPUTE PERSISTENCE INDICATORS & FILTER
        -----------------------------------------------
        For mean dry-bulb temperature:
            - consecutive days above the 67th percentile (warm runs)
            - consecutive days below the 33rd percentile (cool runs)
        For GHI:
            - consecutive days below the 33rd percentile (low-radiation runs)
        
        For each candidate month, calculate:
            - Number of runs (frequency)
            - Longest run length
        
        EXCLUSION CRITERIA (Step 4 continued):
        --------------------------------------
        The exclusion criteria are applied sequentially in a single pass (Pass 1, 2, 3).
        
        PASS 1: NUMBER OF RUNS CRITERION
           a. If all months have no runs → select the first month in ranking list
           b. If all months have equal number of runs → check length of runs:
              i.  If unequal run lengths → exclude the one with the longest run
              ii. If equal run lengths → exclude the last one in the list
           c. If number of runs are not equal:
              - Exclude the one with largest number of runs
              - Modified rule: eliminate only if it has more runs than all others
              - If tie for max runs → eliminate the worst-ranked among them
        
        PASS 2: RUNS LENGTH CRITERION (if Pass 1 survivors > 1)
           a. If unequal run length → exclude the longest run month
           b. If equal run length → check number of runs:
              i.  If equal number of runs → exclude the last one in the list
              ii. If not equal → exclude the one with the largest number of runs
        
        PASS 3: ZERO-RUN CRITERION (if Pass 2 survivors > 1)
           Inspect remaining months for number of runs.
           Behavior depends on `zero_run_method`:
           - 'eliminate_worst_ranked': Exclude ONE candidate (the one with worst Proximity Rank).
           - 'eliminate_all': Exclude ALL candidates with zero runs.
           - 'eliminate_none': Do nothing.
        
        STEP 5: FINAL SELECTION
        -----------------------
        Select the highest Proximity-ranked candidate among survivors.
        """
        print("\nApplying persistence criteria (Step 4) and Final Selection (Step 5)...")
        selected_months = {}
        if self.save_validation_dfs:
            self.validation_step4_persistence_sequential_details = {}
            self.validation_step4_persistence_score_details = None
            self.validation_step4_df_persistence_decision = None 

        for month in range(1, 13):
            candidates_years = self.candidate_months.get(month, [])
            if not candidates_years: continue

            # candidates_years is already sorted by FS (best first) - this is our starting point
            month_decisions = {y: "" for y in candidates_years}
            month_stats_list = []
            
            long_term_month_data = self.df_daily[self.df_daily.index.month == month]
            if long_term_month_data.empty: continue

            # ═══════════════════════════════════════════════════════════════════
            # STEP 4 (Part A): COMPUTE PERSISTENCE INDICATORS
            # ═══════════════════════════════════════════════════════════════════
            
            # Define thresholds for runs
            lower_p, upper_p = self.persistence_thresholds  # Default: 33rd and 67th percentiles
            
            t_col = 'T_air' if 'T_air' in long_term_month_data.columns else 'T_air_mean'
            ghi_col = 'GHI' if 'GHI' in long_term_month_data.columns else 'GHI_sum'

            if t_col not in long_term_month_data.columns or ghi_col not in long_term_month_data.columns:
                 print(f"  Warning: Persistence analysis requires Temp and GHI. Skipping Month {month}.")
                 selected_months[month] = candidates_years[0]
                 continue
            
            # Calculate quantiles for the entire long-term month data
            # For dry-bulb temperature: 67th percentile (warm runs) and 33rd percentile (cool runs)
            t_air_upper = long_term_month_data[t_col].quantile(upper_p)  # 67th percentile
            t_air_lower = long_term_month_data[t_col].quantile(lower_p)  # 33rd percentile
            # For GHI: 33rd percentile (low-radiation runs)
            ghi_lower = long_term_month_data[ghi_col].quantile(lower_p)  # 33rd percentile

            # Build initial persistence statistics for all candidates
            # For each candidate month, calculate:
            #   - Number of runs (frequency)
            #   - Longest run length
            month_stats_list = []
            for rank, year in enumerate(candidates_years):
                candidate_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
                if candidate_data.empty: continue
                
                # Temperature runs: consecutive days above 67th OR below 33rd percentile
                t_freq, t_dur = self._calculate_run_stats(candidate_data[t_col], t_air_upper, t_air_lower, self.min_run_length)
                # GHI runs: consecutive days below 33rd percentile
                ghi_freq, ghi_dur = self._calculate_run_stats(candidate_data[ghi_col], np.inf, ghi_lower, self.min_run_length)
                
                # Aggregate metrics
                total_runs = t_freq + ghi_freq        # Total number of runs
                max_run_len = max(t_dur, ghi_dur)     # Longest run length
                
                # Get FS value for reference
                fs_val_ranking = next((item for item in self.fs_ranking_results.get(month, []) if item['year'] == year), None)
                fs_val = fs_val_ranking['Total_W_FS'] if fs_val_ranking else np.nan

                month_stats_list.append({
                    'Year': year,
                    'Original_Rank': rank,  # 0 = best FS rank
                    'Total_Runs': total_runs,
                    'Max_Run_Len': max_run_len,
                    'FS': fs_val
                })


            
            # ═══════════════════════════════════════════════════════════════════
            # STEP 4 (Part B): SINGLE-PASS SEQUENTIAL EXCLUSION
            # ═══════════════════════════════════════════════════════════════════
            
            survivors = month_stats_list.copy()
            month_decisions = {s['Year']: "" for s in survivors}
            
            # Helper to find candidate with worst Proximity Rank among a list
            def get_worst_ranked(cands):
                return sorted(cands, key=lambda x: x['Original_Rank'])[-1]

            # ───────────────────────────────────────────────────────────────
            # PASS 1: NUMBER OF RUNS CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic:
            # Rule 1a: If all candidates have 0 runs -> Select Rank 1 immediately.
            # Rule 1b: If all candidates have EQUAL runs -> Check run lengths.
            #    Rule 1b.i: Unequal run lengths -> Exclude Longest Run.
            #    Rule 1b.ii: Equal run lengths -> Exclude Last in List (Worst Rank).
            # Rule 1c: Unequal runs -> Exclude Max Runs.
            
            runs_values = [s['Total_Runs'] for s in survivors]
            max_runs = max(runs_values)
            min_runs = min(runs_values)
            
            excluded_p1 = None
            
            if max_runs == 0:
                # Rule 1a: Immediate selection
                top_cand = sorted(survivors, key=lambda x: x['Original_Rank'])[0]
                month_decisions[top_cand['Year']] = "SELECTED (Rule 1a: No runs)"
                selected_months[month] = top_cand['Year']
                
                # Save details and continue to next month
                if self.save_validation_dfs:
                    self._save_persistence_details(month, month_stats_list, month_decisions)
                continue
                
            elif max_runs == min_runs:
                # Rule 1b: Equal runs
                max_lens = [s['Max_Run_Len'] for s in survivors]
                if max(max_lens) != min(max_lens):
                    # Rule 1b.i: Unequal lengths -> Exclude longest run
                    # Tie-breaker for longest run: Worst Rank (implied/common sense)
                    target_len = max(max_lens)
                    cands_target = [s for s in survivors if s['Max_Run_Len'] == target_len]
                    to_exclude = get_worst_ranked(cands_target)
                    excluded_p1 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1b.i: Longest Run)"
                else:
                    # Rule 1b.ii: Equal lengths -> Exclude last in list
                    to_exclude = get_worst_ranked(survivors)
                    excluded_p1 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1b.ii: Last in list)"
            else:
                # Rule 1c: Unequal runs -> Exclude Max Runs
                # Tie-breaker for max runs: Worst Rank
                cands_target = [s for s in survivors if s['Total_Runs'] == max_runs]
                to_exclude = get_worst_ranked(cands_target)
                excluded_p1 = to_exclude
                month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1c: Max Runs)"

            if excluded_p1:
                survivors = [s for s in survivors if s['Year'] != excluded_p1['Year']]

            # ───────────────────────────────────────────────────────────────
            # PASS 2: LONGEST RUN LENGTH CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic:
            # Rule 2a: Unequal run lengths -> Exclude Longest Run Month.
            # Rule 2b: Equal run lengths -> Check number of runs.
            #    Rule 2b.i: Equal number of runs -> Exclude Last in List.
            #    Rule 2b.ii: Unequal number of runs -> Exclude Max Runs.

            excluded_p2 = None
            lens = [s['Max_Run_Len'] for s in survivors]
            if not lens: pass # Safety
            else:
                max_len = max(lens)
                min_len = min(lens)
                
                if max_len != min_len:
                    # Rule 2a: Unequal run lengths -> Exclude longest run
                    # Tie-breaker: Max Runs (from user prompt) then Worst Rank
                    cands_target = [s for s in survivors if s['Max_Run_Len'] == max_len]
                    # Sort primarily by Runs (desc), then by Rank (desc)
                    to_exclude = sorted(cands_target, key=lambda x: (x['Total_Runs'], x['Original_Rank']))[-1]
                    excluded_p2 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2a: Longest Run)"
                else:
                    # Rule 2b: Equal run lengths
                    runs = [s['Total_Runs'] for s in survivors]
                    if max(runs) == min(runs):
                         # Rule 2b.i: Equal runs -> Exclude Last in List
                         to_exclude = get_worst_ranked(survivors)
                         excluded_p2 = to_exclude
                         month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2b.i: Equal runs, last in list)"
                    else:
                         # Rule 2b.ii: Unequal runs -> Exclude Max Runs
                         target_runs = max(runs)
                         cands_target = [s for s in survivors if s['Total_Runs'] == target_runs]
                         to_exclude = get_worst_ranked(cands_target)
                         excluded_p2 = to_exclude
                         month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2b.ii: Max Runs)"

            if excluded_p2:
                survivors = [s for s in survivors if s['Year'] != excluded_p2['Year']]

            # ───────────────────────────────────────────────────────────────
            # PASS 3: ZERO-RUN CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic: If exists, eliminate based on `zero_run_method`.
            
            zero_run_cands = [s for s in survivors if s['Total_Runs'] == 0]
            
            if zero_run_cands:
                if zero_run_method == 'eliminate_none':
                    pass # Do nothing
                
                elif zero_run_method == 'eliminate_all':
                     # Eliminate ALL candidates with zero runs
                     for cand in zero_run_cands:
                         month_decisions[cand['Year']] = "Excluded Pass 3 (Zero Run - All)"
                     
                     survivors = [s for s in survivors if s['Total_Runs'] > 0]
                     
                else: # 'eliminate_worst_ranked' (Default)
                    # Eliminate ONLY the worst-ranked candidate with 0 runs
                    to_exclude = get_worst_ranked(zero_run_cands)
                    month_decisions[to_exclude['Year']] = "Excluded Pass 3 (Zero Run - Worst Ranked)"
                    survivors = [s for s in survivors if s['Year'] != to_exclude['Year']]
            
            # ═══════════════════════════════════════════════════════════════════
            # STEP 5: FINAL SELECTION
            # ═══════════════════════════════════════════════════════════════════
            # Select the highest Proximity-ranked candidate among survivors (lowest Original_Rank index)
            
            if survivors:
                survivors.sort(key=lambda x: x['Original_Rank'])
                best_choice = survivors[0]['Year']
                selected_months[month] = best_choice
                month_decisions[best_choice] = "SELECTED TMY MONTH"
            else:
                # Fallback (should not happen with 5 candidates and 3 passes)
                print(f"  Warning: All candidates excluded for Month {month}. Selecting best Proximity Rank.")
                best_choice = candidates_years[0]
                selected_months[month] = best_choice
            
            if self.save_validation_dfs:
                self._save_persistence_details(month, month_stats_list, month_decisions)

        self.selected_months = selected_months

    def _save_persistence_details(self, month, stats_list, decisions):
        """Helper to save persistence details dataframe."""
        month_details = []
        for stat in stats_list:
            month_details.append({
                'Prox_Rank': stat['Original_Rank'] + 1,
                'Year': stat['Year'],
                'FS_Score': stat['FS'],
                'NumRuns': stat['Total_Runs'],
                'Max_run': stat['Max_Run_Len'],
                'Decision': decisions.get(stat['Year'], "")
            })
        df = pd.DataFrame(month_details).sort_values('Prox_Rank')
        self.validation_step4_persistence_sequential_details[month] = df



    def _select_months_by_fs_rank(self):
        """Selects months based purely on FS/Proximity rank, skipping persistence filtering (Step 4 & 5)."""
        print("\nSkipping persistence filtering. Selecting the best candidate by rank.")
        if self.candidate_months is None: raise RuntimeError("Run step_2_select_candidate_months() first.")
        self.selected_months = {month: candidates[0] for month, candidates in self.candidate_months.items() if candidates}

    def _create_raw_tmy(self):
        """
        Step 6: Assembles the raw TMY by concatenating the selected months.
        """
        print("\nStep 6: Creating raw (un-smoothed) TMY...")
        TMY_YEAR = 2000
        tmy_pieces = []
        for month in range(1, 13):
            year = int(self.selected_months[month])

            start_date = f"{year}-{month:02d}-01"
            end_date = pd.Timestamp(start_date) + pd.offsets.MonthEnd(0)

            if self.df_hourly is not None:
                monthly_data = self.df_hourly.loc[start_date:f"{end_date.date()} 23:00:00"].copy()
            else:
                monthly_data = self.df_daily.loc[start_date:f"{end_date.date()}"].copy()

            if month == 2 and len(monthly_data) > 28 * 24:
                print(f"  Leap year adjustment: Removing Feb 29th from year {year}.")
                monthly_data = monthly_data[monthly_data.index.day != 29]

            monthly_data.index = monthly_data.index.map(lambda t: t.replace(year=TMY_YEAR))
            tmy_pieces.append(monthly_data)

        self.tmy_raw = pd.concat(tmy_pieces)
        if not self.tmy_raw.index.is_unique:
            self.tmy_raw = self.tmy_raw[~self.tmy_raw.index.duplicated()]

    def _apply_smoothing(self, smoothing_config=None, hours=6, s_factor=0.0):
        """
        Applies a sophisticated smoothing spline at the month junctions, with
        configurable and potentially asymmetric parameters for each junction.
        
        Args:
            smoothing_config (dict): Per-junction configuration.
            hours (int): Global default hours before/after (used if not in config).
            s_factor (float): Global default smoothing factor (used if not in config).
        """

        # Check if hourly data is available for smoothing
        if self.df_hourly is None:
            print("Smoothing requires hourly data. Skipping smoothing.")
            print("  Tip: Provide hourly_file_path parameter to enable smoothing with daily data analysis.")
            self.tmy_final = self.tmy_raw.copy()
            return

        print("Applying sophisticated smoothing at month junctions...")

        self.smoothing_config = smoothing_config or {}

        default_params = {'hours_before': hours, 'hours_after': hours, 's_factor': s_factor}

        tmy_final = self.tmy_raw.copy()

        for i in range(11):
            month1 = i + 1
            month2 = i + 2

            junction_params = self.smoothing_config.get(month1, {}).copy()

            hours = junction_params.get('hours', None)
            hours_before = junction_params.get('hours_before', hours or default_params['hours_before'])
            hours_after = junction_params.get('hours_after', hours or default_params['hours_after'])
            s_factor = junction_params.get('s_factor', default_params['s_factor'])

            print(f"  - Junction {month1}->{month2}: hours_before={hours_before}, hours_after={hours_after}, s_factor={s_factor}")

            year1 = self.selected_months[month1]
            year2 = self.selected_months[month2]

            month1_data_full = self.df_hourly[
                (self.df_hourly.index.month == month1) & (self.df_hourly.index.year == year1)
                ].copy()
            if month1 == 2 and len(month1_data_full) > 28 * 24:
                month1_data_full = month1_data_full[month1_data_full.index.day != 29]
                
            month2_data_full = self.df_hourly[
                (self.df_hourly.index.month == month2) & (self.df_hourly.index.year == year2)
                ].copy()
            if month2 == 2 and len(month2_data_full) > 28 * 24:
                month2_data_full = month2_data_full[month2_data_full.index.day != 29]

            fitting_data = pd.concat([month1_data_full, month2_data_full])
            x_fit = np.arange(len(fitting_data))

            junction_point = self.tmy_raw[self.tmy_raw.index.month == month1].index[-1]

            start_apply_window = junction_point - pd.Timedelta(hours=hours_before - 1)
            end_apply_window = junction_point + pd.Timedelta(hours=hours_after)

            application_window_range = pd.date_range(start=start_apply_window, end=end_apply_window, freq='h')
            application_window_timestamps = tmy_final.index.intersection(application_window_range)

            junction_index_in_fit = len(month1_data_full)

            num_hours_before = len(application_window_timestamps[application_window_timestamps <= junction_point])
            num_hours_after = len(application_window_timestamps[application_window_timestamps > junction_point])

            x_apply = np.arange(
                junction_index_in_fit - num_hours_before,
                junction_index_in_fit + num_hours_after
            )

            for col in tmy_final.columns:
                if col in ['GHI', 'DNI']:
                    continue

                y_fit = fitting_data[col].values

                if np.var(y_fit) == 0:
                    continue

                try:
                    # Fit the spline
                    spl = UnivariateSpline(x_fit, y_fit, s=s_factor)
                except Exception as e:
                    print(f"  - Warning: Could not fit spline for {col} at month {month1}-{month2} junction. Skipping. Error: {e}")
                    continue

                # --- CORRECCIÓN v4.08: Obtener el valor de 's' y aplicar el suavizado ---
                # Si s es automático, capturar el valor calculado
                if s_factor is None:
                    s_val_auto = spl.get_residual()
                    if 's_factor_auto' not in junction_params:
                        junction_params['s_factor_auto'] = {}
                    junction_params['s_factor_auto'][col] = s_val_auto

                # Aplicar el suavizado
                smoothed_y = spl(x_apply)

                tmy_final.loc[application_window_timestamps, col] = smoothed_y

            # Actualizar la configuración guardada con los valores automáticos de 's'
            self.smoothing_config[month1] = junction_params

        # --- FIX: Final Safety Clip after smoothing ---
        # Spline smoothing can introduce negative values (undershoot) near zero.
        for col in tmy_final.columns:
            if col in ['GHI', 'DNI', 'Wind_speed']:
                neg_count = (tmy_final[col] < 0).sum()
                if neg_count > 0:
                   print(f"  - Fixed {neg_count} negative values in '{col}' caused by smoothing undershoot.")
                   tmy_final[col] = tmy_final[col].clip(lower=0)


        self.tmy_final = tmy_final
        print("Final TMY generated and smoothed.")

    def _plot_single_persistence_subplot(self, ax, year_data, t_thresholds, ghi_threshold, title_info, t_col='T_air', ghi_col='GHI'):
        """Helper function to plot persistence data for a single year on a subplot."""
        t_upper, t_lower = t_thresholds
        lower_p, upper_p = self.persistence_thresholds

        ax.plot(year_data.index.day, year_data[t_col], marker='o', linestyle='-', color='royalblue', markersize=4, label=t_col)
        ax.axhline(t_upper, color='darkred', linestyle='--', label=f'{t_col} P{int(upper_p * 100)} ({t_upper:.1f})')
        ax.axhline(t_lower, color='darkblue', linestyle='--', label=f'{t_col} P{int(lower_p * 100)} ({t_lower:.1f})')
        ax.set_ylabel(f'Daily Mean {t_col}', color='royalblue')
        ax.tick_params(axis='y', labelcolor='royalblue')

        is_hot_run, is_cold_run = pd.Series(False, index=year_data.index), pd.Series(False, index=year_data.index)
        # Fix condition logic for dynamic column
        for condition, run_mask in [(year_data[t_col] > t_upper, is_hot_run), (year_data[t_col] < t_lower, is_cold_run)]:
            groups = (condition != condition.shift()).cumsum()
            for _, group in year_data[condition].groupby(groups):
                if len(group) >= self.min_run_length:
                    run_mask.loc[group.index] = True

        ax.fill_between(year_data.index.day, t_upper, year_data[t_col], where=is_hot_run, color='red', alpha=0.3, interpolate=True)
        ax.fill_between(year_data.index.day, year_data[t_col], t_lower, where=is_cold_run, color='blue', alpha=0.3, interpolate=True)

        ax2 = ax.twinx()
        ax2.plot(year_data.index.day, year_data[ghi_col], marker='.', linestyle=':', color='darkorange', markersize=4, label=ghi_col)
        ax2.axhline(ghi_threshold, color='orange', linestyle='--', label=f'{ghi_col} P{int(lower_p * 100)} ({ghi_threshold:.0f})')
        ax2.set_ylabel(f'Daily Sum {ghi_col} (Wh/m²)', color='darkorange')
        ax2.tick_params(axis='y', labelcolor='darkorange')

        is_low_ghi = pd.Series(False, index=year_data.index)
        condition = year_data[ghi_col] < ghi_threshold
        groups = (condition != condition.shift()).cumsum()
        for _, group in year_data[condition].groupby(groups):
            if len(group) >= self.min_run_length:
                is_low_ghi.loc[group.index] = True

        ax2.fill_between(year_data.index.day, year_data[ghi_col], ghi_threshold, where=is_low_ghi, color='orange', alpha=0.3, interpolate=True)

        ax.set_title(title_info, fontsize=12)
        ax.grid(True, linestyle=':')
        lines, labels = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines + lines2, labels + labels2, loc='best')

    # --- PUBLIC WORKFLOWS ---

    def sandia_step_1_load_and_prepare(self):
        """
        **Step 1** of the Sandia TMY workflow: load the source file(s),
        apply the column mapping, convert the index to a UTC ``DatetimeIndex``,
        filter by :attr:`years_to_include` if given, resample to hourly
        frequency if ``data_frequency='hourly'`` (clipping negative
        GHI/DNI/Wind_speed to 0), and compute the daily aggregates required
        by :attr:`weighting_method`. Populates :attr:`df_hourly` and/or
        :attr:`df_daily`. Requires a minimum of 5 years of data.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            ValueError: If essential columns are missing after mapping, or
                if fewer than 5 years of data remain after filtering.

        Example:
            >>> gen = tmy.TMYGenerator(file_path="weather_data.csv")  # doctest: +SKIP
            >>> gen.sandia_step_1_load_and_prepare()  # doctest: +SKIP
        """
        self._load_and_prepare_real_data()

        if self.data_frequency == 'daily':
            if len(self.df_daily.index.year.unique()) < 5:
                raise ValueError("The filtered dataset contains fewer than 5 years of data.")
        return self

    def step_1_load_and_prepare_data(self):
        """[DEPRECATED] Use sandia_step_1_load_and_prepare() instead."""
        warnings.warn("step_1_load_and_prepare_data() is deprecated. Use sandia_step_1_load_and_prepare() instead.", DeprecationWarning, stacklevel=2)
        return self.sandia_step_1_load_and_prepare()

    def sandia_step_2_select_candidates_fs(self, completeness_threshold=None):
        """
        **Step 2** of the Sandia TMY workflow: for each calendar month,
        compute the Finkelstein-Schafer (FS) statistic between every
        available year's empirical CDF and the long-term CDF (see
        :meth:`_calculate_fs_statistic`), excluding candidate months whose
        data completeness falls below *completeness_threshold*, and keep
        the 5 years with the lowest weighted-FS score. Populates
        :attr:`candidate_months_pre_proximity` and :attr:`fs_ranking_results`.

        Args:
            completeness_threshold (float, optional): Overrides
                :attr:`missing_data_threshold` for this call.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_1_load_and_prepare` has not
                been run yet.

        Example:
            >>> gen.sandia_step_1_load_and_prepare()  # doctest: +SKIP
            >>> gen.sandia_step_2_select_candidates_fs()  # doctest: +SKIP
        """
        if self.df_hourly is None and self.df_daily is None: raise RuntimeError("Run sandia_step_1_load_and_prepare() first.")
        self._run_fs_selection(completeness_threshold=completeness_threshold)
        return self

    def sandia_step_3_proximity_ranking(self, normalization_method='std', normalization_weights=None):
        """
        **Step 3** of the Sandia TMY workflow (Sawaqed, Zurigat & Al-Hinai,
        2005): re-orders the 5 FS candidates from Step 2 by how close their
        monthly mean/median temperature and GHI are to the long-term
        statistics, using a normalised, configurable proximity score (see
        the module-level formulas in the package README, section 3.4).
        Populates :attr:`candidate_months` with the re-ordered candidate
        lists (ascending by proximity score, best first).

        Args:
            normalization_method (str): One of 'std' (default), 'long_term_mean',
                'range', 'weighted', or 'no_normalization'. The deprecated
                alias ``'sawaqed'`` is still accepted and mapped internally
                to ``'weighted'`` (emits a ``DeprecationWarning``).
            normalization_weights (dict, optional): Used only when
                normalization_method='weighted'. Expected keys:
                't_mean', 't_median', 'ghi_mean', 'ghi_median'.
                Values must be non-negative and sum to 1.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_2_select_candidates_fs` has
                not been run yet.
            ValueError: If *normalization_method* is invalid, or if
                *normalization_weights* has invalid keys/values.

        Example:
            >>> gen.sandia_step_2_select_candidates_fs()  # doctest: +SKIP
            >>> gen.sandia_step_3_proximity_ranking(normalization_method="std")  # doctest: +SKIP
        """
        if self.candidate_months_pre_proximity is None: raise RuntimeError("Run sandia_step_2_select_candidates_fs() first.")
        self._run_proximity_ranking(
            normalization_method=normalization_method,
            normalization_weights=normalization_weights
        )
        return self

    def step_2_select_candidate_months(self, completeness_threshold=None):
        """[DEPRECATED] Use sandia_step_2 and sandia_step_3 instead."""
        warnings.warn("step_2_select_candidate_months() is deprecated. Use sandia_step_2_select_candidates_fs() and sandia_step_3_proximity_ranking() instead.", DeprecationWarning, stacklevel=2)
        self.sandia_step_2_select_candidates_fs(completeness_threshold=completeness_threshold)
        self.sandia_step_3_proximity_ranking()
        return self

    def sandia_step_4_and_5_apply_persistence(self, thresholds=(0.33, 0.67), min_run_length=1, persistence_weights=None, persistence_method='score', zero_run_method='eliminate_worst_ranked'):
        """
        Step 4 & 5: Apply persistence criteria and Select Final Month.

        Args:
            thresholds (tuple): Lower and upper percentile thresholds to define runs.
            min_run_length (int): The minimum number of days for a period to be
                considered a persistence run.
            persistence_weights (dict, optional): A dictionary to customize the
                weights for persistence penalties (only for 'score' method).
            persistence_method (str): Method to use. 'score' (default) or 'sequential'.
            zero_run_method (str): Method for handling zero-run candidates (only for 'sequential').
                Options: 'eliminate_worst_ranked' (default), 'eliminate_all', 'eliminate_none'.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_3_proximity_ranking` has not
                been run yet.

        Example:
            >>> gen.sandia_step_3_proximity_ranking()  # doctest: +SKIP
            >>> gen.sandia_step_4_and_5_apply_persistence(persistence_method="sequential")  # doctest: +SKIP
        """
        if self.candidate_months is None: raise RuntimeError("Run sandia_step_3_proximity_ranking() first.")
        self.persistence_thresholds = thresholds
        self.min_run_length = min_run_length

        if persistence_method == 'sequential':
            self._apply_persistence_sequential_exclusion(zero_run_method=zero_run_method)
        else:
            # Default Score Method
            default_weights = {
                'w_t_longest_run': 0.002, 'w_t_total_runs': 0.001,
                'w_ghi_longest_run': 0.001, 'w_ghi_total_runs': 0.0005
            }

            final_weights = default_weights.copy()
            if persistence_weights:
                user_keys = set(persistence_weights.keys())
                valid_keys = set(final_weights.keys())
                invalid_keys = user_keys - valid_keys

                if invalid_keys:
                    print(f"\nWARNING: Found invalid keys in `persistence_weights`: {sorted(list(invalid_keys))}.")
                    print(f"These keys will be ignored. Valid keys are: {sorted(list(valid_keys))}")

                valid_user_weights = {k: v for k, v in persistence_weights.items() if k in valid_keys}
                final_weights.update(valid_user_weights)

            print("\nPersistence weights being used for the Score calculation:")
            print(final_weights)

            self._apply_persistence_scoring(final_weights)
        
        if self.save_validation_dfs:
            self._generate_selected_months_summary()
            
        return self

    def step_3_apply_persistence(self, thresholds=(0.33, 0.67), min_run_length=1, persistence_weights=None, persistence_method='score', zero_run_method='eliminate_worst_ranked'):
        """[DEPRECATED] Use sandia_step_4_and_5_apply_persistence() instead."""
        warnings.warn("step_3_apply_persistence() is deprecated. Use sandia_step_4_and_5_apply_persistence() instead.", DeprecationWarning, stacklevel=2)
        return self.sandia_step_4_and_5_apply_persistence(thresholds, min_run_length, persistence_weights, persistence_method, zero_run_method)

    def _generate_selected_months_summary(self):
        """Generates a simple dataframe showing the finally selected year for each month."""
        if self.selected_months is None: return
        df = pd.DataFrame(list(self.selected_months.items()), columns=['Month', 'Selected_Year'])
        self.validation_step5_selected_months_summary = df

    def _generate_tmy_composition_dataframe(self):
        """Generates a detailed TMY composition dataframe merging FS and Persistence stats."""
        if self.selected_months is None: return None
        
        composition_rows = []
        for month in range(1, 13):
            if month not in self.selected_months: continue
            selected_year = int(self.selected_months[month])
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            
            row_data = {'Month': month_name, 'Month_Num': month, 'Source_Year': selected_year}
            
            # 1. Merge FS details (from validation_st2)
            if self.validation_step3_proximity_ranking is not None and not self.validation_step3_proximity_ranking.empty:
                try:
                    if (month_name, selected_year) in self.validation_step3_proximity_ranking.index:
                        fs_row = self.validation_step3_proximity_ranking.loc[(month_name, selected_year)]
                        if isinstance(fs_row, pd.DataFrame): fs_row = fs_row.iloc[0]
                        fs_dict = fs_row.to_dict()
                        fs_dict.pop('Month', None)
                        fs_dict.pop('Year', None)
                        row_data.update(fs_dict)
                except Exception:
                    pass
            
            # 2. Merge Persistence details (from validation_st3)
            if self.validation_step4_df_persistence_decision is not None:
                df_pers = self.validation_step4_df_persistence_decision
                if isinstance(df_pers, pd.DataFrame) and not df_pers.empty:
                     pers_row = df_pers[
                        (df_pers['Month'] == month) & 
                        (df_pers['Year'] == selected_year)
                     ]
                     if not pers_row.empty:
                         pers_data = pers_row.iloc[0].to_dict()
                         pers_data.pop('Month', None)
                         pers_data.pop('Year', None)
                         if 'Rank' in pers_data: pers_data['Persistence_Rank'] = pers_data.pop('Rank')
                         if 'Total_W_FS' in pers_data: pers_data.pop('Total_W_FS')
                         row_data.update(pers_data)
            
            composition_rows.append(row_data)

        if not composition_rows: return None
        df_comp = pd.DataFrame(composition_rows)
        basic_cols = ['Month_Num', 'Month', 'Source_Year']
        other_cols = [c for c in df_comp.columns if c not in basic_cols]
        return df_comp[basic_cols + other_cols]

    def sandia_step_6_assemble_tmy(self):
        """
        **Step 6** of the Sandia TMY workflow: for each of the 12 calendar
        months, extracts the full month (hourly resolution if
        :attr:`df_hourly` is available, otherwise daily) from its
        :attr:`selected_months` source year, relabels it to the synthetic
        year 2000 (dropping February 29th if the source year was a leap
        year), and concatenates the 12 months into :attr:`tmy_raw`. If
        :meth:`sandia_step_4_and_5_apply_persistence` was not run,
        automatically falls back to selecting by best FS/proximity rank
        (:meth:`_select_months_by_fs_rank`).

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_3_proximity_ranking` has not
                been run yet.

        Example:
            >>> gen.sandia_step_3_proximity_ranking()  # doctest: +SKIP
            >>> gen.sandia_step_6_assemble_tmy()  # doctest: +SKIP
        """
        if self.candidate_months is None: raise RuntimeError("Run sandia_step_3_proximity_ranking() first.")
        if self.selected_months is None:
            self._select_months_by_fs_rank()
        self._create_raw_tmy()
        return self

    def sandia_step_7_smooth_junctions(self, hours=6, s_factor=0.0):
        """
        **Step 7** (final step) of the Sandia TMY workflow: fits a
        smoothing spline (``scipy.interpolate.UnivariateSpline``) across
        each of the 11 month-to-month junctions, using the two full months
        of hourly source data on either side, and replaces the raw values
        in a configurable window around each junction — for every variable
        **except** GHI and DNI (radiation is left untouched to preserve
        solar geometry). Requires hourly data (:attr:`df_hourly` or
        *hourly_file_path*); if unavailable, smoothing is skipped (the
        final TMY equals the raw TMY) with a warning. Populates
        :attr:`tmy_final`, :attr:`validation_step6_tmy_composition` (calling
        :meth:`generate_full_summary` automatically) and, if
        :attr:`save_session` is ``True`` (default), saves a reproducible
        session via
        :func:`~pyweatherfiles.session_manager.save_object_session`.

        Args:
            hours (int): Default number of hours before/after each junction
                over which the spline is evaluated and applied. Defaults to
                6.
            s_factor (float): Default smoothing factor passed to
                ``UnivariateSpline`` (``0.0`` = exact interpolation).
                Defaults to 0.0.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_6_assemble_tmy` has not
                been run yet.

        Example:
            >>> gen.sandia_step_6_assemble_tmy()  # doctest: +SKIP
            >>> gen.sandia_step_7_smooth_junctions(hours=6, s_factor=0.0)  # doctest: +SKIP
        """
        if self.tmy_raw is None: raise RuntimeError("Run sandia_step_6_assemble_tmy() first.")
        self._apply_smoothing(hours=hours, s_factor=s_factor)
        if self.save_validation_dfs:
            self.validation_step6_tmy_composition = self._generate_tmy_composition_dataframe()
            self.generate_full_summary()

        # --- Session persistence ---
        if getattr(self, 'save_session', True):
            _inputs = {
                "file_path": self.file_path,
                "cdf_method": self.cdf_method,
                "weighting_method": self.weighting_method,
            }
            _dir = getattr(self, 'session_dir', None) or os.path.dirname(os.path.abspath(self.file_path)) or os.getcwd()
            try:
                save_object_session(self, "TMYGenerator", _inputs, session_dir=_dir)
            except Exception as _e:
                print(f"[SESSION] No se pudo guardar la sesión: {_e}")

        return self

    def step_4_create_and_smooth_tmy(self, hours=6, s_factor=0.0):
        """[DEPRECATED] Use sandia_step_6 and sandia_step_7 instead."""
        warnings.warn("step_4_create_and_smooth_tmy() is deprecated. Use sandia_step_6_assemble_tmy() and sandia_step_7_smooth_junctions() instead.", DeprecationWarning, stacklevel=2)
        self.sandia_step_6_assemble_tmy()
        self.sandia_step_7_smooth_junctions(hours=hours, s_factor=s_factor)
        return self

    def generate_tmy(self, use_persistence=True, persistence_thresholds=(0.33, 0.67), min_run_length=1, persistence_weights=None, persistence_method='sequential', zero_run_method='eliminate_worst_ranked', completeness_threshold=0.9, save_validation_dfs=True, proximity_normalization_method='std', proximity_normalization_weights=None):
        """
        Runs the complete TMY generation workflow from start to finish.

        Args:
            use_persistence (bool): If True, applies the persistence criteria (Step 3).
            persistence_method (str): 'score' or 'sequential'.
            completeness_threshold (float): Threshold for data completeness (0.0 to 1.0)
            save_validation_dfs (bool): If True (default), stores validation dataframes.
            proximity_normalization_method (str): Proximity denominator method.
                One of 'std' (default), 'long_term_mean', 'range',
                'weighted', or 'no_normalization'.
            proximity_normalization_weights (dict, optional): Used when
                proximity_normalization_method='weighted'. Expected keys are
                't_mean', 't_median', 'ghi_mean', 'ghi_median' and values must sum to 1.
            ... (other args passed to respective steps)

        Returns:
            self: The TMYGenerator instance for method chaining.

        Example:
            >>> from pyweatherfiles import tmy
            >>> gen = tmy.TMYGenerator(file_path="weather_data.csv", cdf_method="daily", data_frequency="hourly")  # doctest: +SKIP
            >>> gen.generate_tmy(use_persistence=True, persistence_method="sequential")  # doctest: +SKIP
            >>> gen.export_tmy("tmy_output.csv")  # doctest: +SKIP
        """
        print("--- Starting full TMY generation workflow ---")
        self.save_validation_dfs = save_validation_dfs
        self.sandia_step_1_load_and_prepare()
        self.sandia_step_2_select_candidates_fs(completeness_threshold=completeness_threshold)
        self.sandia_step_3_proximity_ranking(
            normalization_method=proximity_normalization_method,
            normalization_weights=proximity_normalization_weights
        )
        if use_persistence:
            self.sandia_step_4_and_5_apply_persistence(
                thresholds=persistence_thresholds,
                min_run_length=min_run_length,
                persistence_weights=persistence_weights,
                persistence_method=persistence_method,
                zero_run_method=zero_run_method
            )
        else:
            self._select_months_by_fs_rank()
        self.sandia_step_6_assemble_tmy()
        self.sandia_step_7_smooth_junctions()
        print("\n--- Full TMY generation finished ---")
        return self

    # --- PUBLIC METHODS FOR EXPORT, VALIDATION, AND VISUALIZATION ---

    def export_tmy(self, output_path=None):
        """
        Exports the final TMY data to a specified file path.

        Any variable present in :attr:`df_hourly` but absent from
        :attr:`tmy_final` is assembled the same way as the TMY (same
        selected months/years) and appended. The source file's original
        column names are restored (inverse of :attr:`base_mapping`) before
        writing, so that — if the ``col_*`` arguments matched
        :class:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`'s
        defaults — the exported file is directly usable as input to that
        converter without any extra ``column_mapping``.

        Args:
            output_path (str, optional): The destination file path. If None, a
                default name is generated. Supported extensions: .csv, .tmy, .xlsx.

        Returns:
            None: The file is written to *output_path*; nothing is returned.

        Raises:
            RuntimeError: If no TMY has been generated yet (i.e.
                :attr:`tmy_final` is ``None``).
            ValueError: If *output_path*'s extension is not one of
                ``.csv``/``.tmy``/``.xlsx``.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.export_tmy("tmy_output.csv")  # doctest: +SKIP
        """
        if self.tmy_final is None: raise RuntimeError("No TMY has been generated to export.")

        if output_path is None:
            base_name = os.path.splitext(os.path.basename(self.file_path))[0]
            output_path = f"{base_name}_generated_tmy.csv"

        _, extension = os.path.splitext(output_path)
        extension = extension.lower()

        # --- FIX: Final Pre-Export Safety Check ---
        for col in ['GHI', 'DNI', 'Wind_speed']:
            if col in self.tmy_final.columns:
                if (self.tmy_final[col] < 0).any():
                     print(f"WARNING: Negative values detected in '{col}' before export. Clipping to 0.")
                     self.tmy_final[col] = self.tmy_final[col].clip(lower=0)

        tmy_to_export = self.tmy_final.copy()

        # --- Append extra columns from df_hourly (variables not already in tmy_final) ---
        if self.df_hourly is not None and self.selected_months is not None:
            core_cols = set(tmy_to_export.columns)
            extra_cols = [c for c in self.df_hourly.columns if c not in core_cols]
            if extra_cols:
                print(f"Appending {len(extra_cols)} extra column(s) from hourly source: {extra_cols}")
                TMY_YEAR = 2000
                extra_pieces = []
                for month in range(1, 13):
                    year = int(self.selected_months[month])
                    start_date = f"{year}-{month:02d}-01"
                    end_date = pd.Timestamp(start_date) + pd.offsets.MonthEnd(0)
                    slice_data = self.df_hourly.loc[
                        start_date:f"{end_date.date()} 23:00:00", extra_cols
                    ].copy()
                    if month == 2:
                        slice_data = slice_data[slice_data.index.day != 29]
                    slice_data.index = slice_data.index.map(lambda t: t.replace(year=TMY_YEAR))
                    extra_pieces.append(slice_data)

                df_extra = pd.concat(extra_pieces)
                if not df_extra.index.is_unique:
                    df_extra = df_extra[~df_extra.index.duplicated()]

                # Align index to tmy_to_export (handles minor gaps)
                df_extra = df_extra.reindex(tmy_to_export.index)
                tmy_to_export = pd.concat([tmy_to_export, df_extra], axis=1)

        # --- Restore original column names from the source file ---
        # Use only base_mapping (user-specified col_* args) to invert, NOT the full column_mapping
        # which also contains legacy shortcuts (temp→T_air, dwpt→T_dew, wspd→Wind_speed) that
        # would overwrite the correct original names when the dict is inverted.
        inverse_mapping = {v: k for k, v in self.base_mapping.items()}
        # Only rename columns that actually exist in the dataframe
        rename_cols = {k: v for k, v in inverse_mapping.items() if k in tmy_to_export.columns}
        if rename_cols:
            tmy_to_export = tmy_to_export.rename(columns=rename_cols)
        # Also restore the index name if 'time' was mapped from a different column name
        original_time_name = inverse_mapping.get('time', 'time')
        tmy_to_export.index.name = original_time_name

        print(f"Exporting TMY to '{output_path}'...")
        if extension in ['.csv', '.tmy']:
            tmy_to_export.to_csv(output_path)
        elif extension == '.xlsx':
            try:
                tmy_for_excel = tmy_to_export.copy()
                tmy_for_excel.index = tmy_for_excel.index.tz_localize(None)
                tmy_for_excel.to_excel(output_path)
            except ImportError:
                print("ERROR: To export to .xlsx, you need to install 'openpyxl'.")
        else:
            raise ValueError(f"Unsupported file format: '{extension}'.")
        print("Export completed successfully.")

    def validate_step_1_data_loading(self):
        """Prints descriptive statistics and a sample plot for the loaded data.

        Example:
            >>> gen.sandia_step_1_load_and_prepare()  # doctest: +SKIP
            >>> gen.validate_step_1_data_loading()  # doctest: +SKIP
        """
        # Check if either hourly or daily data exists
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")

        print("\n--- Validation for Step 1: Data Loading and Preparation ---")

        if self.df_hourly is not None:
            print("\nDescriptive Statistics for Hourly Data (`df_hourly`):"), print(self.df_hourly.describe().to_string())
        if self.df_daily is not None:
            print("\nDescriptive Statistics for Daily Data (`df_daily`):"), print(self.df_daily.describe().to_string())

        # plt.figure(figsize=(15, 5))
        # sample_month, sample_year = self.df_hourly.index[0].month, self.df_hourly.index[0].year
        # sample_data = self.df_hourly[(self.df_hourly.index.year == sample_year) & (self.df_hourly.index.month == sample_month)]
        # plt.plot(sample_data.index, sample_data['T_air'])
        # plt.title(f"Time Series Sample for T_air ({pd.to_datetime(f'2000-{sample_month}-01').strftime('%B')} {sample_year})")
        # plt.ylabel("T_air (°C)"), plt.grid(True, linestyle=':'), plt.show()

    def validate_fs_calculation(self, variable, month, year):
        """
        Provides a detailed breakdown of the FS statistic calculation for a specific case.

        Args:
            variable (str): The name of the variable to validate.
            month (int): The month to validate (1-12).
            year (int): The year to validate.

        Returns:
            pd.DataFrame or None: A DataFrame with the calculation steps.

        Example:
            >>> gen.validate_fs_calculation("T_air", month=1, year=2019)  # doctest: +SKIP
        """
        # Check if either hourly or daily data exists
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")
        print(f"\n--- Validation of FS Calculation for '{variable}' in {pd.to_datetime(f'2000-{month}-01').strftime('%B')} of {year} ---")

        analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily

        # Handle column name mapping: user might pass 'T_air' but df_daily has 'T_air_mean'
        if variable not in analysis_df.columns:
            # Try to find a matching column
            if 'T_air' in variable or variable == 'T_air':
                variable = 'T_air_mean' if 'T_air_mean' in analysis_df.columns else 'T_air'
            elif 'T_dew' in variable or variable == 'T_dew':
                variable = 'T_dew_mean' if 'T_dew_mean' in analysis_df.columns else 'T_dew'
            elif 'Wind_speed' in variable or variable == 'Wind_speed':
                variable = 'Wind_speed_mean' if 'Wind_speed_mean' in analysis_df.columns else 'Wind_speed'
            elif 'GHI' in variable or variable == 'GHI':
                variable = 'GHI_sum' if 'GHI_sum' in analysis_df.columns else 'GHI'

        long_term_series = analysis_df[analysis_df.index.month == month][variable]
        year_series = analysis_df[(analysis_df.index.month == month) & (analysis_df.index.year == year)][variable]

        if long_term_series.empty or year_series.empty:
            print("Not enough data for this validation.")
            return None

        fs_val, common_x, interp_lt, interp_yr, _, _ = self._calculate_fs_statistic(year_series, long_term_series, return_details=True)

        df_calc = pd.DataFrame({
            'Interpolation_Point': common_x, 'CDF_Long_Term': interp_lt,
            'CDF_Candidate_Year': interp_yr, 'Absolute_Difference': np.abs(interp_lt - interp_yr)
        })
        print("Calculation Breakdown Table (first 5 rows):"), print(df_calc.head().to_string())
        print(f"\nSum of 'Absolute_Difference' (Final FS Value): {df_calc['Absolute_Difference'].sum():.4f}")

        return df_calc

    def validate_full_ranking_for_month(self, month):
        """
        Calculates and displays the full FS ranking for all years for a given month.

        Args:
            month (int): The month to validate (1-12).

        Returns:
            pd.DataFrame: The full ranking table for the specified month.

        Example:
            >>> gen.validate_full_ranking_for_month(month=1)  # doctest: +SKIP
        """
        # Check if either hourly or daily data exists
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")
        month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
        print(f"\n--- Validation of Full FS Ranking for {month_name} ---")

        analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily

        # Use the internal helper to generate the table
        df_ranking = self._generate_ranking_table_for_month(month, analysis_df)

        # Update attribute as well, ensuring consistency
        self.validation_step2_fs_ranking_by_month[month] = df_ranking

        print("\nWeights used for calculation:"), print(self.weights)
        print("\nFull Ranking Table (showing top 10 years):"), print(df_ranking.head(10).to_string(float_format="%.4f"))
        print(f"(The full table with {len(df_ranking)} years has been saved to `tmy_generator.validation_st2_df_fs_ranking_by_month[{month}]`)")

        return df_ranking

    def validate_persistence_selection(self):
        """Prints the detailed persistence tables for each month.

        Example:
            >>> gen.sandia_step_4_and_5_apply_persistence()  # doctest: +SKIP
            >>> gen.validate_persistence_selection()  # doctest: +SKIP
        """
        
        # 1. Check for Sequential method details
        if self.validation_step4_persistence_sequential_details:
            print("\n--- Validation for Step 3: Persistence Decisions (Sequential Exclusion) ---")
            for month_num, df_details in sorted(self.validation_step4_persistence_sequential_details.items()):
                month_name = pd.to_datetime(f'2000-{month_num}-01').strftime('%B')
                print(f"\nPersistence Table for {month_name}:")
                # Format floats for FS
                print(df_details.to_string(index=False, float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))
                
                selected_row = df_details[df_details['Decision'].str.contains("SELECTED", na=False)]
                if not selected_row.empty:
                    print(f"--> Selected Year: {int(selected_row.iloc[0]['Year'])}")
            return

        # 2. Check for Scoring method details
        if self.validation_step4_persistence_score_details:
            print("\n--- Validation for Step 3: Persistence Scoring Selection ---")
            for month_num, df_details in sorted(self.validation_step4_persistence_score_details.items()):
                month_name = pd.to_datetime(f'2000-{month_num}-01').strftime('%B')
                print(f"\nScoring Table for {month_name}:")
                # Format floats
                print(df_details.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)))
                selected_year = df_details.iloc[0]['Year']
                print(f"--> Selected year for {month_name}: {int(selected_year)} (Rank 1)")
            return

        # Fallback for old data or if no details were saved
        if self.persistence_thresholds is None:
            print("\nPersistence step was skipped. Nothing to validate.")
        else:
            raise RuntimeError("Run 'step_3_apply_persistence()' first.")

    def _smooth_tmy_curve_fitting(self, hours=6, s_factor=0.0):
        """
        Part of Step 6: Smooths the TMY discontinuities using curve fitting (spline).
        """
        if self.tmy_raw is None: raise RuntimeError("Raw TMY not generated yet. Run 'step_4_create_and_smooth_tmy()' first.")

    def validate_step_4_final_tmy(self):
        """Prints the composition table and descriptive statistics of the final TMY.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.validate_step_4_final_tmy()  # doctest: +SKIP
        """
        if self.tmy_final is None: raise RuntimeError("Run 'step_4_create_and_smooth_tmy()' first.")
        print("\n--- Validation for Step 4: Final TMY ---")

        if self.validation_step6_tmy_composition is None:
             self.validation_step6_tmy_composition = self._generate_tmy_composition_dataframe()

        # Fallback if generation failed or returned None
        if self.validation_step6_tmy_composition is None:
             composition_data = {'Month': [pd.to_datetime(f'2000-{m}-01').strftime('%B') for m in range(1, 13)], 'Source_Year': [self.selected_months[m] for m in range(1, 13)]}
             self.validation_step6_tmy_composition = pd.DataFrame(composition_data)
        print("\nTMY Composition Table:"), print(self.validation_step6_tmy_composition.set_index('Month').to_string())

        print("\nDescriptive Statistics of the Final TMY:"), print(self.tmy_final.describe().to_string())

    def summarize_fs_results(self):
        """Creates and prints a summary table of FS results for all candidate months.

        Example:
            >>> gen.sandia_step_3_proximity_ranking()  # doctest: +SKIP
            >>> gen.summarize_fs_results()  # doctest: +SKIP
        """
        if self.candidate_months is None: raise RuntimeError("Run 'step_2_select_candidate_months()' first.")
        print("\n--- Overall Summary of FS Results ---")

        # Ensure the summary dataframe exists
        if self.validation_step3_proximity_ranking is None:
            self._generate_summary_fs_ranking()

        print("\nRanking Breakdown for the Top 5 Candidates of Each Month:")
        print(self.validation_step3_proximity_ranking.to_string(float_format="%.4f"))

    def plot_cdfs(self, month_to_plot=1, years_to_plot=None, save_figure_data=False):
        """
        Plots the CDFs for selected years against the long-term CDF for a given month.

        Args:
            month_to_plot (int): The month to visualize (1-12).
            years_to_plot (list, optional): A list of specific years to plot.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Example:
            >>> gen.plot_cdfs(month_to_plot=1, years_to_plot=[2018, 2019, 2020])  # doctest: +SKIP
        """
        # Check if either hourly or daily data exists
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")
        print(f"\nGenerating CDF visualizations for month {month_to_plot}...")

        # Adapt variables, labels, and data source based on the method
        if self.cdf_method == 'hourly':
            analysis_df = self.df_hourly
            prefix = "Hourly"
            variables = {
                'T_air': f'{prefix} T_air (°C)', 'T_dew': f'{prefix} T_dew (°C)',
                'Wind_speed': f'{prefix} Wind_speed (m/s)', 'GHI': f'{prefix} GHI (Wh/m^2)'
            }
            fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        else:  # daily or daily_with_dtr
            analysis_df = self.df_daily
            prefix = "Daily"
            if self.cdf_method == 'daily_with_dtr':
                variables = {
                    'T_air': f'{prefix} Mean T_air (°C)', 'DTR': 'Diurnal Temperature Range (°C)',
                    'T_dew': f'{prefix} Mean T_dew (°C)', 'Wind_speed': f'{prefix} Mean Wind_speed (m/s)',
                    'GHI': f'{prefix} Sum GHI (Wh/m^2)'
                }
                fig, axes = plt.subplots(3, 2, figsize=(16, 18))
            else:  # daily
                variables = {
                    'T_air_mean': f'{prefix} Mean T_air (°C)', 'T_dew_mean': f'{prefix} Mean T_dew (°C)',
                    'Wind_speed_mean': f'{prefix} Mean Wind_speed (m/s)', 'GHI_sum': f'{prefix} Sum GHI (Wh/m^2)'
                }
                # Fallback: check if columns exist, if not try without suffix (for generic daily files)
                # Instead of checking all, let's filter variables to those that exist
                existing_vars = {k: v for k, v in variables.items() if k in analysis_df.columns}
                if not existing_vars:
                    # Try alternate names if standard ones failed
                    if 'T_air' in analysis_df.columns:
                        variables = {
                            'T_air': f'{prefix} Mean T_air (°C)', 'T_dew': f'{prefix} Mean T_dew (°C)',
                            'Wind_speed': f'{prefix} Mean Wind_speed (m/s)', 'GHI': f'{prefix} Sum GHI (Wh/m^2)'
                        }
                        # Re-filter
                        variables = {k: v for k, v in variables.items() if k in analysis_df.columns}
                else:
                    variables = existing_vars
                
                fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        if years_to_plot is None: years_to_plot = sorted(analysis_df.index.year.unique())[-5:]

        month_data, month_name = analysis_df[analysis_df.index.month == month_to_plot], pd.to_datetime(f'2000-{month_to_plot}-01').strftime('%B')
        axes = axes.flatten()

        for i, (var, xlabel) in enumerate(variables.items()):
            ax = axes[i]
            
            # Prepare list to collect data for this subplot
            subplot_data_list = []
            
            long_term_series = month_data[var]
            if not long_term_series.empty:
                ax.plot(*self._compute_cdf(long_term_series), 'k--', label='Long-term', lw=2)
                
                # Add long-term data to storage
                lt_df = long_term_series.to_frame(name='value')
                lt_df['type'] = 'Long-term'
                lt_df['variable'] = var
                subplot_data_list.append(lt_df)
                
            for year in years_to_plot:
                year_series = month_data[month_data.index.year == year][var]
                if not year_series.empty:
                    ax.plot(*self._compute_cdf(year_series), label=str(year))
                    
                    # Add year data to storage
                    y_df = year_series.to_frame(name='value')
                    y_df['type'] = f'Year {year}'
                    y_df['variable'] = var
                    subplot_data_list.append(y_df)
                    
            ax.set_title(f'{month_name} - {var} ({prefix} CDFs)', fontsize=14)
            ax.set_xlabel(xlabel), ax.set_ylabel('CDF'), ax.set_ylim(0, 1), ax.grid(True, linestyle=':', alpha=0.7)
            ax.legend()
            
            if save_figure_data and subplot_data_list:
                combined_df = pd.concat(subplot_data_list)
                self.figures_data[f"{month_name} - {var} ({prefix} CDFs)"] = {'fig': fig, 'data': combined_df}

        for j in range(i + 1, len(axes)):
            axes[j].set_visible(False)

        fig.suptitle(f'CDF Comparison for {month_name} - {prefix} Data', fontsize=16)
        plt.tight_layout(), plt.show()

    def plot_fs_details(self, var_to_plot, month_to_plot, year_to_plot, save_figure_data=False):
        """
        Generates a detailed plot illustrating how the FS statistic is calculated.

        Args:
            var_to_plot (str): The variable to visualize.
            month_to_plot (int): The month to visualize (1-12).
            year_to_plot (int): The year to visualize.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Example:
            >>> gen.plot_fs_details(var_to_plot="T_air", month_to_plot=1, year_to_plot=2019)  # doctest: +SKIP
        """
        # Check if either hourly or daily data exists
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")
        print(f"\nGenerating FS Statistic visualization for {var_to_plot} in {pd.to_datetime(f'2000-{month_to_plot}-01').strftime('%B')} {year_to_plot}...")

        analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily
        prefix = "Hourly" if self.cdf_method == 'hourly' else "Daily"

        long_term_series = analysis_df[analysis_df.index.month == month_to_plot][var_to_plot]
        year_series = analysis_df[(analysis_df.index.month == month_to_plot) & (analysis_df.index.year == year_to_plot)][var_to_plot]

        if long_term_series.empty or year_series.empty:
            print("Not enough data to generate the plot.")
            return

        fs_val, common_x, interp_lt, interp_yr, (lt_vals, lt_cdf), (yr_vals, yr_cdf) = self._calculate_fs_statistic(year_series, long_term_series, return_details=True)

        fig, axes = plt.subplots(2, 1, figsize=(10, 12), sharex=True)
        month_name = pd.to_datetime(f'2000-{month_to_plot}-01').strftime('%B')

        axes[0].plot(lt_vals, lt_cdf, color='blue', label='Long-term')
        axes[0].plot(yr_vals, yr_cdf, color='red', label=f'{year_to_plot} (raw)')
        axes[0].set_title(f'{month_name} {year_to_plot} - BEFORE interpolation', fontsize=14)
        axes[0].set_ylabel('Cumulative Probability', fontsize=12), axes[0].legend(), axes[0].grid(True, linestyle='--', alpha=0.6)

        axes[1].plot(common_x, interp_lt, color='blue', label='Long-term (interp)')
        axes[1].plot(common_x, interp_yr, '--', color='green', label=f'{year_to_plot} (interp)')
        axes[1].fill_between(common_x, interp_lt, interp_yr, color='gray', alpha=0.3, label=f'FS area = {fs_val / len(common_x):.3f}')
        axes[1].set_title(f'{month_name} {year_to_plot} - AFTER interpolation', fontsize=14)
        axes[1].set_xlabel(f'{prefix} Value for {var_to_plot}', fontsize=12), axes[1].set_ylabel('Cumulative Probability', fontsize=12), axes[1].legend(), axes[1].grid(True, linestyle='--', alpha=0.6)

        if save_figure_data:
            # Store interpolation details
            data_df = pd.DataFrame({
                'Interpolation_Point': common_x,
                'CDF_Long_Term': interp_lt,
                'CDF_Candidate_Year': interp_yr,
                'Variable': var_to_plot,
                'Month': month_to_plot,
                'Year': year_to_plot
            })
            self.figures_data[f"FS Details - {var_to_plot} - {month_name} {year_to_plot}"] = {'fig': fig, 'data': data_df}

        fig.suptitle(f'Finkelstein-Schafer Statistic Calculation - {var_to_plot} ({month_name} {year_to_plot})', fontsize=16)
        plt.tight_layout(), plt.show()

    def _map_daily_to_hourly_var(self, var):
        """Maps daily variable names to their hourly counterparts."""
        mapping = {
            'T_air_mean': 'T_air', 'T_air_max': 'T_air', 'T_air_min': 'T_air',
            'T_dew_mean': 'T_dew', 'T_dew_max': 'T_dew', 'T_dew_min': 'T_dew',
            'Wind_speed_mean': 'Wind_speed', 'Wind_speed_max': 'Wind_speed',
            'GHI_sum': 'GHI', 'DNI_sum': 'DNI'
        }
        return mapping.get(var, var)

    def plot_junctions(self, junctions_to_plot, hours_around=12, save_figure_data=False):
        """
        Visualizes the raw, un-smoothed data around month junctions.

        This method is intended to be used BEFORE smoothing to inspect the
        discontinuities and help decide on appropriate smoothing parameters.

        Args:
            junctions_to_plot (list of tuples): A list where each tuple contains
                a variable name and the first month of the junction to plot.
                Example: `[('T_air', 1), ('GHI', 7)]`.
            hours_around (int): The number of hours to show on either side of
                the junction point.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Example:
            >>> gen.plot_junctions([("T_air", 1), ("GHI", 7)], hours_around=12)  # doctest: +SKIP
        """
        if self.tmy_raw is None:
            # Create a temporary raw TMY if it doesn't exist, to allow pre-visualization
            print("Creating temporary raw TMY for junction visualization...")
            self._create_raw_tmy()

        print("\n--- Visualizing Raw Month Junctions (Pre-Smoothing) ---")
        if not isinstance(junctions_to_plot, list): raise TypeError("`junctions_to_plot` must be a list of tuples, e.g., [('T_air', 2)]")

        n_plots = len(junctions_to_plot)
        if n_plots == 0:
            print("No junctions were specified to plot.")
            return

        if n_plots == 1:
            fig, axes = plt.subplots(1, 1, figsize=(15, 7), squeeze=False)
        else:
            n_cols = 2
            n_rows = (n_plots + n_cols - 1) // n_cols
            fig, axes = plt.subplots(n_rows, n_cols, figsize=(10 * n_cols, 7 * n_rows), squeeze=False)
        axes = axes.flatten()

        for i, (var_input, month1) in enumerate(junctions_to_plot):
            ax = axes[i]
            
            # Map daily variable name to hourly if necessary
            var = self._map_daily_to_hourly_var(var_input)
            
            # Check if variable exists in TMY
            if var not in self.tmy_raw.columns:
                if var_input in self.tmy_raw.columns:
                    var = var_input
                else:
                    print(f"WARNING: Variable '{var}' (mapped from '{var_input}') not found in TMY data. Skipping plot.")
                    continue
                
            junction_point_ts = self.tmy_raw[self.tmy_raw.index.month == month1].index[-1]

            try:
                junction_idx = self.tmy_raw.index.get_loc(junction_point_ts)
            except KeyError:
                print(f"WARNING: Could not find junction point for month {month1}. Skipping plot.")
                continue

            start_idx = max(0, junction_idx - hours_around)
            end_idx = min(len(self.tmy_raw) - 1, junction_idx + hours_around)

            data_raw = self.tmy_raw.iloc[start_idx:end_idx + 1]
            x_axis = np.arange(start_idx - junction_idx, end_idx - junction_idx + 1)

            month2 = month1 % 12 + 1
            month1_name = pd.to_datetime(f'2000-{month1}-01').strftime('%B')
            month2_name = pd.to_datetime(f'2000-{month2}-01').strftime('%B')

            ax.plot(x_axis, data_raw[var], 'o-', color='royalblue', label='TMY without Smoothing')
            ax.axvline(0, color='k', linestyle='-', lw=1, label='Month Junction')
            ax.set_title(f'Raw Junction for {var}: {month1_name} → {month2_name}', fontsize=14)
            ax.set_xlabel('Hours Around Junction'), ax.set_ylabel(var), ax.legend(), ax.grid(True, linestyle=':')

            if save_figure_data:
                # Store junction data
                df_junction = data_raw[[var]].copy()
                df_junction['hours_from_junction'] = x_axis
                df_junction['type'] = 'Raw'
                df_junction['variable'] = var
                df_junction['month1'] = month1
                self.figures_data[f"Junction - {var} - {month1}->{month2}"] = {'fig': fig, 'data': df_junction}

        for j in range(i + 1, len(axes)):
            axes[j].set_visible(False)

        fig.suptitle('Raw Month Junctions (Pre-Smoothing)', fontsize=16)
        plt.tight_layout(), plt.show()

    def plot_smoothing_comparison(self, junctions_to_plot, hours_around=12, save_figure_data=False):
        """
        Plots a comparison of data before and after smoothing at month junctions.
        The plot title will include the smoothing parameters used.

        Args:
            junctions_to_plot (list of tuples): Example: `[('T_air', 1), ('GHI', 7)]`.
            hours_around (int): The number of hours to show on either side of the junction.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Example:
            >>> gen.plot_smoothing_comparison([("T_air", 1), ("GHI", 7)], hours_around=12)  # doctest: +SKIP
        """
        if self.tmy_raw is None or self.tmy_final is None: raise RuntimeError("Run 'step_4_create_and_smooth_tmy()' first.")
        print("\n--- Comparing Smoothing Effect ---")
        if not isinstance(junctions_to_plot, list): raise TypeError("`junctions_to_plot` must be a list of tuples, e.g., [('T_air', 2)]")

        n_plots = len(junctions_to_plot)
        if n_plots == 0:
            print("No junctions were specified to plot.")
            return

        if n_plots == 1:
            fig, axes = plt.subplots(1, 1, figsize=(15, 7), squeeze=False)
        else:
            n_cols = 2
            n_rows = (n_plots + n_cols - 1) // n_cols
            fig, axes = plt.subplots(n_rows, n_cols, figsize=(10 * n_cols, 7 * n_rows), squeeze=False)
        axes = axes.flatten()

        default_params = {'hours_before': 6, 'hours_after': 6, 's_factor': None}

        for i, (var_input, month1) in enumerate(junctions_to_plot):
            ax = axes[i]
            
            # Map daily variable name to hourly if necessary
            var = self._map_daily_to_hourly_var(var_input)

            # Check if variable exists in TMY
            if var not in self.tmy_raw.columns:
                if var_input in self.tmy_raw.columns:
                    var = var_input
                else:
                    print(f"WARNING: Variable '{var}' (mapped from '{var_input}') not found in TMY data. Skipping plot.")
                    continue

            junction_params = (self.smoothing_config or {}).get(month1, {})
            hours = junction_params.get('hours', None)
            hours_before_val = junction_params.get('hours_before', hours or default_params['hours_before'])
            hours_after_val = junction_params.get('hours_after', hours or default_params['hours_after'])
            s_factor_val = junction_params.get('s_factor', default_params['s_factor'])

            # Comprobar si se usó un valor automático y está disponible
            s_auto_val = junction_params.get('s_factor_auto', {}).get(var)

            if s_factor_val is None:
                if s_auto_val is not None:
                    s_factor_str = f"{s_auto_val:.2g} (auto)"
                else:
                    s_factor_str = "auto"
            else:
                s_factor_str = f"{s_factor_val:.2g}"

            junction_point_ts = self.tmy_raw[self.tmy_raw.index.month == month1].index[-1]

            try:
                junction_idx = self.tmy_raw.index.get_loc(junction_point_ts)
            except KeyError:
                print(f"WARNING: Could not find junction point for month {month1}. Skipping plot.")
                continue

            start_idx = max(0, junction_idx - hours_around)
            end_idx = min(len(self.tmy_raw) - 1, junction_idx + hours_around)

            data_raw = self.tmy_raw.iloc[start_idx:end_idx + 1]
            data_final = self.tmy_final.iloc[start_idx:end_idx + 1]

            x_axis = np.arange(start_idx - junction_idx, end_idx - junction_idx + 1)

            month2 = month1 % 12 + 1
            month1_name = pd.to_datetime(f'2000-{month1}-01').strftime('%B')
            month2_name = pd.to_datetime(f'2000-{month2}-01').strftime('%B')

            ax.plot(x_axis, data_raw[var], 'o-', color='royalblue', label='TMY without Smoothing')

            # --- Estilo de línea actualizado ---
            ax.plot(x_axis, data_final[var], 'ro--', lw=2, label='Smoothed TMY')

            ax.axvline(0, color='k', linestyle='-', lw=1, label='Month Junction')

            title = (f'Smoothing Comparison for {var}: {month1_name} → {month2_name}\n'
                     f'(params: h_before={hours_before_val}, h_after={hours_after_val}, s={s_factor_str})')
            ax.set_title(title, fontsize=14)

            ax.set_xlabel('Hours Around Junction'), ax.set_ylabel(var), ax.legend(), ax.grid(True, linestyle=':')

            if save_figure_data:
                # Store comparison data
                df_raw_slice = data_raw[[var]].copy()
                df_raw_slice['hours_from_junction'] = x_axis
                df_raw_slice['type'] = 'Raw'
                
                df_final_slice = data_final[[var]].copy()
                df_final_slice['hours_from_junction'] = x_axis
                df_final_slice['type'] = 'Smoothed'
                
                combined_slice = pd.concat([df_raw_slice, df_final_slice])
                combined_slice['variable'] = var
                combined_slice['month1'] = month1
                
                self.figures_data[f"Smoothing Comparison - {var} - {month1}->{month2}"] = {'fig': fig, 'data': combined_slice}

        for j in range(i + 1, len(axes)):
            axes[j].set_visible(False)

        fig.suptitle('Smoothing Effect Comparison at Month Junctions', fontsize=16)
        plt.tight_layout(), plt.show()

    def plot_persistence_runs(self, month, years, save_figure_data=False):
        """
        Plots the daily data and persistence runs for T_air and GHI for selected years.

        Args:
            month (int): The month to visualize (1-12).
            years (list or int): A list of years (or a single year) to plot.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Example:
            >>> gen.plot_persistence_runs(month=1, years=[2018, 2019, 2020])  # doctest: +SKIP
        """
        if self.df_daily is None: raise RuntimeError("Run 'step_1_load_and_prepare_data()' first.")
        if self.persistence_thresholds is None: raise RuntimeError("Run 'step_3_apply_persistence()' before visualizing its results.")
        if not self.fs_ranking_results: raise RuntimeError("FS ranking results have not been calculated. Run 'step_2_select_candidate_months()' first.")
        if isinstance(years, int): years = [years]

        month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
        print(f"\n--- Visualizing Persistence Runs for T_air and GHI in {month_name} ---")

        long_term_data = self.df_daily[self.df_daily.index.month == month]
        if long_term_data.empty:
            print("No long-term data available for this month.")
            return

        # Determine accessible columns
        t_col = 'T_air' if 'T_air' in long_term_data.columns else 'T_air_mean'
        ghi_col = 'GHI' if 'GHI' in long_term_data.columns else 'GHI_sum'

        if t_col not in long_term_data.columns or ghi_col not in long_term_data.columns:
            print(f"  Error: Plotting requires Temp ({t_col}) and GHI ({ghi_col}). Found {long_term_data.columns.tolist()[:5]}... Skipping.")
            return

        lower_p, upper_p = self.persistence_thresholds
        t_air_upper, t_air_lower = long_term_data[t_col].quantile([upper_p, lower_p])
        ghi_lower = long_term_data[ghi_col].quantile(lower_p)

        fig, axes = plt.subplots(nrows=len(years), ncols=1, figsize=(16, 6 * len(years)), sharex=True)
        if len(years) == 1: axes = [axes]

        for ax, year in zip(axes, years):
            year_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
            if year_data.empty:
                ax.text(0.5, 0.5, f"No data available for year {year}", ha='center', va='center')
                continue

            try:
                fs_rank = self.candidate_months[month].index(year) + 1
            except (ValueError, KeyError, AttributeError):
                fs_rank = "N/A"

            w_fs_value_str = "N/A"
            year_stats = next((item for item in self.fs_ranking_results.get(month, []) if item['year'] == year), None)
            if year_stats:
                w_fs_value_str = f"{year_stats['Total_W_FS']:.4f}"

            t_freq, t_dur = self._calculate_run_stats(year_data[t_col], t_air_upper, t_air_lower, self.min_run_length)
            ghi_freq, ghi_dur = self._calculate_run_stats(year_data[ghi_col], np.inf, ghi_lower, self.min_run_length)

            title_info = (f"Year {year} (FS Rank: {fs_rank}, Total_W_FS: {w_fs_value_str})\n"
                          f"{t_col} Runs: Freq={t_freq}, MaxLen={t_dur} days | "
                          f"{ghi_col} Low Runs: Freq={ghi_freq}, MaxLen={ghi_dur} days")

            self._plot_single_persistence_subplot(ax, year_data, (t_air_upper, t_air_lower), ghi_lower, title_info, t_col=t_col, ghi_col=ghi_col)

        fig.suptitle(f"Year-by-Year Persistence Analysis for {month_name}", fontsize=16, y=1.0)
        axes[-1].set_xlabel("Day of Month")
        plt.tight_layout(rect=[0, 0, 1, 0.98])
        
        # Collect data for storage
        persistence_data_list = []
        
        # Add long-term data (common for all years in this context, effectively showing the dist, but the runs are per year)
        # The plot shows year-by-year, so let's store the year data that was actually plotted.
        for year in years:
            year_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
            if not year_data.empty:
                 ydf = year_data[[t_col, ghi_col]].copy()
                 ydf['type'] = f'Year {year}'
                 ydf['month'] = month
                 persistence_data_list.append(ydf)
                 
        if save_figure_data and persistence_data_list:
            combined_df = pd.concat(persistence_data_list)
            self.figures_data[f"Year-by-Year Persistence Analysis for {month_name}"] = {'fig': fig, 'data': combined_df}
        
        plt.show()

    def plot_annual_cdfs(self, save_figure_data=False):
        """
        Plots a comparison of the annual CDF of the final TMY against the long-term data.

        This method generates a 2x2 grid of plots, one for each primary weather
        variable, to provide a high-level validation of the statistical properties
        of the entire generated TMY year.

        Args:
             save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Raises:
            RuntimeError: If the TMY has not been generated yet.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.plot_annual_cdfs()  # doctest: +SKIP
        """
        # Check if TMY and data exist
        if self.tmy_final is None:
            raise RuntimeError("The TMY must be generated first. Run the full workflow.")
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("No data available. Run 'step_1_load_and_prepare_data()' first.")

        print("\n--- Plotting Annual CDF Comparison: Final TMY vs. Long-term ---")

        # Determine the data source based on the method used for generation
        if self.data_frequency == 'daily':
            analysis_df = self.df_daily
            # Check if tmy_final is hourly (e.g. used hourly_file_path) and resample if needed
            if 'T_air' in self.tmy_final.columns and 'T_air_mean' not in self.tmy_final.columns:
                 tmy_resampled = self.tmy_final.resample('D').agg({
                    'T_air': 'mean', 'T_dew': 'mean', 'Wind_speed': 'mean', 'GHI': 'sum'
                 }).dropna()
                 # Rename to match typical daily columns for consistency with analysis_df logic
                 tmy_analysis_df = tmy_resampled.rename(columns={
                     'T_air': 'T_air_mean', 'T_dew': 'T_dew_mean', 
                     'Wind_speed': 'Wind_speed_mean', 'GHI': 'GHI_sum'
                 })
            else:
                 tmy_analysis_df = self.tmy_final
        else:
            analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily
            tmy_analysis_df = self.tmy_final.resample('D').agg({
                'T_air': 'mean', 'T_dew': 'mean', 'Wind_speed': 'mean', 'GHI': 'sum'
            }).dropna() if self.cdf_method != 'hourly' else self.tmy_final

        # Determine column names based on what's actually in analysis_df
        cols = analysis_df.columns
        t_col = 'T_air_mean' if 'T_air_mean' in cols else 'T_air'
        td_col = 'T_dew_mean' if 'T_dew_mean' in cols else 'T_dew'
        ws_col = 'Wind_speed_mean' if 'Wind_speed_mean' in cols else 'Wind_speed'
        ghi_col = 'GHI_sum' if 'GHI_sum' in cols else 'GHI'

        variables = {
            t_col: 'T_air', td_col: 'T_dew',
            ws_col: 'Wind_speed', ghi_col: 'GHI'
        }

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()

        # Initialize list to collect data if saving is enabled
        figure_data_list = []

        for i, (var, xlabel) in enumerate(variables.items()):
            ax = axes[i]

            # Get the long-term and final TMY series for the current variable
            # var is the key from variables dict (could be T_air_mean or T_air)
            # xlabel is the display label
            long_term_series = analysis_df[var]

            # For tmy_analysis_df, we need to map back to the appropriate column
            # If we're using daily analysis, tmy_analysis_df was resampled and has standard names
            if self.cdf_method != 'hourly' and self.data_frequency != 'daily':
                # tmy_analysis_df was created by resampling tmy_final (hourly) to daily
                # It has standard column names: T_air, T_dew, Wind_speed, GHI
                tmy_var = xlabel  # Use the display name which matches the resampled columns
            else:
                tmy_var = var

            tmy_series = tmy_analysis_df[tmy_var]

            # Plot interpolated CDFs for better comparison
            common_x, lt_cdf, tmy_cdf = self._compute_interpolated_cdf(long_term_series, tmy_series)
            ax.plot(common_x, lt_cdf, 'k--', label='Long-term', lw=2)
            ax.plot(common_x, tmy_cdf, 'r-', label='Final TMY', lw=1.5)

            ax.set_xlabel(xlabel)
            ax.set_ylabel('Cumulative Probability')
            ax.legend()
            ax.grid(True, linestyle=':')

            if save_figure_data:
                # Store annual CDF data
                # Long term
                lt_df = long_term_series.to_frame(name='value')
                lt_df['type'] = 'Long-term'
                lt_df['variable'] = var
                figure_data_list.append(lt_df)
                
                # TMY
                tmy_df = tmy_series.to_frame(name='value')
                tmy_df['type'] = 'Final TMY'
                tmy_df['variable'] = var
                figure_data_list.append(tmy_df)

        if save_figure_data and figure_data_list:
             combined_df = pd.concat(figure_data_list)
             self.figures_data[f"Annual CDF Comparison - {var}"] = {'fig': fig, 'data': combined_df}

        fig.suptitle('Annual CDF Comparison - Final TMY vs. Long-term Data', fontsize=16)
        plt.tight_layout()
        plt.show()

    def plot_monthly_means(self, save_figure_data=False):
        """
        Plots a comparison of monthly mean values of the final TMY against long-term averages.

        For GHI, it compares the total monthly sum instead of the mean. This plot is
        essential for quickly identifying any systematic monthly biases in the generated TMY.

        Args:
             save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Raises:
            RuntimeError: If the TMY has not been generated yet.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.plot_monthly_means()  # doctest: +SKIP
        """
        # Check if TMY and daily data exist
        if self.tmy_final is None:
            raise RuntimeError("The TMY must be generated first. Run the full workflow.")
        if self.df_daily is None:
            raise RuntimeError("Daily data required. Run 'step_1_load_and_prepare_data()' first.")

        print("\n--- Plotting Monthly Mean Comparison: Final TMY vs. Long-term ---")

        # Calculate long-term monthly averages
        # df_daily might have T_air_mean or T_air depending on how it was created
        cols = self.df_daily.columns
        t_col = 'T_air_mean' if 'T_air_mean' in cols else 'T_air'
        td_col = 'T_dew_mean' if 'T_dew_mean' in cols else 'T_dew'
        ws_col = 'Wind_speed_mean' if 'Wind_speed_mean' in cols else 'Wind_speed'
        ghi_col = 'GHI_sum' if 'GHI_sum' in cols else 'GHI'

        long_term_monthly = self.df_daily.groupby(self.df_daily.index.month).mean()
        long_term_monthly[ghi_col] = self.df_daily.groupby(self.df_daily.index.month)[ghi_col].sum() / len(self.df_daily.index.year.unique())

        # Calculate final TMY monthly averages
        # Check if tmy_final is hourly
        if 'T_air' in self.tmy_final.columns and 'T_air_mean' not in self.tmy_final.columns:
             tmy_daily = self.tmy_final.resample('D').agg({'T_air': 'mean', 'T_dew': 'mean', 'Wind_speed': 'mean', 'GHI': 'sum'}).dropna()
        else:
             # Assume it's daily already
             # We need to ensure we map whatever columns differ.
             # If tmy_final is daily, it likely has T_air_mean.
             # We should probably standardize to T_air for the aggregation step below.
             tmy_daily = self.tmy_final.copy()
             # Rename if needed for the aggregation block below which uses standard names
             rename_map = {}
             if 'T_air_mean' in tmy_daily.columns: rename_map['T_air_mean'] = 'T_air'
             if 'T_dew_mean' in tmy_daily.columns: rename_map['T_dew_mean'] = 'T_dew'
             if 'Wind_speed_mean' in tmy_daily.columns: rename_map['Wind_speed_mean'] = 'Wind_speed'
             if 'GHI_sum' in tmy_daily.columns: rename_map['GHI_sum'] = 'GHI'
             if rename_map:
                 tmy_daily = tmy_daily.rename(columns=rename_map)

        tmy_monthly = tmy_daily.groupby(tmy_daily.index.month).mean()
        tmy_monthly['GHI'] = tmy_daily.groupby(tmy_daily.index.month)['GHI'].sum()

        # Determine column names based on availability in long_term_monthly
        lt_cols = long_term_monthly.columns
        t_col = 'T_air_mean' if 'T_air_mean' in lt_cols else 'T_air'
        td_col = 'T_dew_mean' if 'T_dew_mean' in lt_cols else 'T_dew'
        ws_col = 'Wind_speed_mean' if 'Wind_speed_mean' in lt_cols else 'Wind_speed'
        ghi_col = 'GHI_sum' if 'GHI_sum' in lt_cols else 'GHI'

        variables = {
            t_col: 'Temperature (°C)', td_col: 'Dew Point (°C)',
            ws_col: 'Wind Speed (m/s)', ghi_col: 'Monthly Solar Total (Wh/m²)'
        }

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        # Initialize list for data collection
        means_data = []

        for i, (var, ylabel) in enumerate(variables.items()):
            ax = axes[i]

            ax.plot(long_term_monthly.index, long_term_monthly[var], 'k--', label='Long-term', lw=2)
            # tmy_monthly always has standard column names (T_air, GHI, etc.)
            # but var might be T_air_mean, so we need to map it
            tmy_var = 'T_air' if 'T_air' in var else ('T_dew' if 'T_dew' in var else ('Wind_speed' if 'Wind_speed' in var else 'GHI'))
            ax.plot(tmy_monthly.index, tmy_monthly[tmy_var], 'r-', label='Final TMY', lw=1.5)

            ax.set_title(var, fontsize=14)
            ax.set_ylabel(ylabel)
            ax.set_xticks(range(1, 13))
            ax.set_xticklabels(month_labels)
            ax.legend()
            ax.grid(True, linestyle=':')

            if save_figure_data:
                # Store Long Term
                df_lt = long_term_monthly[var].to_frame(name='value')
                df_lt['type'] = 'Long-term Mean'
                df_lt['variable'] = var
                means_data.append(df_lt)
                
                # Store TMY
                df_tmy = tmy_monthly[tmy_var].to_frame(name='value')
                df_tmy['type'] = 'Final TMY Mean'
                df_tmy['variable'] = var
                means_data.append(df_tmy)

        if save_figure_data and means_data:
            combined_df = pd.concat(means_data)
            self.figures_data["Monthly Means Comparison"] = {'fig': fig, 'data': combined_df}

        fig.suptitle('Monthly Mean (and Total GHI) - Final TMY vs Long-term Averages', fontsize=16)
        plt.tight_layout()
        plt.show()

    def plot_monthly_cdfs(self, sharex=True, save_figure_data=False):
        """
        Plots a month-by-month CDF comparison of the final TMY against the long-term data.

        For each primary variable, this method generates a grid of 12 subplots (one for
        each month), allowing for a detailed inspection of the statistical distribution
        of the TMY on a monthly basis.
        
        Args:
            sharex (bool): If True, subplots share the X axis.
            save_figure_data (bool): If True, stores the figure and data in self.figures_data.

        Raises:
            RuntimeError: If the TMY has not been generated yet.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.plot_monthly_cdfs(sharex=True)  # doctest: +SKIP
        """
        # Check if TMY and data exist
        if self.tmy_final is None:
            raise RuntimeError("The TMY must be generated first. Run the full workflow.")
        if self.df_hourly is None and self.df_daily is None:
            raise RuntimeError("No data available. Run 'step_1_load_and_prepare_data()' first.")

        print("\n--- Plotting Monthly CDF Comparison: Final TMY vs. Long-term ---")

        if self.data_frequency == 'daily':
            analysis_df = self.df_daily
            # For daily data, tmy_final might be hourly or daily.
            if 'T_air' in self.tmy_final.columns and 'T_air_mean' not in self.tmy_final.columns:
                # It is hourly, so we resample to daily including max/min for temperature
                tmy_resampled = self.tmy_final.resample('D').agg({
                    'T_air': ['mean', 'max', 'min'], 'T_dew': 'mean', 'Wind_speed': 'mean', 'GHI': 'sum'
                }).dropna()
                # Flatten multi-level columns
                tmy_resampled.columns = ['_'.join(col).strip('_') if isinstance(col, tuple) else col 
                                          for col in tmy_resampled.columns.values]
                # Rename to standard names (removing aggregation suffixes)
                tmy_analysis_df = tmy_resampled.rename(columns={
                    'T_air_mean': 'T_air', 'T_air_max': 'T_air_max', 'T_air_min': 'T_air_min',
                    'T_dew_mean': 'T_dew', 'Wind_speed_mean': 'Wind_speed', 'GHI_sum': 'GHI'
                })
            else:
                 # It is daily, rename to standard keys expected by plotting logic block below
                 rename_map = {
                    'T_air_mean': 'T_air', 'T_dew_mean': 'T_dew',
                    'Wind_speed_mean': 'Wind_speed', 'GHI_sum': 'GHI'
                 }
                 # Keep T_air_max and T_air_min if they exist
                 if 'T_air_max' in self.tmy_final.columns:
                     rename_map['T_air_max'] = 'T_air_max'
                 if 'T_air_min' in self.tmy_final.columns:
                     rename_map['T_air_min'] = 'T_air_min'
                 tmy_analysis_df = self.tmy_final.rename(columns=rename_map)
        else:
            analysis_df = self.df_hourly if self.cdf_method == 'hourly' else self.df_daily
            if self.cdf_method != 'hourly':
                tmy_resampled = self.tmy_final.resample('D').agg({
                    'T_air': ['mean', 'max', 'min'], 'T_dew': 'mean', 'Wind_speed': 'mean', 'GHI': 'sum'
                }).dropna()
                # Flatten multi-level columns
                tmy_resampled.columns = ['_'.join(col).strip('_') if isinstance(col, tuple) else col 
                                          for col in tmy_resampled.columns.values]
                tmy_analysis_df = tmy_resampled.rename(columns={
                    'T_air_mean': 'T_air', 'T_air_max': 'T_air_max', 'T_air_min': 'T_air_min',
                    'T_dew_mean': 'T_dew', 'Wind_speed_mean': 'Wind_speed', 'GHI_sum': 'GHI'
                })
            else:
                tmy_analysis_df = self.tmy_final

        # Determine variables to plot
        cols = analysis_df.columns
        t_col = 'T_air_mean' if 'T_air_mean' in cols else 'T_air'
        t_max_col = 'T_air_max' if 'T_air_max' in cols else None
        t_min_col = 'T_air_min' if 'T_air_min' in cols else None
        td_col = 'T_dew_mean' if 'T_dew_mean' in cols else 'T_dew'
        ws_col = 'Wind_speed_mean' if 'Wind_speed_mean' in cols else 'Wind_speed'
        ghi_col = 'GHI_sum' if 'GHI_sum' in cols else 'GHI'
        
        # Build variables list with temperature max/min if available
        variables = [t_col]
        if t_max_col:
            variables.append(t_max_col)
        if t_min_col:
            variables.append(t_min_col)
        variables.extend([td_col, ws_col, ghi_col])
        
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        for var in variables:
            fig, axes = plt.subplots(3, 4, figsize=(16, 12), sharex=sharex, sharey=True)
            axes = axes.flatten()
            fig.suptitle(f'Monthly CDF Comparison - {var}', fontsize=16)

            # Prepare list to collect data for this figure
            figure_data_list = []

            for month in range(1, 13):
                ax = axes[month - 1]

                # Filter data for the specific month
                long_term_series = analysis_df[analysis_df.index.month == month][var]
                
                # Map analysis_df variable names to tmy_analysis_df names
                if 'T_air' in var:
                    if 'max' in var:
                        tmy_var = 'T_air_max' if 'T_air_max' in tmy_analysis_df.columns else 'T_air'
                    elif 'min' in var:
                        tmy_var = 'T_air_min' if 'T_air_min' in tmy_analysis_df.columns else 'T_air'
                    else:
                        tmy_var = 'T_air'
                elif 'T_dew' in var:
                    tmy_var = 'T_dew'
                elif 'Wind_speed' in var:
                    tmy_var = 'Wind_speed'
                else:
                    tmy_var = 'GHI'
                
                tmy_series = tmy_analysis_df[tmy_analysis_df.index.month == month][tmy_var]

                if not long_term_series.empty:
                    # Add long-term data to storage
                    lt_df = long_term_series.to_frame(name='value')
                    lt_df['type'] = 'Long-term'
                    lt_df['month'] = month
                    lt_df['variable'] = var
                    figure_data_list.append(lt_df)

                if not tmy_series.empty:
                   # Add TMY data to storage
                    tmy_df = tmy_series.to_frame(name='value')
                    tmy_df['type'] = 'Final TMY'
                    tmy_df['month'] = month
                    tmy_df['variable'] = var
                    figure_data_list.append(tmy_df)

                if not long_term_series.empty and not tmy_series.empty:
                    # Use interpolated CDFs for better comparison
                    common_x, lt_cdf, tmy_cdf = self._compute_interpolated_cdf(long_term_series, tmy_series)
                    ax.plot(common_x, lt_cdf, 'k--', label='Long-term', lw=1.5)
                    ax.plot(common_x, tmy_cdf, 'r-', label='Final TMY', lw=1)

                ax.set_title(month_labels[month - 1])
                ax.grid(True, linestyle=':')
                if month % 4 == 1:  # Leftmost column
                    ax.set_ylabel('CDF')
                if month > 8:  # Bottom row
                    ax.set_xlabel(var)

            # Create a single legend for the entire figure
            handles, labels = ax.get_legend_handles_labels()
            fig.legend(handles, labels, loc='upper right')

            plt.tight_layout(rect=[0, 0, 1, 0.96])
            
            # Store figure and data
            if save_figure_data and figure_data_list:
                combined_df = pd.concat(figure_data_list)
                self.figures_data[f"Monthly CDF Comparison - {var}"] = {'fig': fig, 'data': combined_df}
                
            plt.show()

    @staticmethod
    def check_input_expectations(file_path, weighting_method='sandia', data_frequency='hourly', column_mapping=None):
        """
        Helper method to analyze an input file and suggest column mapping.

        Args:
            file_path (str): Path to the input file (csv or excel).
            weighting_method (str): 'sandia' or 'tmy3'.
            data_frequency (str): 'hourly' or 'daily'.
            column_mapping (dict, optional): Dictionary to map file columns to standard names.

        Returns:
            dict: ``{'found_columns': list, 'expected_variables': list,
            'missing_exact': list, 'time_valid': bool}`` — a summary of the
            analysis, also printed to the console with a suggested
            ``column_mapping`` snippet if any expected column is missing.

        Example:
            >>> from pyweatherfiles import tmy
            >>> tmy.TMYGenerator.check_input_expectations("weather_data.csv", weighting_method="sandia", data_frequency="hourly")  # doctest: +SKIP
        """
        import pandas as pd
        print(f"--- Analyzing '{file_path}' for {weighting_method} method ({data_frequency}) ---")

        try:
            if file_path.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_path, nrows=5)
            else:
                df = pd.read_csv(file_path, nrows=5)
        except Exception as e:
            print(f"Error reading file: {e}")
            return

        # Apply column mapping if provided
        if column_mapping:
            print(f"Applying provided column mapping: {column_mapping}")
            df = df.rename(columns=column_mapping)

        columns = df.columns.tolist()
        print(f"Found columns (after mapping): {columns}")

        # Expected Standard Variable Names (internal)
        # 'time' is always required
        expected_internal = ['time']

        if data_frequency == 'hourly':
            expected_internal.extend(['T_air', 'T_dew', 'Wind_speed', 'GHI'])
            if weighting_method == 'tmy3':
                expected_internal.append('DNI')

        elif data_frequency == 'daily':
            # Based on standard daily aggregations used in code
            # Note: The code handles mapping internally, but these are the Keys needed in weights
            if weighting_method == 'tmy3':
                expected_internal.extend([
                    'T_air_max', 'T_air_min', 'T_air_mean',
                    'T_dew_max', 'T_dew_min', 'T_dew_mean',
                    'Wind_speed_max', 'Wind_speed_mean',
                    'GHI_sum', 'DNI_sum'
                ])
            else:  # sandia
                expected_internal.extend([
                    'T_air_max', 'T_air_min', 'T_air_mean',
                    'T_dew_max', 'T_dew_min', 'T_dew_mean',
                    'Wind_speed_max', 'Wind_speed_mean',
                    'GHI_sum'
                ])

        print(f"\\nExpected Variables: {expected_internal}")

        # Simple heuristic check
        missing_exact = [col for col in expected_internal if col not in columns]

        # Time format validation
        time_ok = False
        if 'time' in columns:
            try:
                # Try to parse the time column to see if it's valid
                pd.to_datetime(df['time'], errors='raise', utc=True)
                time_ok = True
                print("Ref: 'time' column found and format looks valid.")
            except Exception:
                print("WARNING: 'time' column found but contains invalid format or non-datetime values.")
        else:
             print("WARNING: 'time' column missing. Please map a column to 'time' (e.g. 'Fecha', 'Date').")

        if not missing_exact and time_ok:
            print("\\nResult: All expected columns found exactly and time format is valid!")
        else:
            if missing_exact:
                print(f"\\nResult: Missing exact matches for: {missing_exact}")
                print("You likely need to provide or update a `column_mapping` dictionary.")
                print("Example structure:")
                print("column_mapping = {")
                for miss in missing_exact:
                    print(f"    '<your_file_column_for_{miss}>': '{miss}',")
                print("}")
            
            if not time_ok and 'time' in missing_exact:
                 print("Critical: 'time' column is missing.")

        return {
            'found_columns': columns,
            'expected_variables': expected_internal,
            'missing_exact': missing_exact,
            'time_valid': time_ok
        }

    # ==========================================================================
    #   ANALYSIS & CORRECTION METHODS  (v4.09)
    # ==========================================================================

    def _get_daily_t_col(self):
        """Returns the daily temperature column name available in df_daily."""
        for col in ('T_air_mean', 'T_air'):
            if self.df_daily is not None and col in self.df_daily.columns:
                return col
        return None

    def _get_daily_ghi_col(self):
        """Returns the daily GHI column name available in df_daily."""
        for col in ('GHI_sum', 'GHI'):
            if self.df_daily is not None and col in self.df_daily.columns:
                return col
        return None

    def get_candidate_stats(self, month):
        """
        Returns a DataFrame with temperature and GHI statistics for each of
        the top-5 candidate years (after Proximity Ranking) for a given month.

        Columns returned:
            Prox_Rank, Year, FS_Score, T_mean, T_diff_vs_LT,
            T_pctil, GHI_mean, GHI_diff_vs_LT, GHI_pctil

        Args:
            month (int): Month to analyse (1-12).

        Returns:
            pd.DataFrame or None if data are not yet computed.

        Example:
            >>> gen.sandia_step_3_proximity_ranking()  # doctest: +SKIP
            >>> gen.get_candidate_stats(month=7)  # doctest: +SKIP
        """
        if self.candidate_months is None:
            raise RuntimeError("Run step_2_select_candidate_months() first.")

        t_col  = self._get_daily_t_col()
        ghi_col = self._get_daily_ghi_col()

        candidates = self.candidate_months.get(month, [])
        if not candidates:
            print(f"No candidates found for month {month}.")
            return None

        lt_data = self.df_daily[self.df_daily.index.month == month]
        lt_t_mean   = lt_data[t_col].mean()   if t_col  else np.nan
        lt_ghi_mean = lt_data[ghi_col].mean() if ghi_col else np.nan

        yearly_t   = lt_data.groupby(lt_data.index.year)[t_col].mean()   if t_col  else None
        yearly_ghi = lt_data.groupby(lt_data.index.year)[ghi_col].mean() if ghi_col else None

        rows = []
        for rank, yr in enumerate(candidates):
            yr_data = lt_data[lt_data.index.year == yr]

            fs_val = next(
                (item.get('Total_W_FS', np.nan)
                 for item in self.fs_ranking_results.get(month, [])
                 if item['year'] == yr),
                np.nan
            )

            t_mean  = yr_data[t_col].mean()   if t_col  and not yr_data.empty else np.nan
            t_diff  = t_mean - lt_t_mean
            t_pctil = float((yearly_t < t_mean).mean() * 100) if yearly_t is not None else np.nan

            ghi_mean  = yr_data[ghi_col].mean()   if ghi_col and not yr_data.empty else np.nan
            ghi_diff  = ghi_mean - lt_ghi_mean
            ghi_pctil = float((yearly_ghi < ghi_mean).mean() * 100) if yearly_ghi is not None else np.nan

            is_selected = (self.selected_months or {}).get(month) == yr

            rows.append({
                'Prox_Rank':       rank + 1,
                'Year':            yr,
                'FS_Score':        fs_val,
                'T_mean':          t_mean,
                'T_diff_vs_LT':    t_diff,
                'T_pctil':         t_pctil,
                'GHI_mean':        ghi_mean,
                'GHI_diff_vs_LT':  ghi_diff,
                'GHI_pctil':       ghi_pctil,
                'Is_Selected':     is_selected,
            })

        return pd.DataFrame(rows)

    def generate_full_summary(self):
        """
        Generates and stores a single consolidated summary DataFrame
        (``self.validation_full_summary``) with **one row per calendar month**,
        collecting the key metrics from every step of the Sandia TMY process:

        * **Step 2** — Finkelstein-Schafer score and overall ranking position
          among all available years.
        * **Step 3** — Proximity rank (1-5 among top candidates).
        * **Step 4/5** — Persistence run indicators and exclusion decision.
        * **Step 6** — Final selected source year.
        * **Long-term vs. selected year** — mean temperature and mean GHI
          difference between the chosen year and the multi-year average.

        The result is stored in ``self.validation_full_summary`` and is
        automatically included in the pickle/JSON session files.

        Returns
        -------
        pd.DataFrame
            Summary table (also available as ``self.validation_full_summary``).

        Raises
        ------
        RuntimeError
            If the workflow has not been run at least up to Step 4/5.

        Example
        -------
        >>> gen.generate_tmy()  # doctest: +SKIP
        >>> gen.generate_full_summary()  # doctest: +SKIP
        """
        if self.selected_months is None:
            raise RuntimeError(
                "Run the full workflow first (at least up to "
                "sandia_step_4_and_5_apply_persistence())."
            )

        t_col   = self._get_daily_t_col()
        ghi_col = self._get_daily_ghi_col()

        rows = []
        for month in range(1, 13):
            selected_year = self.selected_months.get(month)
            if selected_year is None:
                continue

            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            row = {
                'Month':       month_name,
                'Month_Num':   month,
                'Source_Year': int(selected_year),
            }

            # ── Step 2: FS score and overall rank ────────────────────────────
            df_fs_full = self.validation_step2_fs_ranking_by_month.get(month)
            if df_fs_full is not None and not df_fs_full.empty:
                sel_row_fs = df_fs_full[df_fs_full['Year'] == selected_year]
                if not sel_row_fs.empty:
                    row['FS_Total_W_FS']   = round(float(sel_row_fs.iloc[0]['Total_W_FS']), 6)
                    row['FS_Rank_Overall'] = int(sel_row_fs.iloc[0]['Rank'])
                    row['FS_Num_Years']    = len(df_fs_full)
                else:
                    row['FS_Total_W_FS']   = np.nan
                    row['FS_Rank_Overall'] = np.nan
                    row['FS_Num_Years']    = len(df_fs_full)
            else:
                row['FS_Total_W_FS']   = np.nan
                row['FS_Rank_Overall'] = np.nan
                row['FS_Num_Years']    = np.nan

            # ── Step 3: Proximity rank ────────────────────────────────────────
            candidates_prox = (self.candidate_months or {}).get(month, [])
            row['Prox_Rank'] = (
                candidates_prox.index(selected_year) + 1
                if selected_year in candidates_prox else np.nan
            )

            # ── Step 4/5: Persistence details ────────────────────────────────
            seq_details = (self.validation_step4_persistence_sequential_details or {}).get(month)
            if seq_details is not None and not seq_details.empty:
                sel_p = seq_details[seq_details['Year'] == selected_year]
                if not sel_p.empty:
                    row['Persist_NumRuns']  = int(sel_p.iloc[0]['NumRuns'])
                    row['Persist_MaxRun']   = int(sel_p.iloc[0]['Max_run'])
                    row['Persist_Decision'] = str(sel_p.iloc[0]['Decision'])
                else:
                    row['Persist_NumRuns']  = np.nan
                    row['Persist_MaxRun']   = np.nan
                    row['Persist_Decision'] = ''
            else:
                # Try score-method fallback
                score_details = self.validation_step4_persistence_score_details
                sc = None
                if isinstance(score_details, dict):
                    sc = score_details.get(month)
                if sc is not None and not sc.empty:
                    sel_p = sc[sc['Year'] == selected_year]
                    if not sel_p.empty:
                        row['Persist_Score']    = round(float(sel_p.iloc[0]['Score']), 6)
                        row['Persist_Decision'] = 'SELECTED TMY MONTH (Score)'
                    else:
                        row['Persist_Score']    = np.nan
                        row['Persist_Decision'] = ''
                else:
                    row['Persist_Decision'] = 'N/A (persistence skipped)'

            # ── Long-term vs. selected year stats ────────────────────────────
            if self.df_daily is not None:
                lt_data  = self.df_daily[self.df_daily.index.month == month]
                sel_data = lt_data[lt_data.index.year == selected_year]

                if t_col and t_col in lt_data.columns:
                    lt_t  = lt_data[t_col].mean()
                    sel_t = sel_data[t_col].mean() if not sel_data.empty else np.nan
                    row['LT_T_mean']  = round(lt_t, 2)
                    row['Sel_T_mean'] = round(sel_t, 2)
                    row['T_diff']     = round(float(sel_t - lt_t), 2) if pd.notna(sel_t) else np.nan

                if ghi_col and ghi_col in lt_data.columns:
                    lt_ghi  = lt_data[ghi_col].mean()
                    sel_ghi = sel_data[ghi_col].mean() if not sel_data.empty else np.nan
                    row['LT_GHI_mean']  = round(lt_ghi, 2)
                    row['Sel_GHI_mean'] = round(sel_ghi, 2)
                    row['GHI_diff']     = round(float(sel_ghi - lt_ghi), 2) if pd.notna(sel_ghi) else np.nan

            rows.append(row)

        df_summary = pd.DataFrame(rows)
        self.validation_full_summary = df_summary
        print(
            f"Full summary generated: {len(df_summary)} months. "
            f"Stored in 'self.validation_full_summary'."
        )
        return df_summary

    def analyze_selection(self, months=None, temp_diff_threshold=1.0,
                          ghi_diff_threshold=None, verbose=True):
        """
        Analyses the TMY month selection for the specified months, flagging
        anomalous years where the selected year's mean temperature and/or mean
        GHI deviate significantly from the long-term mean.

        The result is also stored in ``self.validation_selection_analysis`` and
        is therefore automatically included in the pickle/JSON session files.

        Args:
            months (list of int, optional): Months to analyse. Defaults to all
                12 months.
            temp_diff_threshold (float): Absolute temperature difference (°C)
                above which a selection is flagged. Default is 1.0 °C.
                Set to ``None`` to disable the temperature check.
            ghi_diff_threshold (float, optional): Absolute GHI difference
                (Wh/m² daily mean) above which a selection is flagged.
                Default is ``None`` (GHI check disabled).
            verbose (bool): If True, prints a formatted report to stdout.

        Returns:
            pd.DataFrame: Summary table with one row per analysed month.
                Columns: Month, Month_Num, Selected_Year, FS_Rank_of_5,
                T_mean_LT, T_mean_Selected, T_diff, T_pctil, Flagged_T,
                GHI_mean_LT, GHI_mean_Selected, GHI_diff, GHI_pctil,
                Flagged_GHI, Flagged

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.analyze_selection(temp_diff_threshold=1.0)  # doctest: +SKIP
        """
        if self.selected_months is None:
            raise RuntimeError("Run generate_tmy() or step_3_apply_persistence() first.")
        if self.candidate_months is None:
            raise RuntimeError("Run step_2_select_candidate_months() first.")

        t_col   = self._get_daily_t_col()
        ghi_col = self._get_daily_ghi_col()

        if t_col is None and ghi_diff_threshold is None:
            raise RuntimeError("Temperature column not found in df_daily.")

        if months is None:
            months = list(range(1, 13))

        rows = []
        for month in months:
            selected_year = self.selected_months.get(month)
            candidates    = self.candidate_months.get(month, [])
            month_name    = pd.to_datetime(f'2000-{month}-01').strftime('%B')

            lt_data  = self.df_daily[self.df_daily.index.month == month]
            sel_data = lt_data[lt_data.index.year == selected_year]

            # ── Temperature stats ────────────────────────────────────────────
            t_lt_mean = sel_t_mean = t_diff = t_pctil = np.nan
            flagged_t = False
            if t_col and t_col in lt_data.columns:
                yearly_t   = lt_data.groupby(lt_data.index.year)[t_col].mean()
                t_lt_mean  = lt_data[t_col].mean()
                sel_t_mean = sel_data[t_col].mean() if not sel_data.empty else np.nan
                t_diff     = sel_t_mean - t_lt_mean
                t_pctil    = float((yearly_t < sel_t_mean).mean() * 100) if pd.notna(sel_t_mean) else np.nan
                if temp_diff_threshold is not None and pd.notna(t_diff):
                    flagged_t = abs(t_diff) > temp_diff_threshold

            # ── GHI stats ────────────────────────────────────────────────────
            ghi_lt_mean = sel_ghi_mean = ghi_diff = ghi_pctil = np.nan
            flagged_ghi = False
            if ghi_col and ghi_col in lt_data.columns:
                yearly_ghi   = lt_data.groupby(lt_data.index.year)[ghi_col].mean()
                ghi_lt_mean  = lt_data[ghi_col].mean()
                sel_ghi_mean = sel_data[ghi_col].mean() if not sel_data.empty else np.nan
                ghi_diff     = sel_ghi_mean - ghi_lt_mean
                ghi_pctil    = float((yearly_ghi < sel_ghi_mean).mean() * 100) if pd.notna(sel_ghi_mean) else np.nan
                if ghi_diff_threshold is not None and pd.notna(ghi_diff):
                    flagged_ghi = abs(ghi_diff) > ghi_diff_threshold

            # Rank of the selected year within the top-5 candidate list
            fs_rank_in_5 = (candidates.index(selected_year) + 1) if selected_year in candidates else None

            rows.append({
                'Month':               month_name,
                'Month_Num':           month,
                'Selected_Year':       selected_year,
                'FS_Rank_of_5':        fs_rank_in_5,
                'T_mean_LT':           round(t_lt_mean, 2)    if pd.notna(t_lt_mean)    else np.nan,
                'T_mean_Selected':     round(sel_t_mean, 2)   if pd.notna(sel_t_mean)   else np.nan,
                'T_diff':              round(t_diff, 2)        if pd.notna(t_diff)        else np.nan,
                'T_pctil':             round(t_pctil, 1)       if pd.notna(t_pctil)       else np.nan,
                'Flagged_T':           flagged_t,
                'GHI_mean_LT':         round(ghi_lt_mean, 2)  if pd.notna(ghi_lt_mean)  else np.nan,
                'GHI_mean_Selected':   round(sel_ghi_mean, 2) if pd.notna(sel_ghi_mean) else np.nan,
                'GHI_diff':            round(ghi_diff, 2)      if pd.notna(ghi_diff)      else np.nan,
                'GHI_pctil':           round(ghi_pctil, 1)    if pd.notna(ghi_pctil)    else np.nan,
                'Flagged_GHI':         flagged_ghi,
                'Flagged':             flagged_t or flagged_ghi,
            })

        df_result = pd.DataFrame(rows)
        self.validation_selection_analysis = df_result  # store in attribute

        if verbose:
            thr_str = f"T=|{temp_diff_threshold}|°C" if temp_diff_threshold is not None else "T=off"
            if ghi_diff_threshold is not None:
                thr_str += f"  GHI=|{ghi_diff_threshold}| Wh/m²"
            w = 100
            print("\n" + "=" * w)
            print(f"  TMY SELECTION ANALYSIS  ({thr_str})")
            print("=" * w)
            fmt = "{:<12} {:>6} {:>8}  {:>9}  {:>9}  {:>8}  {:>11}  {:>11}  {:>9}  {}"
            print(fmt.format(
                "Month", "Year", "FS_Rank",
                "T_LT(°C)", "T_Sel(°C)", "T_Diff",
                "GHI_LT", "GHI_Sel", "GHI_Diff", "Flag"
            ))
            print("-" * w)
            for _, row in df_result.iterrows():
                flags = []
                if row['Flagged_T']:   flags.append("T")
                if row['Flagged_GHI']: flags.append("GHI")
                flag_str = f" *** {'+'.join(flags)}" if flags else ""
                print(fmt.format(
                    row['Month'],
                    int(row['Selected_Year']) if pd.notna(row['Selected_Year']) else "N/A",
                    f"#{int(row['FS_Rank_of_5'])}" if row['FS_Rank_of_5'] else "N/A",
                    f"{row['T_mean_LT']:.2f}"       if pd.notna(row['T_mean_LT'])       else "N/A",
                    f"{row['T_mean_Selected']:.2f}"  if pd.notna(row['T_mean_Selected'])  else "N/A",
                    f"{row['T_diff']:+.2f}"          if pd.notna(row['T_diff'])           else "N/A",
                    f"{row['GHI_mean_LT']:.1f}"      if pd.notna(row['GHI_mean_LT'])      else "N/A",
                    f"{row['GHI_mean_Selected']:.1f}"if pd.notna(row['GHI_mean_Selected'])else "N/A",
                    f"{row['GHI_diff']:+.1f}"        if pd.notna(row['GHI_diff'])         else "N/A",
                    flag_str,
                ))
            flagged_count = int(df_result['Flagged'].sum())
            print("=" * w)
            print(f"  Flagged months: {flagged_count}")
            if flagged_count:
                flagged_names = df_result[df_result['Flagged']]['Month'].tolist()
                print(f"  -> {', '.join(flagged_names)}")
            print()

        return df_result

    def correct_selection_by_temperature(self, months=None, temp_diff_threshold=1.0,
                                          regenerate=True, verbose=True):
        """
        For each specified month where the currently selected year's temperature
        deviates from the long-term mean by more than *temp_diff_threshold* °C,
        replaces it with the top-5 candidate that minimises the absolute
        difference ``abs(T_mean - T_mean_LT)``.

        After overriding selected_months, optionally regenerates and smooths the
        TMY (raw -> smoothed) in-place.

        Args:
            months (list of int, optional): Months to check. Defaults to all 12.
            temp_diff_threshold (float): Correction is applied when
                ``abs(T_selected - T_LT) > threshold``. Default 1.0 °C.
            regenerate (bool): If True (default), regenerates the TMY after
                correction (calls _create_raw_tmy + _apply_smoothing).
            verbose (bool): Print a correction report.

        Returns:
            dict: Mapping ``{month_num: {'original': year, 'corrected': year,
            'orig_diff': float, 'new_diff': float}}``. Only months that were
            actually corrected are included.

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.correct_selection_by_temperature(temp_diff_threshold=1.0)  # doctest: +SKIP
        """
        if self.selected_months is None:
            raise RuntimeError("Run generate_tmy() first.")
        if self.candidate_months is None:
            raise RuntimeError("Candidate months not available. Run step_2_select_candidate_months() first.")

        t_col = self._get_daily_t_col()
        if t_col is None:
            raise RuntimeError("Temperature column not found in df_daily.")

        if months is None:
            months = list(range(1, 13))

        corrections = {}

        for month in months:
            candidates    = self.candidate_months.get(month, [])
            original_year = self.selected_months.get(month)
            lt_data       = self.df_daily[self.df_daily.index.month == month]
            lt_mean       = lt_data[t_col].mean()

            sel_data  = lt_data[lt_data.index.year == original_year]
            orig_mean = sel_data[t_col].mean() if not sel_data.empty else np.nan
            orig_diff = abs(orig_mean - lt_mean)

            if orig_diff <= temp_diff_threshold:
                continue  # Within tolerance – no correction needed

            # Evaluate all candidates
            best_year = original_year
            best_diff = orig_diff
            for yr in candidates:
                yr_data  = lt_data[lt_data.index.year == yr]
                yr_mean  = yr_data[t_col].mean() if not yr_data.empty else np.nan
                yr_diff  = abs(yr_mean - lt_mean)
                if yr_diff < best_diff:
                    best_diff = yr_diff
                    best_year = yr

            if best_year != original_year:
                self.selected_months[month] = best_year
                corrections[month] = {
                    'original':  original_year,
                    'corrected': best_year,
                    'orig_diff': orig_diff,
                    'new_diff':  best_diff,
                }

        if corrections:
            if not hasattr(self, 'applied_corrections'):
                self.applied_corrections = {}
            self.applied_corrections.update(corrections)

        if verbose:
            print("\n" + "=" * 60)
            print(f"  CORRECTION REPORT  (threshold = |{temp_diff_threshold}| °C)")
            print("=" * 60)
            if corrections:
                for month, info in corrections.items():
                    month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
                    print(f"  {month_name:<12}  {info['original']} -> {info['corrected']}"
                          f"   |diff|: {info['orig_diff']:.2f} -> {info['new_diff']:.2f} °C")
            else:
                print("  No corrections needed within the specified months.")
            print("=" * 60 + "\n")

        if corrections and regenerate:
            print("Regenerating TMY with corrected selection...")
            self._create_raw_tmy()
            self._apply_smoothing()
            # Refresh composition table
            if self.save_validation_dfs:
                self.validation_step6_tmy_composition = self._generate_tmy_composition_dataframe()
            print("TMY regenerated successfully.")

        return corrections

    def plot_monthly_trend(self, months=None, variable=None, figsize=(14, 5),
                           title=None, show=True, show_candidates=False):
        """
        Plots the long-term temporal trend of the monthly mean for the
        specified months, highlighting the year(s) selected for the TMY with
        a star marker and drawing the linear trend line.

        Args:
            months (list of int, optional): Months to include.
                Defaults to all months (1 to 12).
            variable (str, optional): Column in df_daily to plot.
                Defaults to the temperature column (T_air_mean or T_air).
            figsize (tuple): Figure size. Default (14, 5).
            title (str, optional): Custom figure title.
            show (bool): If True (default), calls plt.show().
            show_candidates (bool): If True, plots the other top-5 candidates as grey circles,
                and highlights the previously selected candidate (if a correction was made) as a red square.

        Returns:
            matplotlib.figure.Figure

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.plot_monthly_trend(months=[1, 7], show_candidates=True)  # doctest: +SKIP
        """
        if self.df_daily is None:
            raise RuntimeError("Run step_1_load_and_prepare_data() first.")

        if months is None:
            months = list(range(1, 13))

        col = variable or self._get_daily_t_col()
        if col is None or col not in self.df_daily.columns:
            raise ValueError(f"Variable '{col}' not found in df_daily. "
                             f"Available: {self.df_daily.columns.tolist()}")

        fig, ax = plt.subplots(figsize=figsize)
        colors = plt.cm.tab10(np.linspace(0, 0.6, len(months)))

        for color, month in zip(colors, months):
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            lt_data    = self.df_daily[self.df_daily.index.month == month]
            yearly_mean = lt_data.groupby(lt_data.index.year)[col].mean()

            ax.plot(yearly_mean.index, yearly_mean.values,
                    marker='o', color=color, linewidth=1.5, alpha=0.85,
                    label=month_name)

            # Star for TMY-selected year
            selected_year = (self.selected_months or {}).get(month)
            if selected_year is not None and selected_year in yearly_mean.index:
                ax.scatter([selected_year], [yearly_mean[selected_year]],
                           s=200, marker='*', color=color, zorder=6,
                           label=f'TMY {month_name} ({selected_year})')

            # Optional: show other candidates and previously selected
            if show_candidates and self.candidate_months:
                candidates = self.candidate_months.get(month, [])
                applied_corr = getattr(self, 'applied_corrections', {}).get(month, {})
                original_year = applied_corr.get('original')

                other_cands_plotted = False
                for c_yr in candidates:
                    if c_yr == selected_year or c_yr not in yearly_mean.index:
                        continue
                        
                    if c_yr == original_year:
                        ax.scatter([c_yr], [yearly_mean[c_yr]],
                                   s=120, marker='s', edgecolors='red', facecolors='none', linewidths=2, zorder=5,
                                   label=f'Previous {month_name} ({c_yr})')
                    else:
                        lbl = 'Other Candidates' if not other_cands_plotted else None
                        ax.scatter([c_yr], [yearly_mean[c_yr]],
                                   s=60, marker='o', edgecolors='red', facecolors='none', zorder=4,
                                   label=lbl)
                        other_cands_plotted = True

        # Overall linear trend across all specified months
        summer_data = self.df_daily[self.df_daily.index.month.isin(months)]
        if col in summer_data.columns and len(summer_data) > 1:
            yearly_all = summer_data.groupby(summer_data.index.year)[col].mean()
            z = np.polyfit(yearly_all.index, yearly_all.values, 1)
            p = np.poly1d(z)
            ax.plot(yearly_all.index, p(yearly_all.index),
                    'k--', linewidth=2,
                    label=f'Trend ({z[0]:+.3f} °C/yr)')

        ax.set_xlabel('Year')
        import matplotlib.ticker as ticker
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        
        ax.set_ylabel(col.replace('_', ' '))
        ax.set_title(title or f'Long-term monthly mean trend — {col}\n'
                              f'(★ = TMY selected year)')
        
        # Deduplicate labels in legend just in case
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), fontsize=9, ncol=2)
        
        ax.grid(True, linestyle=':', alpha=0.7)
        plt.tight_layout()
        if show:
            plt.show()
        return fig

    def plot_monthly_series(self, months=None, variable=None, figsize=(20, 6),
                            title=None, show=True):
        """
        For each specified month, plots the daily series of *variable* for
        every year in the dataset.  The TMY-selected year is drawn in red with
        a thicker line; all other years are drawn in light blue.  The long-term
        daily mean (averaged across all years) is overlaid as a black dashed
        line.

        Args:
            months (list of int, optional): Months to plot. Defaults to all months (1 to 12).
            variable (str, optional): Column in df_daily. Defaults to
                temperature (T_air_mean or T_air).
            figsize (tuple): Figure size. Default (20, 6).
            title (str, optional): Custom super-title.
            show (bool): If True (default), calls plt.show().

        Returns:
            matplotlib.figure.Figure

        Example:
            >>> gen.generate_tmy()  # doctest: +SKIP
            >>> gen.plot_monthly_series(months=[1, 7])  # doctest: +SKIP
        """
        if self.df_daily is None:
            raise RuntimeError("Run step_1_load_and_prepare_data() first.")

        if months is None:
            months = list(range(1, 13))

        col = variable or self._get_daily_t_col()
        if col is None or col not in self.df_daily.columns:
            raise ValueError(f"Variable '{col}' not found in df_daily.")

        n = len(months)
        fig, axes = plt.subplots(1, n, figsize=figsize, sharey=True)
        if n == 1:
            axes = [axes]

        for ax, month in zip(axes, months):
            month_name    = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            selected_year = (self.selected_months or {}).get(month)
            lt_data       = self.df_daily[self.df_daily.index.month == month]
            all_years     = sorted(lt_data.index.year.unique())
            colors        = plt.cm.Blues(np.linspace(0.25, 0.75, len(all_years)))

            for yr, clr in zip(all_years, colors):
                yr_data = lt_data[lt_data.index.year == yr]
                if yr_data.empty:
                    continue
                is_sel  = (yr == selected_year)
                ax.plot(yr_data.index.day, yr_data[col].values,
                        color='tomato' if is_sel else clr,
                        linewidth=2.5 if is_sel else 0.7,
                        alpha=1.0 if is_sel else 0.35,
                        label=str(yr) if is_sel else None)

            # Long-term daily mean
            lt_daily_mean = lt_data.groupby(lt_data.index.day)[col].mean()
            ax.plot(lt_daily_mean.index, lt_daily_mean.values,
                    'k--', linewidth=2.0, label='Long-term mean')

            ax.set_title(f'{month_name}  (TMY → {selected_year})', fontsize=12)
            ax.set_xlabel('Day of month')
            ax.set_ylabel(col.replace('_', ' '))
            ax.legend(fontsize=9)
            ax.grid(True, linestyle=':', alpha=0.6)

        fig.suptitle(title or f'Daily {col} — all years vs. TMY selected year', fontsize=13)
        plt.tight_layout()
        if show:
            plt.show()
        return fig

    def compare_tmy_versions(self, other_tmy_df, months=None, variable=None,
                              label_self='TMY (current)', label_other='TMY (other)',
                              figsize=(20, 6), title=None, show=True):
        """
        Plots a side-by-side comparison of two TMY versions for the specified
        months.  Useful for visualising the effect of a correction applied with
        ``correct_selection_by_temperature()``.

        Args:
            other_tmy_df (pd.DataFrame): The second TMY to compare against.
                Must have a DatetimeIndex and a column named *variable*.
            months (list of int, optional): Months to compare. Defaults to all months (1 to 12).
            variable (str, optional): Column to compare. If None, the
                temperature column is auto-detected from the current TMY.
            label_self (str): Legend label for ``self.tmy_final``.
            label_other (str): Legend label for ``other_tmy_df``.
            figsize (tuple): Figure size.
            title (str, optional): Custom super-title.
            show (bool): If True (default), calls plt.show().

        Returns:
            matplotlib.figure.Figure

        Example:
            >>> other_tmy = pd.read_csv("previous_tmy.csv", index_col=0, parse_dates=True)  # doctest: +SKIP
            >>> gen.compare_tmy_versions(other_tmy, months=[1, 7])  # doctest: +SKIP
        """
        if self.tmy_final is None:
            raise RuntimeError("No TMY available on this instance. "
                               "Run generate_tmy() or step_4_create_and_smooth_tmy() first.")

        if months is None:
            months = list(range(1, 13))

        # Auto-detect variable: try to match a temperature column
        if variable is None:
            # Try common names in tmy_final
            for cand in ('T_air', 'Dry-bulb temperature', 'T_air_mean'):
                if cand in self.tmy_final.columns:
                    variable = cand
                    break
            if variable is None:
                variable = self.tmy_final.columns[0]
            print(f"Auto-detected variable for comparison: '{variable}'")

        # Verify column exists in both DataFrames
        if variable not in self.tmy_final.columns:
            raise ValueError(f"'{variable}' not found in current TMY columns: "
                             f"{self.tmy_final.columns.tolist()}")
        if variable not in other_tmy_df.columns:
            raise ValueError(f"'{variable}' not found in other_tmy_df columns: "
                             f"{other_tmy_df.columns.tolist()}")

        t_col     = self._get_daily_t_col()
        n         = len(months)
        fig, axes = plt.subplots(1, n, figsize=figsize, sharey=True)
        if n == 1:
            axes = [axes]

        for ax, month in zip(axes, months):
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')

            self_month  = self.tmy_final[self.tmy_final.index.month == month][variable]
            other_month = other_tmy_df[other_tmy_df.index.month == month][variable]

            # Resample to daily mean for cleaner visualisation
            self_daily  = self_month.resample('D').mean()
            other_daily = other_month.resample('D').mean()

            ax.plot(self_daily.index.day,  self_daily.values,
                    color='tomato',    linewidth=2.0, label=label_self)
            ax.plot(other_daily.index.day, other_daily.values,
                    color='steelblue', linewidth=2.0, linestyle='--', label=label_other)

            # Long-term mean reference
            if t_col is not None and self.df_daily is not None:
                lt_mean = self.df_daily[self.df_daily.index.month == month][t_col].mean()
                ax.axhline(lt_mean, color='black', linestyle=':', linewidth=1.5,
                           label=f'Long-term mean ({lt_mean:.1f} °C)')

            ax.set_title(month_name, fontsize=12)
            ax.set_xlabel('Day of month')
            ax.set_ylabel(variable.replace('_', ' '))
            ax.legend(fontsize=9)
            ax.grid(True, linestyle=':', alpha=0.6)

        fig.suptitle(title or f'TMY Comparison — {variable}\n'
                              f'{label_self} vs. {label_other}', fontsize=13)
        plt.tight_layout()
        if show:
            plt.show()
        return fig
