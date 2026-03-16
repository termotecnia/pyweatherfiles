# met_epw_converter.py

import pandas as pd
import math
import os
import sys
import contextlib
import numpy as np

try:
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    from ladybug.analysisperiod import AnalysisPeriod
except ImportError:
    raise ImportError("La librería 'ladybug-core' no está instalada. Por favor, instálala con: pip install ladybug-core")


# --- GESTOR DE CONTEXTO ---
@contextlib.contextmanager
def suppress_stdout_stderr():
    with open(os.devnull, 'w') as fnull:
        saved_stdout = sys.stdout
        saved_stderr = sys.stderr
        sys.stdout = fnull
        sys.stderr = fnull
        try:
            yield
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr


# --- CONSTANTES Y DEFINICIONES DE COLUMNAS ---
# Precisión exacta según instrucciones
_STEFAN_BOLTZMANN = 5.6697e-8

COLS_MET_13 = [
    'Month', 'Day', 'Hour', 'DryBulb', 'SkyTemp',
    'RadDirectaHoriz', 'RadDifusaHoriz', 'AbsHum', 'RelHum',
    'WindSpeed', 'WindDir', 'Azimuth', 'Zenith'
]

COLS_MET_15 = [
    'Month', 'Day', 'Hour', 'DryBulb', 'SkyTemp',
    'RadDirectaHoriz', 'RadDifusaHoriz', 'AbsHum', 'RelHum',
    'WindSpeed', 'Nada1', 'Azimuth', 'Zenith',
    'Nada2', 'Nada3'
]


# --- FUNCIONES DE CÁLCULO AUXILIARES ---

def _calculate_variable_pressure_from_met(temp_c, rel_hum, wabs, elevation_m):
    """
    Ingeniería inversa: Despeja la presión atmosférica horaria a partir de la
    Humedad Absoluta (wabs), Temperatura y Humedad Relativa del archivo .met.
    """
    # Si la humedad absoluta es 0 (aire extremadamente seco o error de datos),
    # evitamos división por cero y devolvemos la presión constante por altitud.
    if wabs <= 0 or rel_hum <= 0:
        return _calculate_atmos_pressure(elevation_m)

    # Calcular presión de vapor actual (pv)
    e_s = 610.78 * (10 ** (7.5 * temp_c / (237.3 + temp_c)))
    e = e_s * (rel_hum / 100.0)

    # Despejar P_atm de la fórmula del Apéndice A.3
    p_atm = e * (1.0 + (0.62198 / wabs))

    # Filtro de seguridad: Si por redondeos del .met el valor es un disparate físico
    # (fuera del rango 50,000 Pa - 110,000 Pa), usamos la presión estándar por altitud.
    if 50000 < p_atm < 110000:
        return p_atm
    else:
        return _calculate_atmos_pressure(elevation_m)

def _calculate_dew_point(temp_c, rh_percent):
    if rh_percent <= 0: return temp_c
    b = 17.62
    c = 243.12
    gamma = (b * temp_c / (c + temp_c)) + math.log(rh_percent / 100.0)
    dew_point = (c * gamma) / (b - gamma)
    return dew_point


def _calculate_atmos_pressure(elevation_m):
    p0 = 101325
    L = 0.0065
    T0 = 288.15
    g = 9.80665
    M = 0.0289644
    R = 8.31447
    pressure = p0 * (1 - (L * elevation_m) / T0) ** ((g * M) / (R * L))
    return pressure


def _calculate_sky_temperature(hir_radiation):
    """Calcula la temperatura del cielo a partir de la radiación infrarroja horizontal (EPW -> MET)"""
    if hir_radiation <= 0: return -273.15
    sky_temp_k = (hir_radiation / _STEFAN_BOLTZMANN) ** 0.25
    sky_temp_c = sky_temp_k - 273.15
    return sky_temp_c


