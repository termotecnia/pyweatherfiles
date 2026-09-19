# -*- coding: utf-8 -*-
"""
tmy/_plotting.py
==================

:class:`_PlottingMixin` — every ``plot_*``/``compare_tmy_versions`` matplotlib
visualization method of :class:`~pyweatherfiles.tmy.TMYGenerator` (CDF
comparisons, month-junction/smoothing inspection, persistence runs, monthly
means/CDFs, long-term monthly trends, and TMY-version comparison).

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


class _PlottingMixin:
    """Every ``plot_*`` visualization method."""

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

        default_params = {'hours_before': 6, 'hours_after': 6, 's_factor': 'auto'}


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

            # Check if an automatic value was used and is available
            s_auto_val = junction_params.get('s_factor_auto', {}).get(var)

            if s_factor_val is None or isinstance(s_factor_val, str):
                # 'auto' (variance-normalized) or None (SciPy's own criterion):
                # show the value actually computed for this variable, if known.
                if s_auto_val is not None:
                    s_factor_str = f"{s_auto_val:.3g} (auto)"
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

            # --- Updated line style ---
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

