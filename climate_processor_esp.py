# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import pvlib
import time
import os


class ProcesadorClimatico:
    def __init__(self, file_path, lat, lon, alt):
        self.file_path = file_path
        self.lat = lat
        self.lon = lon
        self.alt = alt

        # Variables de estado interno
        self.df = None
        self.df_before = None
        self.cols_trabajo = []
        self.antes = {}
        self.despues = {}
        self.summary = None
        self.gaps_df = None
        self.stats_anuales = None
        self.max_gaps_df = None

        # Ejecutar el flujo de datos completo al instanciar
        self._log("Inicializando Procesador Climático...")
        self._procesar_todo()

    def _log(self, msg):
        print(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {msg}")

    def _procesar_todo(self):
        """Ejecuta toda la lógica original en el orden correcto."""
        self._cargar_datos()
        self._mapear_variables()
        self._calcular_disponibilidad_antes()
        self._reindexar()
        self._rellenar_datos()
        self._calcular_disponibilidad_despues()
        self._generar_tablas_estadisticas()
        self._log("Procesamiento interno COMPLETADO ✓")

    # -------------------------------------------------------
    # 1. CARGA Y MAPEO
    # -------------------------------------------------------
    def _cargar_datos(self):
        self._log("Cargando archivo de datos...")
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

    def _mapear_variables(self):
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
        self.cols_trabajo = [k for k, v in cols_map.items() if v is not None]

    def _calcular_disponibilidad_antes(self):
        for col in self.cols_trabajo:
            self.antes[col] = self.df[col].notna().mean() * 100

    def _reindexar(self):
        self._log("Reindexando a horas completas...")
        full_index = pd.date_range(self.df.index.min(), self.df.index.max(), freq='h')
        self.df = self.df.reindex(full_index)
        self.df_before = self.df_before.reindex(full_index)
        self.df.index.name = 'time'
        self.df_before.index.name = 'time'

    # -------------------------------------------------------
    # 2. LÓGICA DE RELLENO (Idéntica al original)
    # -------------------------------------------------------
    def _rellenar_datos(self):
        t0 = time.time()

        # 1. Pressure
        if 'Pressure' in self.df.columns:
            self.df['Pressure'] = self.df['Pressure'].interpolate(method='linear', limit=72)

        # 2. Temperaturas
        for col in ['Dry-bulb', 'Dew Point']:
            if col in self.df.columns:
                self.df[col] = self._spline_limit(self.df[col], max_gap=24)

        # 3. Humedad
        if 'RH' in self.df.columns and 'Dry-bulb' in self.df.columns and 'Dew Point' in self.df.columns:
            mask = self.df['RH'].isna() & self.df['Dry-bulb'].notna() & self.df['Dew Point'].notna()
            T = self.df.loc[mask, 'Dry-bulb']
            Td = self.df.loc[mask, 'Dew Point']
            self.df.loc[mask, 'RH'] = (100 * np.exp(17.625 * Td / (243.04 + Td)) / np.exp(17.625 * T / (243.04 + T))).clip(0, 100)
            self.df['RH'] = self.df['RH'].interpolate(method='linear', limit=24)

        # 4. Viento
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
        es_dia = GHIc > 5

        for col, ref in [('GHI', GHIc), ('DHI', DHIc), ('BNI', BNIc)]:
            if col not in self.df.columns: continue
            self.df[col] = self.df[col].interpolate(method='linear', limit=3)
            mask_medio = self._gap_size(self.df[col]).between(3, 24) & es_dia
            if mask_medio.any():
                kt = (self.df[col] / ref.replace(0, np.nan)).clip(0, 1.2)
                kt_med = kt.rolling(24, min_periods=6, center=True).median()
                self.df.loc[mask_medio, col] = (ref[mask_medio] * kt_med[mask_medio]).clip(0)
            self.df.loc[~es_dia, col] = self.df.loc[~es_dia, col].fillna(0)

        if {'GHI', 'DHI'}.issubset(self.df.columns):
            self.df['BHI'] = (self.df['GHI'] - self.df['DHI']).clip(lower=0)

        self._log(f"Relleno completado en {time.time() - t0:5.1f}s")

    def _calcular_disponibilidad_despues(self):
        for col in self.cols_trabajo:
            self.despues[col] = self.df[col].notna().mean() * 100

        self.summary = pd.DataFrame({
            'Variable': self.cols_trabajo,
            'Before_%': [self.antes[c] for c in self.cols_trabajo],
            'After_%': [self.despues[c] for c in self.cols_trabajo],
            'Gain_%': [self.despues[c] - self.antes[c] for c in self.cols_trabajo]
        })

    def _generar_tablas_estadisticas(self):
        self._log("Calculando tablas estadísticas...")
        # 1. Gaps_df
        records = []
        for col in self.cols_trabajo:
            if col in self.df.columns and col in self.df_before.columns:
                records.extend(self._gaps_interpolated(self.df_before, self.df, col))
        self.gaps_df = pd.DataFrame(records)

        # 2. Stats Anuales
        self.stats_anuales = self._calculate_annual_stats(self.df_before, self.df, self.cols_trabajo)

        # 3. Max Gaps
        self.max_gaps_df = self._gaps_stats_periodos(self.df_before, self.cols_trabajo)

    # -------------------------------------------------------
    # 3. FUNCIONES AUXILIARES (Exactamente las originales)
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

    def _calculate_annual_stats(self, df_before, df, cols_trabajo):
        stats_list = []
        for col in cols_trabajo:
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
                    return 'Completos'
                elif row['nans_after'] == row['size_before']:
                    return 'No rellenado'
                else:
                    return 'Parciales'

            gap_agg['estado'] = gap_agg.apply(classify_gap, axis=1)

            for year, group in gap_agg.groupby('year'):
                total_huecos = len(group)
                rellenados = len(group[group['estado'] == 'Completos'])
                no_rellenados = len(group[group['estado'] == 'No rellenado'])
                parciales = len(group[group['estado'] == 'Parciales'])

                horas_originales = group['size_before'].sum()
                horas_quedan = group['nans_after'].sum()
                horas_rellenadas = horas_originales - horas_quedan

                stats_list.append({
                    'year': year,
                    'Variable': col,
                    'Total_Huecos': total_huecos,
                    'Rellenados_100%': rellenados,
                    'Parciales': parciales,
                    'No_Rellenados': no_rellenados,
                    'Horas_Orig_Faltan': horas_originales,
                    'Horas_Rellenadas': horas_rellenadas,
                    'Horas_Siguen_Vacias': horas_quedan
                })

        df_stats = pd.DataFrame(stats_list)
        if df_stats.empty: return df_stats

        df_stats = df_stats.set_index(['year', 'Variable'])
        df_stats['Días_año'] = [366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365 for y in df_stats.index.get_level_values(0)]
        df_stats['Promedio_h_relleno/día'] = (df_stats['Horas_Rellenadas'] / df_stats['Días_año']).round(2)

        return df_stats

    def _gaps_stats_periodos(self, df_before, cols_trabajo):
        max_gaps = []
        limites_interpolacion = {'Pressure': 72, 'Dry-bulb': 24, 'Dew Point': 24, 'RH': 24,
                                 'WindSpeed': 3, 'WindDir': 2, 'GHI': 24, 'BHI': 24, 'DHI': 24, 'BNI': 24}

        for col in cols_trabajo:
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
            limite = limites_interpolacion.get(col, 0)

            for y, group in gaps_info.groupby('year'):
                idx_max = group['size'].idxmax()
                row = group.loc[idx_max]
                tamano = int(row['size'])
                estado = "RELLENADO" if tamano <= limite else f"NO RELLENADO (>{limite}h)"
                max_gaps.append({'Variable': col, 'Tipo': 'AÑO', 'Periodo': y, 'Max_hueco_horas': tamano, 'Inicio': row['start'], 'Fin': row['end'], 'Estado_Relleno': estado})

            for m, group in gaps_info.groupby('month'):
                idx_max = group['size'].idxmax()
                row = group.loc[idx_max]
                tamano = int(row['size'])
                estado = "RELLENADO" if tamano <= limite else f"NO RELLENADO (>{limite}h)"
                max_gaps.append({'Variable': col, 'Tipo': 'MES', 'Periodo': m, 'Max_hueco_horas': tamano, 'Inicio': row['start'], 'Fin': row['end'], 'Estado_Relleno': estado})

        return pd.DataFrame(max_gaps)

    # -------------------------------------------------------
    # 4. LOS 3 MÉTODOS PÚBLICOS SOLICITADOS (Generan XLSX)
    # -------------------------------------------------------
    def exportar_datos_rellenados(self, output_name='Sevilla_RELLENADO.xlsx'):
        """1. Exporta únicamente el dataframe rellenado final"""
        self._log(f"Guardando {output_name}...")
        self.df[self.cols_trabajo].reset_index().to_excel(output_name, index=False)
        return output_name

    def exportar_estadisticas_anuales(self, output_name='ESTADISTICAS_ANUALES.xlsx'):
        """2. Exporta el reporte de calidad y estadísticas por año/mes"""
        self._log(f"Guardando {output_name}...")
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            if not self.stats_anuales.empty:
                self.stats_anuales.to_excel(writer, sheet_name='stats_anuales')
            if not self.max_gaps_df.empty:
                self.max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)
        return output_name

    def exportar_reporte_completo(self, output_name='Sevilla_RELLENADO_con_gaps.xlsx'):
        """3. Exporta el excel con todas las hojas del proceso (Datos, Resumen, Gaps y Estadísticas)"""
        self._log(f"Guardando {output_name}...")
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            self.df[self.cols_trabajo].reset_index().to_excel(writer, sheet_name='rellenado', index=False)
            if self.summary is not None:
                self.summary.to_excel(writer, sheet_name='summary', index=False)
            if not self.gaps_df.empty:
                self.gaps_df.to_excel(writer, sheet_name='gaps', index=False)
            if not self.stats_anuales.empty:
                self.stats_anuales.to_excel(writer, sheet_name='stats_anuales')
            if not self.max_gaps_df.empty:
                self.max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)
        return output_name