def _calculate_absolute_humidity(temp_c, rel_hum, pressure_pa):
    """Fórmula psicrométrica (EPW -> MET)"""
    if rel_hum < 0.1: return 0.0
    e_s = 610.78 * (10 ** (7.5 * temp_c / (237.3 + temp_c)))
    e = e_s * (rel_hum / 100.0)
    wabs = 0.62198 * e / (pressure_pa - e)
    return max(0, wabs)


def _set_epw_values(epw_obj, field_name, new_vals):
    """
    Asigna valores a un campo de Ladybug EPW compensando el desfase interno de point_in_time.
    MET Hour 1 (01:00) es el índice 0 de new_vals.
    Ladybug point_in_time espera que el índice 0 sea Jan 1 00:00 (Row 8760 de un año estándar).
    """
    field = getattr(epw_obj, field_name)
    if field.header.data_type.point_in_time:
        shifted = [new_vals[-1]] + list(new_vals[:-1])
        field.values = tuple(shifted) if isinstance(field.values, tuple) else list(shifted)
    else:
        field.values = tuple(new_vals) if isinstance(field.values, tuple) else list(new_vals)


def _get_epw_values(epw_obj, field_name):
    """
    Obtiene valores de un campo de Ladybug EPW compensando el desfase interno de point_in_time.
    Devuelve una lista donde el índice 0 corresponde a MET Hour 1 (01:00).
    """
    field = getattr(epw_obj, field_name)
    vals = list(field.values)
    if field.header.data_type.point_in_time:
        return vals[1:] + [vals[0]]
    else:
        return vals


