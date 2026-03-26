# -*- coding: utf-8 -*-
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
    Clase para leer archivos climáticos horarios (previamente limpiados y rellenados)
    y exportarlos a formato EPW inhabilitando las variables no requeridas (obsoletas).
    """
    
    def __init__(self, file_path, lat, lon, elev, tz_hour,
                 datetime_col='time', 
                 col_temp='Dry-bulb temperature', 
                 col_dew='Dew Point temperature', 
                 col_wind='Wind Speed', 
                 col_ghi='Global Horizontal Irradiance ', 
                 col_dni='Beam Normal Irradiance ',
                 col_rh='Relative Humidity',
                 col_pres='Pressure',
                 col_wind_dir='Wind Direction',
                 col_dhi='Diffuse Horizontal Irradiance',
                 col_cloud_cover='Total Cloud Cover',
                 col_irh='IRh',
                 column_mapping=None,
                 preserve_extra=False,
                 remove_leap_day=True):
        
        # Atributos geográficos
        self.file_path = file_path
        self.lat = lat
        self.lon = lon
        self.elev = elev
        self.tz_hour = tz_hour
        self.preserve_extra = preserve_extra
        self.remove_leap_day = remove_leap_day
        
        # Mapeo de columnas (se pueden ajustar al instanciar)
        self.col_mapping = {
            'datetime': datetime_col,
            'temp': col_temp,
            'dew': col_dew,
            'wind_speed': col_wind,
            'ghi': col_ghi,
            'dni': col_dni,
            'rh': col_rh,
            'pres': col_pres,
            'wind_dir': col_wind_dir,
            'dhi': col_dhi,
            'cloud_cover': col_cloud_cover,
            'irh': col_irh
        }
        
        if column_mapping:
            self.col_mapping.update(column_mapping)
            
        self.datetime_col = self.col_mapping['datetime']
        self.col_temp = self.col_mapping['temp']
        self.col_dew = self.col_mapping['dew']
        self.col_wind = self.col_mapping['wind_speed']
        self.col_ghi = self.col_mapping['ghi']
        self.col_dni = self.col_mapping['dni']
        self.col_rh = self.col_mapping['rh']
        self.col_pres = self.col_mapping['pres']
        self.col_wind_dir = self.col_mapping['wind_dir']
        self.col_dhi = self.col_mapping['dhi']
        self.col_cloud_cover = self.col_mapping['cloud_cover']
        self.col_irh = self.col_mapping['irh']
        
        # Atributos de datos
        self.df = None
        self.available_years =[]
        
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
        
        # Conversiones condicionales de unidades
        if self.col_wind in self.df.columns:
            self.df[self.col_wind] = pd.to_numeric(self.df[self.col_wind], errors='coerce') / 3.6
            
        if self.col_pres in self.df.columns:
            self.df[self.col_pres] = pd.to_numeric(self.df[self.col_pres], errors='coerce') * 100.0
            
        # Guardar en atributo los años disponibles
        self.available_years = sorted(self.df[self.datetime_col].dt.year.dropna().unique().tolist())
        self.available_years = [int(i) for i in self.available_years]

    def get_year_data(self, year):
        """Devuelve un DataFrame aislado con los datos de un año específico."""
        if year not in self.available_years:
            raise ValueError(f"El año {year} no está disponible en este archivo.")
        return self.df[self.df[self.datetime_col].dt.year == year].copy()

    def _calculate_rh(self, tdb, tdp):
        """Cálculo interno Psicométrico de HR (requerido por el EPW)"""
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

    def transform_to_epw(self, df_year, base_epw_path, output_epw_path):
        """
        Traslada los valores del DataFrame a un archivo .epw que sirve de base,
        realizando cálculos (DHI, Psicometría, Atmosférica) y desactivando las variables obsoletas.
        """
        df_y = df_year.copy()
        df_y = df_y.sort_values(by=self.datetime_col).reset_index(drop=True)

        # Filtro de bisiestos (Feb 29) - EnergyPlus usa típicamente 8760 horas
        is_leap_year = False
        is_leap_day = (df_y[self.datetime_col].dt.month == 2) & (df_y[self.datetime_col].dt.day == 29)
        
        if is_leap_day.any():
            is_leap_year = True
            
        if self.remove_leap_day and is_leap_year:
            df_y = df_y[~is_leap_day].reset_index(drop=True)
            is_leap_year = False # Al removerlo, deja de considerarse bisiesto para la salida
            
        if is_leap_year:
            if len(df_y) < 8784:
                print(f"Advertencia: El año bisiesto proporcionado solo tiene {len(df_y)} horas disponibles.")
            elif len(df_y) > 8784:
                df_y = df_y.head(8784)
        else:
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
            if is_leap_year:
                try:
                    epw_data._analysis_period = AnalysisPeriod(st_month=1, st_day=1, st_hour=1, end_month=12, end_day=31, end_hour=24, is_leap_year=True)
                except Exception:
                    epw_data._analysis_period = AnalysisPeriod(st_month=1, st_day=1, st_hour=1, end_month=12, end_day=31, end_hour=24)
                epw_data._is_leap_year = True
            else:
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

        if self.col_wind_dir in df_y.columns:
            wind_dir = df_y[self.col_wind_dir].tolist()
        else:
            wind_dir = [0] * len(df_y)
            
        if self.col_rh in df_y.columns:
            rel_hum = df_y[self.col_rh].tolist()
        else:
            rel_hum =[self._calculate_rh(tdb, tdp) for tdb, tdp in zip(t_db, t_dp)]
            
        if self.col_pres in df_y.columns:
            p_atm = df_y[self.col_pres].tolist()
        else:
            p_atm = [self._calculate_atmos_pressure()] * len(df_y)

        # Cálculo de Irradiancia Difusa (DHI)
        if self.col_dhi in df_y.columns:
            dhi_values = df_y[self.col_dhi].tolist()
        else:
            sp = Sunpath(latitude=self.lat, longitude=self.lon, time_zone=self.tz_hour)
            dhi_values =[]
            
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

        # Variables extra
        if self.col_cloud_cover in df_y.columns:
            cloud_cover = df_y[self.col_cloud_cover].tolist()
            self._set_epw_values(epw_data, 'total_sky_cover', cloud_cover)
            
        if self.col_irh in df_y.columns:
            irh_vals = df_y[self.col_irh].tolist()
            self._set_epw_values(epw_data, 'horizontal_infrared_radiation_intensity', irh_vals)

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
        
        if self.preserve_extra and self.col_cloud_cover in df_y.columns:
            if 'total_sky_cover' in unused_fields_mapping:
                del unused_fields_mapping['total_sky_cover']

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

    def process(self, base_epw_path, output_dir=".", years=None, remove_leap_day=None, output_pattern=None, **kwargs):
        """
        Método directo que automatiza el proceso de conversión.
        Toma una lista de años (o todos si no se especifican) y genera un EPW para cada uno
        a partir del archivo que ya viene rellenado.
        """
        if remove_leap_day is not None:
            self.remove_leap_day = remove_leap_day
            
        if years is None:
            years = self.available_years
            
        success_list =[]
        
        basename = os.path.splitext(os.path.basename(self.file_path))[0]
        
        for year in years:
            if year not in self.available_years:
                print(f"Año {year} no hallado en los datos. Ignorando...")
                continue
                
            print(f"\n--- Procesando año {year} de forma directa ---")
            df_year = self.get_year_data(year)
            
            # Formatos automáticos de salida
            int_year = int(year)
            if output_pattern:
                try:
                    filename = output_pattern.format(year=int_year, **kwargs)
                except KeyError as e:
                    print(f"Falla de formato de nombre de archivo con KeyError: {e}")
                    filename = f"{basename}_{int_year}.epw"
            else:
                filename = f"{basename}_{int_year}.epw"
                
            output_path = os.path.join(output_dir, filename)
            
            # Pasamos directamente el df_year asumiendo que ya no tiene nulos
            success = self.transform_to_epw(df_year, base_epw_path, output_path)
            if success:
                print(f"¡Éxito! Año {year} guardado en: {output_path}")
                success_list.append(year)
            else:
                print(f"Fallo al procesar guardado de {year}.")
                
        return success_list


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
            if key == 'file_path':
                print(f" - '{key}': Ruta al Excel u origen de datos horario.")
            elif key == 'base_epw_path':
                print(f" - '{key}': Plantilla .epw a usar como base para este archivo.")
            elif key == 'lat':
                print(f" - '{key}': Latitud geográfica (Ej: 40.41)")
            elif key == 'lon':
                print(f" - '{key}': Longitud geográfica (Ej: -3.70)")
            elif key == 'elev':
                print(f" - '{key}': Elevación en metros (Ej: 660.0)")
            elif key == 'tz_hour':
                print(f" - '{key}': Huso horario respecto al UTC (Ej: 1.0)")
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
                        'identifier': identifier,  # Variable libre a inyectar en output_pattern
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

    def process_all(self, output_pattern=None, remove_leap_day=True, **global_kwargs):
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

            # Preparar argumentos opcionales a pasar al converter base
            kwargs_for_converter = {
                'file_path': file_path, 'lat': lat, 'lon': lon, 'elev': elev, 'tz_hour': tz_hour
            }
            optional_keys = [
                'datetime_col', 'col_temp', 'col_dew', 'col_wind', 'col_ghi', 'col_dni',
                'col_rh', 'col_pres', 'col_wind_dir', 'col_dhi', 'col_cloud_cover', 'col_irh',
                'column_mapping', 'preserve_extra'
            ]
            for opt_k in optional_keys:
                if opt_k in config:
                    kwargs_for_converter[opt_k] = config[opt_k]

            try:
                converter = HourlyEPWConverter(**kwargs_for_converter)
            except Exception as e:
                print(f"Error al inicializar conversor para {file_path}: {e}")
                continue

            # Combinar kwargs globales con los específicos de esta ciudad
            pattern_kwargs = global_kwargs.copy()
            ignored_pattern_keys = self.MANDATORY_KEYS + ['years'] + optional_keys

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
                remove_leap_day=remove_leap_day,
                **pattern_kwargs
            )

            results_summary[file_path] = success_years

        print("\n=======================================================")
        print("RESUMEN DE BATCH PROCESSING")
        for f, yrs in results_summary.items():
            print(f"{os.path.basename(f)} -> Años convertidos: {yrs}")

        return results_summary
