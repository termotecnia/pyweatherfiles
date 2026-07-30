# -*- coding: utf-8 -*-
"""
tmy/_assembly_smoothing.py
============================

:class:`_AssemblySmoothingMixin` — **Steps 6 & 7** of the Sandia TMY
workflow: raw TMY assembly (concatenating the 12 selected months) and
junction smoothing (fitting a smoothing spline at each of the 11
month-to-month junctions), via :meth:`sandia_step_6_assemble_tmy` /
:meth:`sandia_step_7_smooth_junctions` and their private helpers.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import os

import pandas as pd
import numpy as np
from scipy.interpolate import UnivariateSpline

from ..session_manager import save_object_session


class _AssemblySmoothingMixin:
    """Steps 6 & 7: raw TMY assembly and month-junction smoothing."""

    # --- PRIVATE METHODS (INTERNAL LOGIC) ---

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

                # --- FIX v4.08: Get the 's' value and apply smoothing ---
                # If s is automatic, capture the computed value
                if s_factor is None:
                    s_val_auto = spl.get_residual()
                    if 's_factor_auto' not in junction_params:
                        junction_params['s_factor_auto'] = {}
                    junction_params['s_factor_auto'][col] = s_val_auto

                # Aplicar el suavizado
                smoothed_y = spl(x_apply)

                tmy_final.loc[application_window_timestamps, col] = smoothed_y

            # Update the saved configuration with the automatic 's' values
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

    # --- PUBLIC WORKFLOWS ---

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
                print(f"[SESSION] Could not save the session: {_e}")

        return self

