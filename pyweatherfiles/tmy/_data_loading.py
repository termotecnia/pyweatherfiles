# -*- coding: utf-8 -*-
"""
tmy/_data_loading.py
=====================

:class:`_DataLoadingMixin` — **Step 1** of the Sandia TMY workflow: loading
and preparing the raw weather data (:meth:`sandia_step_1_load_and_prepare`
and its private helper :meth:`_load_and_prepare_real_data`).

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import pandas as pd


class _DataLoadingMixin:
    """Step 1: load the source file(s), map columns, resample and compute
    daily aggregates."""

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

