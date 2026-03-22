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
                 col_dni='BNI/DNI'):
        
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
        
        # Atributos de datos
        self.df = None
        self.available_years = []
        
        # Inicialización automática
        self._load_file()

    def _load_file(self):
        """Lee el archivo climático y almacena el DataFrame y los años disponibles."""
        if getattr(self, "file_path", "").endswith('.xlsx'):
            self.df = pd.read_excel(self.file_path)
        else:
            self.df = pd.read_csv(self.file_path)
            
        if not pd.api.types.is_datetime64_any_dtype(self.df[self.datetime_col]):
            self.df[self.datetime_col] = pd.to_datetime(self.df[self.datetime_col])
            
        # Ordenar cronológicamente
        self.df = self.df.sort_values(by=self.datetime_col).reset_index(drop=True)
        
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
            
            missing_total_sum = 0
            for col in cols_to_check:
                is_nan = df_year[col].isnull()
                total_missing = is_nan.sum()
                missing_total_sum += total_missing
                
                # Calcular rachas máximas de NaN consecutivos
                consec = is_nan.groupby((~is_nan).cumsum()).sum()
                max_consec = int(consec.max()) if len(consec) > 0 else 0
                
                stat[f'{col}_Faltantes'] = total_missing
                stat[f'{col}_Max_Consecutivos'] = max_consec
                
            stat['Total_Faltantes'] = missing_total_sum
            stats.append(stat)
            
        return pd.DataFrame(stats)

    def get_year_data(self, year):
        """Devuelve un DataFrame aislado con los datos de un año específico."""
        if year not in self.available_years:
            raise ValueError(f"El año {year} no está disponible en este archivo.")
        return self.df[self.df[self.datetime_col].dt.year == year].copy()

    def fill_missing_values(self, df_year, max_interpolate_limit=24):
        """
        Rellena los valores faltantes en un dataframe aislado (ej. de 1 año).
        
        Método:
        1. Interpolación lineal para huecos pequeños y medianos.
        2. Perfil típico basado en la mediana de ese mismo mes/hora a lo largo de los demás datos.
        3. Mediana global como fallback de seguridad extrema.
        """
        df_filled = df_year.copy()
        
        cols_to_fill = [c for c in df_filled.columns if c != self.datetime_col]
        df_filled = df_filled.sort_values(by=self.datetime_col).reset_index(drop=True)
        
        # 1. Interpolación lineal
        for col in cols_to_fill:
            df_filled[col] = df_filled[col].interpolate(method='linear', limit=max_interpolate_limit)
            
        # 2. Perfiles horarios-mensuales (mediana agrupada)
        df_filled['_month'] = df_filled[self.datetime_col].dt.month
        df_filled['_hour'] = df_filled[self.datetime_col].dt.hour
        
        for col in cols_to_fill:
            if df_filled[col].isnull().any():
                median_profile = df_filled.groupby(['_month', '_hour'])[col].transform('median')
                df_filled[col] = df_filled[col].fillna(median_profile)
                
                # 3. Fallback en caso extremo
                if df_filled[col].isnull().any():
                    df_filled[col] = df_filled[col].fillna(df_filled[col].median())
                    
        df_filled = df_filled.drop(columns=['_month', '_hour'])
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

    def transform_to_epw(self, df_year_filled, base_epw_path, output_epw_path):
        """
        Traslada los valores del DataFrame a un archivo .epw que sirve de base,
        realizando cálculos (DHI, Psicometría, Atmosférica) y desactivando las variables obsoletas.
        """
        df_y = df_year_filled.copy()
        df_y = df_y.sort_values(by=self.datetime_col).reset_index(drop=True)

        # Filtro de bisiestos (Feb 29)
        is_leap_day = (df_y[self.datetime_col].dt.month == 2) & (df_y[self.datetime_col].dt.day == 29)
        if is_leap_day.any():
            df_y = df_y[~is_leap_day].reset_index(drop=True)
            
        if len(df_y) < 8760:
            print(f"Advertencia: El año proporcionado solo tiene {len(df_y)} horas disponibles.")
        elif len(df_y) > 8760:
            df_y = df_y.head(8760)

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
            epw_data._is_leap_year = False
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
        rel_hum = [self._calculate_rh(tdb, tdp) for tdb, tdp in zip(t_db, t_dp)]
        p_atm = [self._calculate_atmos_pressure()] * len(df_y)

        # Cálculo de Irradiancia Difusa (DHI) empleando Sunpath
        sp = Sunpath(latitude=self.lat, longitude=self.lon, time_zone=self.tz_hour)
        dhi_values = []
        
        for i in range(len(df_y)):
            dt = pd.to_datetime(dates[i])
            m = dt.month
            d = dt.day
            h = dt.hour 
            
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

    def process(self, base_epw_path, output_dir=".", years=None):
        """
        Método directo ("todo en uno") que automatiza el proceso completo.
        Toma una lista de años (o todos si no se especifican), les rellena 
        huecos y genera un EPW para cada uno.
        """
        if years is None:
            years = self.available_years
            
        success_list = []
        for year in years:
            if year not in self.available_years:
                print(f"Año {year} no hallado en los datos. Ignorando...")
                continue
                
            print(f"\n--- Procesando año {year} de forma directa ---")
            df_year = self.get_year_data(year)
            df_filled = self.fill_missing_values(df_year)
            
            # Formatos automáticos de salida
            city_name = os.path.basename(self.file_path).split('_')[0].split('.')[0].upper()
            output_path = os.path.join(output_dir, f"{city_name}_{year}_convertido.epw")
            
            success = self.transform_to_epw(df_filled, base_epw_path, output_path)
            if success:
                print(f"¡Éxito! Año {year} guardado en: {output_path}")
                success_list.append(year)
            else:
                print(f"Fallo al procesar guardado de {year}.")
                
        return success_list
