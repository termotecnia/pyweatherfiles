import pandas as pd
import numpy as np
import math
import os

try:
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    from ladybug.analysisperiod import AnalysisPeriod
except ImportError:
    raise ImportError("La librería 'ladybug-core' no está instalada.")

try:
    import pvlib
except ImportError:
    raise ImportError("La librería 'pvlib' no está instalada.")


class HourlyEPWConverter:
    """
    Clase para leer archivos climáticos horarios, analizar huecos, rellenar datos faltantes
    y exportarlos a formato EPW inhabilitando las variables no requeridas (obsoletas).
    """
    
    def __init__(self, file_path, lat, lon, elev, tz_hour,
                 datetime_col='DATETIME_UTC', 
                 col_temp='Dry-bulb temperature', 
                 col_dew='Dew Point temperature', 
                 col_wind='Wind speed', 
                 col_ghi='GHI', 
                 col_dni='BNI/DNI',
                 col_rh=None,
                 col_dhi=None,
                 col_bhi=None):
        
        # Atributos geográficos
        self.file_path = file_path
        self.lat = lat
        self.lon = lon
        self.elev = elev
        self.tz_hour = tz_hour
        
        # Mapeo de columnas
        self.datetime_col = datetime_col
        self.col_temp = col_temp
        self.col_dew = col_dew
        self.col_wind = col_wind
        self.col_ghi = col_ghi
        self.col_dni = col_dni
        self.col_rh = col_rh
        self.col_dhi = col_dhi
        self.col_bhi = col_bhi
        
        # Atributos de datos
        self.df = None
        self.available_years = []
        
        # Inicialización automática
        self._load_file()

    def _load_file(self):
        """Lee el archivo climático, reindexando a horas completas para asegurar
        continuidad temporal (elimina saltos de hora que confunden la interpolación)."""
        if getattr(self, "file_path", "").endswith('.xlsx'):
            self.df = pd.read_excel(self.file_path)
        else:
            self.df = pd.read_csv(self.file_path)
            
        if not pd.api.types.is_datetime64_any_dtype(self.df[self.datetime_col]):
            self.df[self.datetime_col] = pd.to_datetime(self.df[self.datetime_col])

        # --- FIX 1: Reindexar a horas completas ---
        # Si en el Excel original falta la fila entera de una hora (p.ej. pasa de
        # 01:00 a 03:00 sin la fila 02:00), Pandas cuenta "filas" y no "horas" al
        # interpolar. El reindex inserta esas filas vacías (NaN) antes de rellenar.
        self.df = self.df.set_index(self.datetime_col).sort_index()
        full_index = pd.date_range(self.df.index.min(), self.df.index.max(), freq='h')
        self.df = self.df.reindex(full_index)
        self.df.index.name = self.datetime_col
        self.df = self.df.reset_index()
        
        # Guardar en atributo los años disponibles
        self.available_years = sorted(self.df[self.datetime_col].dt.year.unique().tolist())

    def get_missing_data_stats(self):
        """
        Analiza el DataFrame climático y proporciona estadísticas sobre los valores faltantes.
        Devuelve un DataFrame donde cada fila es un año, muy útil para decidir
        si descartar un año completo.
        """
        stats = []
        cols_to_check = [c for c in self.df.columns if c != self.datetime_col]
        
        for year in self.available_years:
            df_year = self.df[self.df[self.datetime_col].dt.year == year]
            
            stat = {
                'Año': year,
                'Horas_Totales': len(df_year),
            }
            
            col_limits = {}
            for col in cols_to_check:
                # FIX 2: el límite de temperatura es 12h (no 24h)
                if col in [self.col_temp, self.col_dew]: col_limits[col] = 12
                elif col in [self.col_ghi, self.col_dni, self.col_dhi, self.col_bhi]: col_limits[col] = 24
                elif col == self.col_wind: col_limits[col] = 3
                elif 'pressure' in col.lower(): col_limits[col] = 72
                elif 'dir' in col.lower(): col_limits[col] = 2
                elif 'speed' in col.lower(): col_limits[col] = 3
                elif col == self.col_rh or (col is not None and ('rh' in str(col).lower() or 'humidity' in str(col).lower())): col_limits[col] = 24
                else: col_limits[col] = 24

            missing_total_sum = 0
            is_valid = True
            for col in cols_to_check:
                is_nan = df_year[col].isnull()
                total_missing = is_nan.sum()
                missing_total_sum += total_missing
                
                # Calcular rachas máximas de NaN consecutivos
                consec = is_nan.groupby((~is_nan).cumsum()).sum()
                max_consec = int(consec.max()) if len(consec) > 0 else 0
                
                if max_consec > col_limits.get(col, 24):
                    is_valid = False
                
                stat[f'{col}_Faltantes'] = total_missing
                stat[f'{col}_Max_Consecutivos'] = max_consec
                
            stat['Total_Faltantes'] = missing_total_sum
            stat['Valido_Para_EPW'] = is_valid
            stats.append(stat)
            
        return pd.DataFrame(stats)

    def get_year_data(self, year):
        """Devuelve un DataFrame aislado con los datos de un año específico."""
        if year not in self.available_years:
            raise ValueError(f"El año {year} no está disponible en este archivo.")
        return self.df[self.df[self.datetime_col].dt.year == year].copy()

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

    def fill_missing_values(self, df_year, max_interpolate_limit=24, profile_method='window', window_weeks=2):
        """
        Rellena los valores faltantes en un dataframe aislado (ej. de 1 año).
        
        Método:
        1. Interpolaciones específicas por variable (lineal, spline o modelo clearsky).
        2. Perfil típico basado en la mediana de ese mismo mes/hora a lo largo de los demás datos ('monthly'),
           o en una ventana temporal de un número de semanas parametrizable ('window').
        3. Mediana global como fallback de seguridad extrema.
        """
        df_filled = df_year.copy()
        
        cols_to_fill = [c for c in df_filled.columns if c != self.datetime_col]
        df_filled = df_filled.sort_values(by=self.datetime_col).reset_index(drop=True)
        
        # 1. Rellenos específicos según variable

        # FIX 2: spline cúbico con límite 12h para temperaturas
        for col in [self.col_temp, self.col_dew]:
            if col in df_filled.columns:
                df_filled[col] = self._spline_limit(df_filled[col], max_gap=12)

        # FIX 4: Humedad relativa — primero por psicrometría donde hay T y Td,
        #         luego interpolación lineal ≤24h para los huecos restantes
        if self.col_rh and self.col_rh in df_filled.columns:
            if self.col_temp in df_filled.columns and self.col_dew in df_filled.columns:
                mask_rh = (df_filled[self.col_rh].isna() &
                           df_filled[self.col_temp].notna() &
                           df_filled[self.col_dew].notna())
                T  = df_filled.loc[mask_rh, self.col_temp]
                Td = df_filled.loc[mask_rh, self.col_dew]
                df_filled.loc[mask_rh, self.col_rh] = (
                    100 * np.exp(17.625 * Td / (243.04 + Td)) /
                          np.exp(17.625 * T  / (243.04 + T ))
                ).clip(0, 100)
            df_filled[self.col_rh] = df_filled[self.col_rh].interpolate(method='linear', limit=24)

        if self.col_wind in df_filled.columns:
            df_filled[self.col_wind] = df_filled[self.col_wind].interpolate(method='linear', limit=3)

        # FIX 3: solar — GHI, DNI/BNI y DHI con kt-clearsky; BHI = GHI - DHI
        has_solar = self.col_ghi in df_filled.columns or self.col_dni in df_filled.columns
        if has_solar:
            location = pvlib.location.Location(self.lat, self.lon, tz='UTC', altitude=self.elev)
            times_utc = pd.DatetimeIndex(df_filled[self.datetime_col])
            if times_utc.tz is None:
                times_utc = times_utc.tz_localize('UTC')
            cs = location.get_clearsky(times_utc)
            GHIc = pd.Series(cs['ghi'].values, index=df_filled.index)
            BNIc = pd.Series(cs['dni'].values, index=df_filled.index)
            DHIc = pd.Series(cs['dhi'].values, index=df_filled.index)
            es_dia = GHIc > 5

            solar_cols = []
            if self.col_ghi in df_filled.columns: solar_cols.append((self.col_ghi, GHIc))
            if self.col_dni in df_filled.columns: solar_cols.append((self.col_dni, BNIc))
            if self.col_dhi and self.col_dhi in df_filled.columns:
                solar_cols.append((self.col_dhi, DHIc))

            for col, ref in solar_cols:
                df_filled[col] = df_filled[col].interpolate(method='linear', limit=3)
                mask_medio = self._gap_size(df_filled[col]).between(3, 24) & es_dia
                if mask_medio.any():
                    kt = (df_filled[col] / ref.replace(0, np.nan)).clip(0, 1.2)
                    kt_med = kt.rolling(24, min_periods=6, center=True).median()
                    df_filled.loc[mask_medio, col] = (ref[mask_medio] * kt_med[mask_medio]).clip(lower=0)
                df_filled.loc[~es_dia, col] = df_filled.loc[~es_dia, col].fillna(0)

            # BHI = GHI - DHI (calculado tras rellenar ambas)
            if (self.col_bhi and self.col_bhi in df_filled.columns and
                    self.col_ghi in df_filled.columns and self.col_dhi and self.col_dhi in df_filled.columns):
                df_filled[self.col_bhi] = (df_filled[self.col_ghi] - df_filled[self.col_dhi]).clip(lower=0)

        for col in cols_to_fill:
            skip = [self.col_temp, self.col_dew, self.col_wind, self.col_ghi,
                    self.col_dni, self.col_rh, self.col_dhi, self.col_bhi]
            if col not in skip:
                limit = 24
                if 'pressure' in str(col).lower(): limit = 72
                elif 'dir' in str(col).lower(): limit = 2
                df_filled[col] = df_filled[col].interpolate(method='linear', limit=limit)
            
        # 2. Perfiles horarios (mensual o por ventana)
        df_filled['_hour'] = df_filled[self.datetime_col].dt.hour
        if profile_method == 'monthly':
            df_filled['_month'] = df_filled[self.datetime_col].dt.month
            df_filled['_weekday'] = df_filled[self.datetime_col].dt.weekday
            group_cols = ['_month', '_weekday', '_hour']
        elif profile_method == 'window':
            df_filled['_weekday'] = df_filled[self.datetime_col].dt.weekday
            group_cols = ['_weekday', '_hour']
            
            window_elements = 2 * window_weeks + 1
            pad_size = window_weeks
            
            def circular_rolling_median(x):
                vals = x.values
                n = len(vals)
                if n == 0:
                    return x
                if n <= window_elements:
                    return pd.Series(x.median(), index=x.index)
                    
                padded = np.concatenate([vals[-pad_size:], vals, vals[:pad_size]])
                rolled = pd.Series(padded).rolling(window=window_elements, center=True, min_periods=1).median()
                return pd.Series(rolled.iloc[pad_size : pad_size + n].values, index=x.index)
        
        for col in cols_to_fill:
            if df_filled[col].isnull().any():
                if profile_method == 'monthly':
                    median_profile = df_filled.groupby(group_cols)[col].transform('median')
                elif profile_method == 'window':
                    median_profile = df_filled.groupby(group_cols)[col].transform(circular_rolling_median)
                else:
                    raise ValueError("parameter 'profile_method' must be 'monthly' or 'window'")
                    
                df_filled[col] = df_filled[col].fillna(median_profile)
                
                # 3. Fallback en caso extremo
                if df_filled[col].isnull().any():
                    df_filled[col] = df_filled[col].fillna(df_filled[col].median())
                    
        if '_month' in df_filled.columns:
            df_filled = df_filled.drop(columns=['_month'])
        if '_weekday' in df_filled.columns:
            df_filled = df_filled.drop(columns=['_weekday'])
        df_filled = df_filled.drop(columns=['_hour'])
        return df_filled

    def _calculate_rh(self, tdb, tdp):
        """Cálculo interno Psicométrico de HR"""
        if pd.isna(tdb) or pd.isna(tdp): 
            return 50.0
        if tdp > tdb:
            tdp = tdb
        es = 6.112 * math.exp((17.67 * tdb) / (tdb + 243.5))
        e = 6.112 * math.exp((17.67 * tdp) / (tdp + 243.5))
        rh = (e / es) * 100.0
        return min(max(rh, 0.0), 100.0)

    def _calculate_atmos_pressure(self):
        """Cálculo de la presión atmosférica basado en su elevación"""
        p0 = 101325
        L = 0.0065
        T0 = 288.15
        g = 9.80665
        M = 0.0289644
        R = 8.31447
        return p0 * (1 - (L * self.elev) / T0) ** ((g * M) / (R * L))

    def _set_epw_values(self, epw_obj, field_name, new_vals):
        """Asigna valores a un campo compensando el desfase interno de Ladybug"""
        field = getattr(epw_obj, field_name)
        if field.header.data_type.point_in_time:
            shifted = [new_vals[-1]] + list(new_vals[:-1])
            field.values = tuple(shifted) if isinstance(field.values, tuple) else list(shifted)
        else:
            field.values = tuple(new_vals) if isinstance(field.values, tuple) else list(new_vals)

    def transform_to_epw(self, df_year_filled, base_epw_path, output_epw_path, remove_leap_day=True):
        """
        Traslada los valores del DataFrame a un archivo .epw que sirve de base,
        realizando cálculos (DHI, Psicometría, Atmosférica) y desactivando las variables obsoletas.
        """
        df_y = df_year_filled.copy()
        df_y = df_y.sort_values(by=self.datetime_col).reset_index(drop=True)

        # Filtro de bisiestos (Feb 29)
        is_leap_day = (df_y[self.datetime_col].dt.month == 2) & (df_y[self.datetime_col].dt.day == 29)
        has_leap_day = is_leap_day.any()
        
        if remove_leap_day and has_leap_day:
            df_y = df_y[~is_leap_day].reset_index(drop=True)
            has_leap_day = False
            
        expected_len = 8784 if has_leap_day else 8760
        if len(df_y) < expected_len:
            print(f"Advertencia: El año proporcionado solo tiene {len(df_y)} horas disponibles (se esperaban {expected_len}).")
        elif len(df_y) > expected_len:
            df_y = df_y.head(expected_len)

        # Carga EPW Base
        try:
            epw_data = EPW(base_epw_path)
        except Exception as e:
            print(f"Error al cargar base EPW '{base_epw_path}': {e}")
            return False

        # Actualización de Headers
        epw_data.location.latitude = self.lat
        epw_data.location.longitude = self.lon
        epw_data.location.time_zone = self.tz_hour
        epw_data.location.elevation = self.elev
        epw_data.comments_1 = f"Convertido automáticamente desde archivo horario a partir de plantilla {os.path.basename(base_epw_path)}"
        
        try:
            epw_data._analysis_period = AnalysisPeriod(st_month=1, st_day=1, st_hour=1, end_month=12, end_day=31, end_hour=24)
            epw_data._is_leap_year = bool(has_leap_day)
        except Exception:
            pass

        # Extracción a variables
        t_db = df_y[self.col_temp].tolist()
        t_dp = df_y[self.col_dew].tolist()
        wind_spd = df_y[self.col_wind].tolist()
        ghi = df_y[self.col_ghi].tolist()
        dni = df_y[self.col_dni].tolist()
        dates = df_y[self.datetime_col].tolist()

        wind_dir = [0] * len(df_y)
        if self.col_rh and self.col_rh in df_y.columns:
            rel_hum = df_y[self.col_rh].tolist()
        else:
            rel_hum = [self._calculate_rh(tdb, tdp) for tdb, tdp in zip(t_db, t_dp)]
        p_atm = [self._calculate_atmos_pressure()] * len(df_y)

        # Cálculo de Irradiancia Difusa (DHI)
        if self.col_dhi and self.col_dhi in df_y.columns:
            dhi_values = df_y[self.col_dhi].tolist()
        else:
            # Empleando Sunpath como fallback
            sp = Sunpath(latitude=self.lat, longitude=self.lon, time_zone=self.tz_hour)
            dhi_values = []
            
            for i in range(len(df_y)):
                dt = pd.to_datetime(dates[i])
                m, d, h = dt.month, dt.day, dt.hour 
                
                calc_hour = float(h) + 0.5
                if calc_hour >= 24.0:
                    calc_hour -= 24.0
                    
                sun = sp.calculate_sun(month=m, day=d, hour=calc_hour)
                zenith_deg = 90.0 - sun.altitude
                cos_zenith = math.cos(math.radians(zenith_deg))
                
                val_ghi, val_dni = ghi[i], dni[i]
                if cos_zenith <= 0.01:
                    val_dhi = val_ghi
                else:
                    val_dhi = val_ghi - val_dni * cos_zenith
                    
                dhi_values.append(max(0.0, float(val_dhi)))

        # Inyección de datos al objeto Ladybug
        self._set_epw_values(epw_data, 'dry_bulb_temperature', t_db)
        self._set_epw_values(epw_data, 'dew_point_temperature', t_dp)
        self._set_epw_values(epw_data, 'relative_humidity', rel_hum)
        self._set_epw_values(epw_data, 'wind_speed', wind_spd)
        self._set_epw_values(epw_data, 'wind_direction', wind_dir)
        self._set_epw_values(epw_data, 'global_horizontal_radiation', ghi)
        self._set_epw_values(epw_data, 'direct_normal_radiation', dni)
        self._set_epw_values(epw_data, 'diffuse_horizontal_radiation', dhi_values)
        self._set_epw_values(epw_data, 'atmospheric_station_pressure', p_atm)

        # Desactivación de variables obsoletas de EnergyPlus
        unused_fields_mapping = {
            'extraterrestrial_horizontal_radiation': 9999,
            'extraterrestrial_direct_normal_radiation': 9999,
            'global_horizontal_illuminance': 999999,
            'direct_normal_illuminance': 999999,
            'diffuse_horizontal_illuminance': 999999,
            'zenith_luminance': 9999,
            'total_sky_cover': 99,
            'opaque_sky_cover': 99,
            'visibility': 9999,
            'ceiling_height': 99999,
            'precipitable_water': 999,
            'aerosol_optical_depth': 0.999,
            'days_since_last_snowfall': 99,
            'albedo': 999,
            'liquid_precipitation_quantity': 99
        }
        num_rows = len(df_y)
        for field_name, missing_val in unused_fields_mapping.items():
            if hasattr(epw_data, field_name):
                field_obj = getattr(epw_data, field_name)
                replacement_list = [missing_val] * num_rows
                
                if hasattr(field_obj, 'header') and hasattr(field_obj, 'values'):
                    self._set_epw_values(epw_data, field_name, replacement_list)
                else:
                    try:
                        setattr(epw_data, field_name, tuple(replacement_list))
                    except Exception:
                        pass

        # Guardado del EPW en disco
        try:
            epw_data.save(output_epw_path)
            return True
        except Exception as e:
            print(f"Error al guardar el EPW de salida: {e}")
            return False

    def process(self, base_epw_path, output_dir=".", years=None, output_pattern=None, max_interpolate_limit=24, 
                profile_method='monthly', window_weeks=2, remove_leap_day=True, **pattern_kwargs):
        """
        Método directo ("todo en uno") que automatiza el proceso completo.
        Toma una lista de años (o todos si no se especifican), les rellena 
        huecos y genera un EPW para cada uno.
        
        Permite customizar el nombre de salida a través de `output_pattern`.
        Ejemplo: output_pattern="{ciudad}_{zona_climatica}_{year}.epw", ciudad="Sevilla", zona_climatica="B4"
        Si no se provee, el patrón por defecto es "{basename}_{year}_convertido.epw".
        
        También admite todos los argumentos de los métodos paso a paso:
        - max_interpolate_limit: Límite de interpolación de llenado de huecos.
        - profile_method: Método para perfiles base en caso de huecos grandes ('monthly' o 'window').
        - window_weeks: Semanas antes y después para profile_method='window'.
        - remove_leap_day: Si True, elimina el 29 de febrero de los años bisiestos (por defecto True).
        """
        if years is None:
            years = self.available_years
            
        if output_pattern is None:
            output_pattern = "{basename}_{year}_convertido.epw"
            
        # Extraemos el nombre del archivo sin extensión como el 'basename' por defecto
        basename = os.path.splitext(os.path.basename(self.file_path))[0]
        pattern_kwargs['basename'] = basename
            
        success_list = []
        for year in years:
            if year not in self.available_years:
                print(f"Año {year} no hallado en los datos. Ignorando...")
                continue
                
            print(f"\n--- Procesando año {year} de forma directa ---")
            
            # Verificación de validación de huecos máximos consecutivos
            # (se recalcula una sola vez fuera del bucle si ya fue llamado antes,
            #  pero aquí lo dejamos inline para que process() sea autocontenido)
            stats_df = self.get_missing_data_stats()
            year_row = stats_df[stats_df['Año'] == year]
            if year_row.empty or not year_row.iloc[0]['Valido_Para_EPW']:
                print(f"Descartando año {year} porque excede los huecos máximos consecutivos permitidos.")
                continue

            df_year = self.get_year_data(year)
            df_filled = self.fill_missing_values(df_year, max_interpolate_limit=max_interpolate_limit, 
                                                 profile_method=profile_method, window_weeks=window_weeks)
            
            # Formateamos el patrón de salida dinámicamente inyectando el año de la iteración actual
            pattern_kwargs['year'] = year
            
            try:
                filename = output_pattern.format(**pattern_kwargs)
            except KeyError as e:
                raise ValueError(f"Falta proveer la variable en process() para el patrón de nombre: {e}")
                
            output_path = os.path.join(output_dir, filename)
            
            success = self.transform_to_epw(df_filled, base_epw_path, output_path, remove_leap_day=remove_leap_day)
            if success:
                print(f"¡Éxito! Año {year} guardado en: {output_path}")
                success_list.append(year)
            else:
                print(f"Fallo al procesar guardado de {year}.")
                
        return success_list

    # ------------------------------------------------------------------
    # FIX 5: Estadísticas avanzadas de huecos (portadas de Relleno_Datos_faltantes_TMY3.py)
    # ------------------------------------------------------------------
    def get_gap_report(self, df_filled_dict=None):
        """
        Genera un informe detallado de huecos antes y (opcionalmente) después del relleno.

        Parámetros
        ----------
        df_filled_dict : dict {year: df_filled} opcional.
            Si se pasa, compara el estado antes vs. después y mide cuántos huecos
            fueron rellenados, cuántos parcialmente y cuántos siguen vacíos.
            Si no se pasa, sólo analiza el estado original.

        Devuelve
        --------
        dict con claves:
            'annual_stats'  – DataFrame con huecos por año y variable
            'top_gaps'      – DataFrame con los 10 huecos más largos de toda la serie
        """
        LIMITS = {}
        for col in self.df.columns:
            if col == self.datetime_col: continue
            if col in [self.col_temp, self.col_dew]:        LIMITS[col] = 12
            elif col in [self.col_ghi, self.col_dni,
                         self.col_dhi, self.col_bhi]:       LIMITS[col] = 24
            elif col == self.col_wind:                       LIMITS[col] = 3
            elif col == self.col_rh:                         LIMITS[col] = 24
            elif 'pressure' in str(col).lower():             LIMITS[col] = 72
            elif 'dir' in str(col).lower():                  LIMITS[col] = 2
            elif 'speed' in str(col).lower():                LIMITS[col] = 3
            else:                                            LIMITS[col] = 24

        cols_trabajo = [c for c in self.df.columns if c != self.datetime_col]
        df_orig = self.df.set_index(self.datetime_col)

        # ── estadísticas anuales ──────────────────────────────────────
        annual_rows = []
        top_gap_rows = []

        for col in cols_trabajo:
            if col not in df_orig.columns: continue
            s = df_orig[col]
            is_nan = s.isna()
            if not is_nan.any(): continue

            gap_id = (~is_nan).cumsum()
            gap_id_nan = gap_id[is_nan]          # solo IDs de grupos NaN
            gap_sizes  = is_nan.groupby(gap_id).sum()
            gap_sizes  = gap_sizes[gap_sizes.index.isin(gap_id_nan.unique())]
            gap_starts = s[is_nan].groupby(gap_id_nan).apply(lambda x: x.index[0])
            gap_ends   = s[is_nan].groupby(gap_id_nan).apply(lambda x: x.index[-1])

            gaps_info = pd.DataFrame({
                'size':  gap_sizes.values,
                'start': gap_starts.values,
                'end':   gap_ends.values
            })
            gaps_info['year']  = pd.DatetimeIndex(gaps_info['start']).year
            gaps_info['month'] = pd.DatetimeIndex(gaps_info['start']).month
            limite = LIMITS.get(col, 24)

            for yr, grp in gaps_info.groupby('year'):
                total_huecos = len(grp)
                h_orig = int(grp['size'].sum())
                h_rellenas = 0
                h_vacias   = h_orig

                if df_filled_dict and yr in df_filled_dict:
                    df_f = df_filled_dict[yr].set_index(self.datetime_col)
                    if col in df_f.columns:
                        mask_was_nan = is_nan.reindex(df_f.index, fill_value=False)
                        h_vacias   = int(df_f.loc[mask_was_nan, col].isna().sum())
                        h_rellenas = h_orig - h_vacias

                max_hueco = int(grp['size'].max())
                annual_rows.append({
                    'Año': yr, 'Variable': col,
                    'Total_Huecos': total_huecos,
                    'Horas_Orig_Faltan': h_orig,
                    'Horas_Rellenadas': h_rellenas,
                    'Horas_Siguen_Vacias': h_vacias,
                    'Max_Hueco_h': max_hueco,
                    'Limite_h': limite,
                    'Supera_Limite': max_hueco > limite,
                })

                # top gaps
                for _, row in grp.iterrows():
                    estado = 'RELLENADO' if int(row['size']) <= limite else f'NO RELLENADO (>{limite}h)'
                    top_gap_rows.append({
                        'Variable': col, 'Año': yr, 'Mes': int(row['month']),
                        'Max_hueco_horas': int(row['size']),
                        'Inicio': row['start'], 'Fin': row['end'],
                        'Estado_Relleno': estado
                    })

        annual_stats = pd.DataFrame(annual_rows)
        top_gaps = pd.DataFrame(top_gap_rows)
        if not top_gaps.empty:
            top_gaps = top_gaps.nlargest(10, 'Max_hueco_horas')

        return {'annual_stats': annual_stats, 'top_gaps': top_gaps}

    def save_gap_report_excel(self, output_path, df_filled_dict=None):
        """Llama a get_gap_report() y vuelca los resultados en un Excel multi-hoja."""
        report = self.get_gap_report(df_filled_dict=df_filled_dict)
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            if not report['annual_stats'].empty:
                report['annual_stats'].to_excel(writer, sheet_name='stats_anuales', index=False)
            if not report['top_gaps'].empty:
                report['top_gaps'].to_excel(writer, sheet_name='top_10_huecos', index=False)
        print(f"Informe de huecos guardado en: {output_path}")
        return report


