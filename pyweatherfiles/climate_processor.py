# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import pvlib
import time
import os


class ClimateProcessor:
    def __init__(self, file_path, lat, lon, alt):
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
        print(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {msg}")

    def _process_all(self):
        """Executes all original logic in the correct order."""
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
        for col in self.working_cols:
            self.before_availability[col] = self.df[col].notna().mean() * 100

    def _reindex(self):
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
        for col in self.working_cols:
            self.after_availability[col] = self.df[col].notna().mean() * 100

        self.summary = pd.DataFrame({
            'Variable': self.working_cols,
            'Before_%': [self.before_availability[c] for c in self.working_cols],
            'After_%': [self.after_availability[c] for c in self.working_cols],
            'Gain_%': [self.after_availability[c] - self.before_availability[c] for c in self.working_cols]
        })

    def _generate_statistics_tables(self):
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
        is_nan = series.isna()
        gap_id = (~is_nan).cumsum()
        return is_nan.groupby(gap_id).transform('sum').where(is_nan, 0)

    def _spline_limit(self, series, max_gap):
        s = series.copy()
        gaps = self._gap_size(s)
        mask_gap = (gaps > 0) & (gaps <= max_gap)
        if not mask_gap.any():
            return s
        s_spline = s.interpolate(method='spline', order=3, limit=max_gap, limit_direction='both')
        s.loc[mask_gap] = s_spline.loc[mask_gap]
        return s

    def _gaps_interpolated(self, original, filled, var_name):
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
        """1. Exports only the final filled dataframe"""
        self._log(f"Saving {output_name}...")
        self.df[self.working_cols].reset_index().to_excel(output_name, index=False)
        return output_name

    def export_annual_statistics(self, output_name='ANNUAL_STATISTICS.xlsx'):
        """2. Exports the quality report and statistics by year/month"""
        self._log(f"Saving {output_name}...")
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            if not self.annual_stats.empty:
                self.annual_stats.to_excel(writer, sheet_name='annual_stats')
            if not self.max_gaps_df.empty:
                self.max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)
        return output_name

    def export_complete_report(self, output_name='FILLED_with_gaps_report.xlsx'):
        """3. Exports the excel with all process sheets (Data, Summary, Gaps, and Stats)"""
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