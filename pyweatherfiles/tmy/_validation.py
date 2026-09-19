# -*- coding: utf-8 -*-
"""
tmy/_validation.py
====================

:class:`_ValidationMixin` — diagnostic/validation methods
(``validate_step_1_data_loading``, ``validate_fs_calculation``,
``validate_full_ranking_for_month``, ``validate_persistence_selection``,
``validate_step_4_final_tmy``, ``summarize_fs_results``,
``check_input_expectations``) plus the v4.09 "analysis & correction" methods
(``get_candidate_stats``, ``generate_full_summary``, ``analyze_selection``,
``correct_selection_by_temperature``) of
:class:`~pyweatherfiles.tmy.TMYGenerator`.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import pandas as pd
import numpy as np


class _ValidationMixin:
    """Diagnostic/validation methods and the v4.09 analysis & correction
    methods."""

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

        print(f"\nExpected Variables: {expected_internal}")

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
            print("\nResult: All expected columns found exactly and time format is valid!")
        else:
            if missing_exact:
                print(f"\nResult: Missing exact matches for: {missing_exact}")
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
            # Re-smooth with the exact settings used the first time (Step 7),
            # instead of silently reverting to the method defaults.
            self._apply_smoothing(**(getattr(self, '_last_smoothing_kwargs', None) or {}))
            # Refresh composition table
            if self.save_validation_dfs:
                self.validation_step6_tmy_composition = self._generate_tmy_composition_dataframe()
            print("TMY regenerated successfully.")

        return corrections