# --- CONVERSIÓN MET -> EPW ---
def convert_met_to_epw(met_path: str, epw_path: str, base_epw_path: str, replace_unused_with_missing: bool = False) -> bool:
    print(f"Iniciando conversión de '{met_path}' a '{epw_path}'...")

    try:
        epw_data = EPW(base_epw_path)
    except Exception as e:
        print(f"Error al cargar plantilla: {e}")
        return False

    try:
        with open(met_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        print(f"Error: Archivo no encontrado.")
        return False

    # --- PROCESAMIENTO DE CABECERA ---
    if len(lines) < 3:
        print("Error Crítico: El archivo .met es demasiado corto.")
        return False

    meta_line_index = 1
    header2 = lines[meta_line_index].split()

    try:
        float(header2[0])
    except ValueError:
        for i, line in enumerate(lines[:10]):
            parts = line.split()
            try:
                val = float(parts[0])
                if -90 <= val <= 90 and len(parts) >= 3:
                    meta_line_index = i
                    header2 = parts
                    break
            except ValueError:
                continue

    if len(header2) >= 3:
        lat = float(header2[0])
        lon = float(header2[1])
        elev = float(header2[2])
    else:
        print("Error Crítico: No se encontraron metadatos geográficos válidos.")
        return False

    tz_hour = round(lon / 15.0)

    epw_data.location.city = os.path.basename(met_path).split('.')[0].capitalize()
    epw_data.location.latitude = lat
    epw_data.location.longitude = lon
    epw_data.location.time_zone = tz_hour
    epw_data.location.elevation = elev
    epw_data.comments_1 = f"Convertido desde {os.path.basename(met_path)}"
    epw_data.comments_2 = "Radiacion Directa Normal recalculada astronomicamente."

    # --- DETECCIÓN DEL INICIO DE DATOS ---
    data_start_index = meta_line_index + 1
    first_data_line = lines[data_start_index].split()

    if first_data_line[0] != '1' or first_data_line[1] != '1' or first_data_line[2] != '1':
        for i in range(data_start_index, min(data_start_index + 10, len(lines))):
            parts = lines[i].split()
            if len(parts) > 5 and parts[0] == '1' and parts[1] == '1' and parts[2] == '1':
                data_start_index = i
                break

    # --- LECTURA PANDAS ---
    from io import StringIO
    data_str = "\n".join(lines[data_start_index:])

    try:
        df = pd.read_csv(StringIO(data_str), header=None, sep=r'\s+')
        num_cols = df.shape[1]

        if num_cols == 13:
            df.columns = COLS_MET_13
            wind_direction_data = df['WindDir'].tolist()
        elif num_cols == 15:
            df.columns = COLS_MET_15
            wind_direction_data = [0] * len(df)
        else:
            print(f"Error Crítico: El archivo tiene {num_cols} columnas.")
            return False

    except Exception as e:
        print(f"Error al procesar datos del MET: {e}")
        return False

    # --- CORRECCIÓN AÑO ESTÁNDAR ---
    try:
        epw_data._analysis_period = AnalysisPeriod(st_month=1, st_day=1, st_hour=1, end_month=12, end_day=31, end_hour=24)
        epw_data._is_leap_year = False
    except Exception:
        pass

    # --- ASIGNACIÓN DIRECTA CON DESFASE CORREGIDO ---
    _set_epw_values(epw_data, 'dry_bulb_temperature', df['DryBulb'].tolist())
    _set_epw_values(epw_data, 'relative_humidity', df['RelHum'].tolist())
    _set_epw_values(epw_data, 'diffuse_horizontal_radiation', df['RadDifusaHoriz'].tolist())
    _set_epw_values(epw_data, 'wind_speed', df['WindSpeed'].tolist())
    _set_epw_values(epw_data, 'wind_direction', wind_direction_data)
    _set_epw_values(epw_data, 'dew_point_temperature', [_calculate_dew_point(t, rh) for t, rh in zip(df['DryBulb'], df['RelHum'])])
    patm_values = [
        _calculate_variable_pressure_from_met(t, rh, w, elev)
        for t, rh, w in zip(df['DryBulb'], df['RelHum'], df['AbsHum'])
    ]
    _set_epw_values(epw_data, 'atmospheric_station_pressure', patm_values)

    # --- CONVERSIÓN DE RADIACIÓN INFRARROJA ---
    ir_values = []
    for t_sky in df['SkyTemp']:
        t_sky_k = t_sky + 273.15
        ir = _STEFAN_BOLTZMANN * (t_sky_k ** 4)
        ir_values.append(ir)
    _set_epw_values(epw_data, 'horizontal_infrared_radiation_intensity', ir_values)

    # --- CONVERSIÓN DE RADIACIÓN SOLAR CON PRECISIÓN ASTRONÓMICA ---
    print("  - Recalculando ángulo cenital (theta_z) y balanceando radiación...")
    # CORRECCIÓN: Sunpath no recibe 'elevation', solo lat, lon, y tz.
    sp = Sunpath(latitude=lat, longitude=lon, time_zone=tz_hour)

    ghi_values = []
    dni_values = []

    for m, d, h, dir_horiz, diff_horiz in zip(df['Month'], df['Day'], df['Hour'], df['RadDirectaHoriz'], df['RadDifusaHoriz']):

        # 1. GHI = Directa Horizontal + Difusa Horizontal
        ghi = dir_horiz + diff_horiz
        ghi_values.append(ghi)

        # 2. Calcular theta_z preciso para el punto medio de la hora
        calc_hour = float(h) - 0.5
        sun = sp.calculate_sun(month=int(m), day=int(d), hour=calc_hour)
        zenith_deg = 90.0 - sun.altitude

        # 3. Calcular DNI
        cos_zenith = math.cos(math.radians(zenith_deg))

        if cos_zenith <= 0.01:
            dni = 0.0
        else:
            dni = dir_horiz / cos_zenith
            if dni > 1367.0:
                dni = 1367.0

        dni_values.append(dni)

    _set_epw_values(epw_data, 'global_horizontal_radiation', ghi_values)
    _set_epw_values(epw_data, 'direct_normal_radiation', dni_values)

    if replace_unused_with_missing:
        # Solo se incluyen las variables marcadas con 'N' (No usadas por EnergyPlus)
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
        num_rows = len(df)
        
        for field_name, missing_val in unused_fields_mapping.items():
            if hasattr(epw_data, field_name):
                field_obj = getattr(epw_data, field_name)
                replacement_list = [missing_val] * num_rows
                
                if hasattr(field_obj, 'header') and hasattr(field_obj, 'values'):
                    # Si es una DataCollection de Ladybug
                    _set_epw_values(epw_data, field_name, replacement_list)
                else:
                    # Si es una propiedad simple como list/tuple
                    try:
                        setattr(epw_data, field_name, tuple(replacement_list))
                    except Exception:
                        pass

    try:
        with suppress_stdout_stderr():
            epw_data.save(epw_path)
    except Exception as e:
        print(f"Error al guardar EPW: {e}")
        return False

    print("¡Conversión MET -> EPW completada (Balance de radiación asegurado)!")
    return True


# --- CONVERSIÓN EPW -> MET ---
def convert_epw_to_met(epw_path: str, met_path: str) -> bool:
    print(f"\n--- Iniciando conversión de '{epw_path}' a '{met_path}' ---")

    try:
        epw_obj = EPW(epw_path)
        lat = epw_obj.location.latitude
        lon = epw_obj.location.longitude
        elev = epw_obj.location.elevation
        tz = epw_obj.location.time_zone

        dry_bulb = np.array(_get_epw_values(epw_obj, 'dry_bulb_temperature'))
        rel_hum = np.array(_get_epw_values(epw_obj, 'relative_humidity'))
        wind_spd = np.array(_get_epw_values(epw_obj, 'wind_speed'))
        wind_dir = np.array(_get_epw_values(epw_obj, 'wind_direction'))
        glob_horiz = np.array(_get_epw_values(epw_obj, 'global_horizontal_radiation'))
        diff_horiz = np.array(_get_epw_values(epw_obj, 'diffuse_horizontal_radiation'))
        horiz_ir = np.array(_get_epw_values(epw_obj, 'horizontal_infrared_radiation_intensity'))

    except Exception as e:
        print(f"Error al leer EPW: {e}")
        return False

    df_met = pd.DataFrame()

    df_met['Mes'] = [pd.Timestamp(2005, 1, 1) + pd.Timedelta(hours=i) for i in range(8760)]
    df_met['Mes_Num'] = df_met['Mes'].dt.month
    df_met['Dia'] = df_met['Mes'].dt.day
    df_met['Hora'] = df_met['Mes'].dt.hour + 1

    df_met['Taire'] = dry_bulb

    # RESTAURADA: Función _calculate_sky_temperature
    df_met['Tcielo'] = [_calculate_sky_temperature(x) for x in horiz_ir]

    rad_directa_horiz = glob_horiz - diff_horiz
    rad_directa_horiz = np.maximum(rad_directa_horiz, 0)

    df_met['RadDirectaHoriz'] = rad_directa_horiz
    df_met['RadDifusaHoriz'] = diff_horiz

    presion = _calculate_atmos_pressure(elev)
    df_met['wabs'] = [_calculate_absolute_humidity(t, rh, presion) for t, rh in zip(dry_bulb, rel_hum)]

    df_met['HR'] = rel_hum
    df_met['WindSpeed'] = wind_spd
    df_met['WindDir'] = wind_dir

    df_met['Azimuth'] = 0
    df_met['Zenith'] = 0

    try:
        with open(met_path, 'w') as f:
            f.write(f"{os.path.basename(met_path)} {tz * 15.0}\n")
            f.write(f"{lat:.2f}\t{lon:.2f}\t{elev:.1f}\t0.0\n")

        cols_out = ['Mes_Num', 'Dia', 'Hora', 'Taire', 'Tcielo',
                    'RadDirectaHoriz', 'RadDifusaHoriz', 'wabs', 'HR',
                    'WindSpeed', 'WindDir', 'Azimuth', 'Zenith']

        df_met[cols_out].to_csv(met_path, mode='a', sep=' ', header=False, index=False, float_format='%.4f')

        print("¡Conversión EPW -> MET completada!")
        return True

    except Exception as e:
        print(f"Error al escribir MET: {e}")
        return False