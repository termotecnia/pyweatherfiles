# -*- coding: utf-8 -*-
"""
tmy/_core.py
=============

:class:`TMYGenerator` — the orchestrator class combining the
``_DataLoadingMixin`` (Step 1), ``_FsSelectionMixin`` (Step 2),
``_ProximityMixin`` (Step 3), ``_PersistenceMixin`` (Steps 4-5),
``_AssemblySmoothingMixin`` (Steps 6-7), ``_ValidationMixin``
(diagnostics/analysis/correction), ``_PlottingMixin`` (figures) and
``_CompatMixin`` (deprecated aliases) mixins.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6): the class itself keeps its full,
unchanged public API (``sandia_step_1_load_and_prepare`` ...
``sandia_step_7_smooth_junctions``, ``generate_tmy``, ``export_tmy``,
every ``plot_*``/``validate_*`` method, etc. are still plain methods on
``TMYGenerator``, just implemented in the mixins above it in the MRO) —
only the *implementation* moved to keep each concern in its own, more
manageable file. See ``pyweatherfiles/tmy/__init__.py`` for the
package-level overview.
"""

import os

import pandas as pd

from ._assembly_smoothing import _AssemblySmoothingMixin
from ._compat import _CompatMixin
from ._data_loading import _DataLoadingMixin
from ._fs_selection import _FsSelectionMixin
from ._persistence import _PersistenceMixin
from ._plotting import _PlottingMixin
from ._proximity import _ProximityMixin
from ._validation import _ValidationMixin


class TMYGenerator(
    _DataLoadingMixin,
    _FsSelectionMixin,
    _ProximityMixin,
    _PersistenceMixin,
    _AssemblySmoothingMixin,
    _ValidationMixin,
    _PlottingMixin,
    _CompatMixin,
):
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

    # --- PUBLIC WORKFLOWS ---

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