class BatchHourlyEPWConverter:
    """
    Clase para iterar de manera masiva sobre múltiples archivos climáticos
    de diferentes ciudades o zonas climáticas y generar sus respectivos EPW.
    """
    
    # Atributo de clase con las llaves requeridas
    MANDATORY_KEYS = ['file_path', 'base_epw_path', 'lat', 'lon', 'elev', 'tz_hour']

    @classmethod
    def get_mandatory_config_keys(cls):
        """
        Imprime y devuelve la lista de llaves obligatorias que cada diccionario 
        / fila de DataFrame debe contener en la configuración 'cities_config'.
        """
        print("Las llaves de configuración obligatorias para cada archivo son:")
        for key in cls.MANDATORY_KEYS:
            if key == 'file_path': print(f" - '{key}': Ruta al Excel u origen de datos horario.")
            elif key == 'base_epw_path': print(f" - '{key}': Plantilla .epw a usar como base para este archivo.")
            elif key == 'lat': print(f" - '{key}': Latitud geográfica (Ej: 40.41)")
            elif key == 'lon': print(f" - '{key}': Longitud geográfica (Ej: -3.70)")
            elif key == 'elev': print(f" - '{key}': Elevación en metros (Ej: 660.0)")
            elif key == 'tz_hour': print(f" - '{key}': Huso horario respecto al UTC (Ej: 1.0)")
        return cls.MANDATORY_KEYS
    
    def __init__(self, cities_config, output_dir="."):
        """
        cities_config: Lista de diccionarios, o un pandas DataFrame.
          Debe contener obligatoriamente las llaves expuestas en `get_mandatory_config_keys()`.
          - 'years': (opcional) Lista de años a procesar [2013, 2014]. Si se omite, procesa todos.
          - Toda llave extra en el diccionario se asume como variable para formatear el 'output_pattern'.
        """
        if isinstance(cities_config, pd.DataFrame):
            self.cities_config = cities_config.to_dict(orient='records')
        else:
            self.cities_config = cities_config
            
        self.output_dir = output_dir

    @classmethod
    def suggest_config(cls, identifiers, data_files, base_epw_files):
        """
        Genera automáticamente la lista de configuración 'cities_config' buscando 
        coincidencias de una lista de identificadores (ej: nombres de ciudades, zonas) 
        dentro de dos orígenes (archivos de datos y plantillas EPW).
        Además, abre cada plantilla EPW encontrada para extraer de ella 
        la latitud, longitud, elevación y huso horario.
        
        identifiers: Lista de strings, ej: ['MADRID', 'SEVILLA', 'C3']
        data_files: Lista de rutas a los archivos .xlsx/.csv, o ruta a la carpeta.
        base_epw_files: Lista de rutas a los archivos .epw base, o ruta a la carpeta.
        """
        # Permite pasar directamente la ruta a los directorios o listas de archivos
        if isinstance(data_files, str) and os.path.isdir(data_files):
            data_files = [os.path.join(data_files, f) for f in os.listdir(data_files) if f.endswith(('.xlsx', '.csv'))]
        if isinstance(base_epw_files, str) and os.path.isdir(base_epw_files):
            base_epw_files = [os.path.join(base_epw_files, f) for f in os.listdir(base_epw_files) if f.endswith('.epw')]
            
        suggested_config = []
        
        for identifier in identifiers:
            ident_str = str(identifier).lower()
            
            # Buscar el archivo de datos que contenga el identificador
            matched_data = next((f for f in data_files if ident_str in os.path.basename(f).lower()), None)
            
            # Buscar el EPW base que contenga el identificador
            matched_epw = next((f for f in base_epw_files if ident_str in os.path.basename(f).lower()), None)
            
            if matched_data and matched_epw:
                print(f"Match exitoso para '{identifier}':\n  -> Archivo horario: {os.path.basename(matched_data)}\n  -> Plantilla EPW: {os.path.basename(matched_epw)}")
                try:
                    # Extraer toda la información obligatoria desde Ladybug
                    epw_obj = EPW(matched_epw)
                    config = {
                        'identifier': identifier, # Variable libre a inyectar en output_pattern
                        'file_path': matched_data,
                        'base_epw_path': matched_epw,
                        'lat': float(epw_obj.location.latitude),
                        'lon': float(epw_obj.location.longitude),
                        'elev': float(epw_obj.location.elevation),
                        'tz_hour': float(epw_obj.location.time_zone)
                    }
                    suggested_config.append(config)
                except Exception as e:
                    print(f"Error al extraer info geográfica del EPW base {matched_epw}: {e}")
            else:
                print(f"Advertencia: No se pudo hacer pareja para '{identifier}'.")
                print(f" - Horario encontrado: {os.path.basename(matched_data) if matched_data else 'NINGUNO'}")
                print(f" - Plantilla EPW encontrada: {os.path.basename(matched_epw) if matched_epw else 'NINGUNO'}")
                
        return suggested_config

    def process_all(self, output_pattern=None, max_interpolate_limit=24, profile_method='monthly', window_weeks=2, remove_leap_day=True, **global_kwargs):
        """
        Ejecuta el procesado iterando cada ciudad.
        Las variables pasadas en global_kwargs se combinan con las variables individuales 
        de cada ciudad para rellenar las llaves del output_pattern.
        Acepta configuración como profile_method, window_weeks, remove_leap_day.
        """
        results_summary = {}
        for config in self.cities_config:
            
            # Verificación estructural obligatoria
            missing_keys = [k for k in self.MANDATORY_KEYS if k not in config]
            if missing_keys:
                print(f"Error: La configuración omite los atributos obligatorios {missing_keys} en:\n{config}\nIgnorando archivo...")
                continue
                
            file_path = config['file_path']
            base_epw_path = config['base_epw_path']
            lat = config['lat']
            lon = config['lon']
            elev = config['elev']
            tz_hour = config['tz_hour']
                
            print(f"\n=======================================================")
            print(f"Iniciando procesamiento masivo para: {file_path}")
            print(f"Base EPW asignada: {base_epw_path}")
            print(f"=======================================================")
            
            try:
                converter = HourlyEPWConverter(
                    file_path=file_path, lat=lat, lon=lon, elev=elev, tz_hour=tz_hour,
                    datetime_col=config.get('datetime_col', 'DATETIME_UTC'),
                    col_temp=config.get('col_temp', 'Dry-bulb temperature'),
                    col_dew=config.get('col_dew', 'Dew Point temperature'),
                    col_wind=config.get('col_wind', 'Wind speed'),
                    col_ghi=config.get('col_ghi', 'GHI'),
                    col_dni=config.get('col_dni', 'BNI/DNI'),
                    col_rh=config.get('col_rh', None),
                    col_dhi=config.get('col_dhi', None),
                    col_bhi=config.get('col_bhi', None)
                )
            except Exception as e:
                print(f"Error al inicializar conversor para {file_path}: {e}")
                continue
            
            # Combinar kwargs globales con los específicos de esta ciudad
            pattern_kwargs = global_kwargs.copy()
            ignored_pattern_keys = self.MANDATORY_KEYS + ['years', 'datetime_col', 'col_temp', 'col_dew', 'col_wind', 'col_ghi', 'col_dni', 'col_rh', 'col_dhi', 'col_bhi']
            
            for key, val in config.items():
                if key not in ignored_pattern_keys:
                    pattern_kwargs[key] = val
                    
            years_to_process = config.get('years', None)
            
            # Delegamos a la clase base
            success_years = converter.process(
                base_epw_path=base_epw_path,
                output_dir=self.output_dir,
                years=years_to_process,
                output_pattern=output_pattern,
                max_interpolate_limit=max_interpolate_limit,
                profile_method=profile_method,
                window_weeks=window_weeks,
                remove_leap_day=remove_leap_day,
                **pattern_kwargs
            )
            
            results_summary[file_path] = success_years
            
        print("\n=======================================================")
        print("RESUMEN DE BATCH PROCESSING")
        for f, yrs in results_summary.items():
            print(f"{os.path.basename(f)} -> Años convertidos: {yrs}")
            
        return results_summary
