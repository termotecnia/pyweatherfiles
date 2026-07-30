# -*- coding: utf-8 -*-
"""
tmy/_fs_selection.py
======================

:class:`_FsSelectionMixin` — **Step 2** of the Sandia TMY workflow: the
Finkelstein-Schafer (FS) statistic and candidate-month selection
(:meth:`sandia_step_2_select_candidates_fs` and its private helpers).

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import pandas as pd
import numpy as np


class _FsSelectionMixin:
    """Step 2: Finkelstein-Schafer candidate selection."""

    # --- PRIVATE METHODS (INTERNAL LOGIC) ---

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

    # --- PUBLIC WORKFLOWS ---

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

