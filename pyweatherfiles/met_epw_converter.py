# -*- coding: utf-8 -*-
"""
met_epw_converter.py
=====================

Bidirectional conversion between the Spanish ``.met`` reference-climate file
format (used by the CTE/LIDER-CALENER building-energy-code tools) and the
international **EPW** (EnergyPlus Weather) format.

**The ``.met`` format.** A plain-text file with a metadata line (latitude,
longitude, elevation) followed by a data block of either 13 columns
(``Month, Day, Hour, DryBulb, SkyTemp, RadDirectaHoriz, RadDifusaHoriz,
AbsHum, RelHum, WindSpeed, WindDir, Azimuth, Zenith``, see
:data:`COLS_MET_13`) or 15 columns (no wind direction, two unused auxiliary
columns, see :data:`COLS_MET_15`). Because ``.met`` does not store
temperature-independent physical quantities directly (dew point, atmospheric
pressure, DNI), this module reconstructs them from what *is* available using
well known meteorological/astronomical formulas (Magnus dew-point inversion,
the international barometric formula, Stefan-Boltzmann sky-temperature
inversion, and exact solar-position-based DNI reconstruction via
``ladybug.sunpath.Sunpath``).

Public API
----------
- :func:`convert_met_to_epw` — the main, most commonly used entry point:
  ``.met`` (+ an EPW template for anything a ``.met`` cannot provide, such as
  illuminance/cloud-cover placeholders) -> ``.epw``.
- :func:`convert_epw_to_met` — the reverse conversion, ``.epw`` -> ``.met``.

Both functions are free functions (no class involved); :func:`convert_met_to_epw`
persists a reproducible session via
:func:`~pyweatherfiles.session_manager.save_function_session` when
``save_session=True`` (the default).

Example
-------
Converting an official CTE/LIDER-CALENER reference file to EPW, ready to be
fed into EnergyPlus or compared against a generated TMY::

    from pyweatherfiles import met_epw_converter

    met_epw_converter.convert_met_to_epw(
        met_path="seville.met",
        base_epw_path="ESP_Sevilla.083910_IWEC.epw",
        epw_path="sevilla_met.epw",
        replace_unused_with_missing=True,
    )

    # Round-trip back to .met (e.g. to sanity-check the conversion):
    met_epw_converter.convert_epw_to_met("sevilla_met.epw", "sevilla_roundtrip.met")
"""

import pandas as pd
import math
import os
import sys
import contextlib
import numpy as np
from .session_manager import save_function_session
from .epw_field_utils import (
    calculate_atmos_pressure as _shared_calculate_atmos_pressure,
    set_epw_values as _shared_set_epw_values,
    get_epw_values as _shared_get_epw_values,
    neutralize_unused_epw_fields,
)


try:
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    from ladybug.analysisperiod import AnalysisPeriod
except ImportError:
    raise ImportError("The 'ladybug-core' library is not installed. Install it with: pip install ladybug-core")


# --- CONTEXT MANAGER ---
@contextlib.contextmanager
def suppress_stdout_stderr():
    """Context manager that temporarily redirects ``stdout``/``stderr`` to
    the OS null device, silencing any print statements made by third-party
    code (namely ``ladybug``'s ``EPW.save()``, which can otherwise be quite
    verbose) for the duration of the ``with`` block.

    ``stdout``/``stderr`` are always restored on exit, even if the code
    inside the block raises an exception.

    Example:
        >>> with suppress_stdout_stderr():
        ...     print("this will not be shown")
        >>> print("this will be shown")
        this will be shown
    """
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


# --- CONSTANTS AND COLUMN DEFINITIONS ---
# Exact physical constants as specified by the conversion formulas below.
_STEFAN_BOLTZMANN = 5.6697e-8
"""float: Stefan-Boltzmann constant in W/(m2*K4), used to convert between
sky temperature and horizontal infrared radiation intensity."""

_COS_ZENITH_MIN = 0.01
"""float: Minimum cosine of the solar zenith angle below which the sun is
considered to be at/below the horizon (used to zero-out DNI safely instead
of dividing by a near-zero cosine)."""

_DNI_MAX_PHYSICAL = 1367.0
"""float: The solar constant (W/m2), used as a physically-motivated upper
clip for the DNI values reconstructed from ``.met`` horizontal irradiance."""

COLS_MET_13 = [
    'Month', 'Day', 'Hour', 'DryBulb', 'SkyTemp',
    'RadDirectaHoriz', 'RadDifusaHoriz', 'AbsHum', 'RelHum',
    'WindSpeed', 'WindDir', 'Azimuth', 'Zenith'
]
"""list[str]: Column names for the 13-column ``.met`` data-block variant
(includes wind direction)."""

COLS_MET_15 = [
    'Month', 'Day', 'Hour', 'DryBulb', 'SkyTemp',
    'RadDirectaHoriz', 'RadDifusaHoriz', 'AbsHum', 'RelHum',
    'WindSpeed', 'Nada1', 'Azimuth', 'Zenith',
    'Nada2', 'Nada3'
]
"""list[str]: Column names for the 15-column ``.met`` data-block variant
(no wind direction; ``Nada1``/``Nada2``/``Nada3`` are unused placeholder
columns kept only to match the file's column count)."""


# --- AUXILIARY CALCULATION FUNCTIONS ---

def _calculate_variable_pressure_from_met(temp_c, rel_hum, wabs, elevation_m):
    """
    Reverse-engineer the hourly atmospheric pressure from the absolute
    humidity, dry-bulb temperature and relative humidity provided by a
    ``.met`` file (``.met`` does not store pressure directly).

    Steps: compute the saturation vapour pressure at *temp_c* (Magnus-type
    formula), scale it by *rel_hum* to get the actual vapour pressure, then
    solve for atmospheric pressure using the standard psychrometric relation
    between absolute humidity and vapour pressure. If the result is not a
    physically plausible sea-level-adjustable pressure (outside
    50,000-110,000 Pa, which can happen due to rounding noise in the source
    ``.met``), falls back to the standard barometric estimate for the site's
    elevation (see :func:`_calculate_atmos_pressure`).

    Args:
        temp_c (float): Dry-bulb temperature in degrees Celsius.
        rel_hum (float): Relative humidity in percent (0-100).
        wabs (float): Absolute humidity (humidity ratio, kg water / kg dry
            air) as provided by the ``.met`` file's ``AbsHum`` column.
        elevation_m (float): Site elevation in metres, used only for the
            barometric-formula fallback.

    Returns:
        float: Atmospheric station pressure in Pascals.
    """
    # If absolute humidity is 0 (extremely dry air or data error),
    # avoid division by zero and return the constant pressure for the elevation.
    if wabs <= 0 or rel_hum <= 0:
        return _calculate_atmos_pressure(elevation_m)

    # Calculate the current vapour pressure (pv)
    e_s = 610.78 * (10 ** (7.5 * temp_c / (237.3 + temp_c)))
    e = e_s * (rel_hum / 100.0)

    # Solve for P_atm from the Appendix A.3 formula
    p_atm = e * (1.0 + (0.62198 / wabs))

    # Safety filter: if rounding noise in the .met file produces a physically
    # implausible value (outside the 50,000 Pa - 110,000 Pa range), fall back
    # to the standard elevation-based pressure.
    if 50000 < p_atm < 110000:
        return p_atm
    else:
        return _calculate_atmos_pressure(elevation_m)

def _calculate_dew_point(temp_c, rh_percent):
    """Compute the dew-point temperature from dry-bulb temperature and
    relative humidity by inverting the Magnus formula.

    ``gamma = b*T/(c+T) + ln(RH/100)`` and ``Tdp = c*gamma / (b - gamma)``,
    with the standard Magnus coefficients ``b=17.62`` and ``c=243.12``.

    Args:
        temp_c (float): Dry-bulb temperature in degrees Celsius.
        rh_percent (float): Relative humidity in percent (0-100). If
            ``<= 0``, *temp_c* is returned unchanged (degenerate case, avoids
            ``log(0)``).

    Returns:
        float: Dew-point temperature in degrees Celsius.

    Example:
        >>> round(_calculate_dew_point(25.0, 50.0), 2)
        13.85
    """
    if rh_percent <= 0: return temp_c
    b = 17.62
    c = 243.12
    gamma = (b * temp_c / (c + temp_c)) + math.log(rh_percent / 100.0)
    dew_point = (c * gamma) / (b - gamma)
    return dew_point


def _calculate_atmos_pressure(elevation_m):
    """Estimate the standard atmospheric pressure at a given elevation using
    the international barometric formula (ISA, constant lapse-rate model).
    Thin backward-compatible wrapper; the real (shared) implementation now
    lives in :func:`~pyweatherfiles.epw_field_utils.calculate_atmos_pressure`,
    also used by :mod:`~pyweatherfiles.hourly_epw_converter` (see
    ``INFORME_REVISION_GENERAL.md`` §3.1/Fase 1).

    Args:
        elevation_m (float): Site elevation above sea level, in metres.

    Returns:
        float: Estimated standard atmospheric pressure in Pascals.

    Example:
        >>> round(_calculate_atmos_pressure(0), 0)
        101325.0
    """
    return _shared_calculate_atmos_pressure(elevation_m)


def _calculate_sky_temperature(hir_radiation):
    """Invert the Stefan-Boltzmann law to recover an equivalent sky
    temperature from horizontal infrared radiation intensity (used for the
    EPW -> ``.met`` direction, since ``.met`` stores ``SkyTemp`` directly).

    ``T_sky = (IR / sigma) ** 0.25 - 273.15``.

    Args:
        hir_radiation (float): Horizontal infrared radiation intensity in
            W/m2 (EPW's ``horizontal_infrared_radiation_intensity`` field).

    Returns:
        float: Equivalent sky temperature in degrees Celsius. Returns
        ``-273.15`` (absolute zero, a sentinel for "no signal") if
        *hir_radiation* is ``<= 0``.
    """
    if hir_radiation <= 0: return -273.15
    sky_temp_k = (hir_radiation / _STEFAN_BOLTZMANN) ** 0.25
    sky_temp_c = sky_temp_k - 273.15
    return sky_temp_c


def _calculate_absolute_humidity(temp_c, rel_hum, pressure_pa):
    """Compute absolute humidity (humidity ratio) from dry-bulb temperature,
    relative humidity and atmospheric pressure using the standard
    psychrometric relation, for the EPW -> ``.met`` direction (``.met``
    stores absolute humidity, ``AbsHum``/``wabs``, instead of pressure).

    Args:
        temp_c (float): Dry-bulb temperature in degrees Celsius.
        rel_hum (float): Relative humidity in percent (0-100). Values below
            0.1% are treated as perfectly dry air (returns 0.0 directly).
        pressure_pa (float): Atmospheric (station) pressure in Pascals.

    Returns:
        float: Absolute humidity (humidity ratio) in kg water / kg dry air,
        clipped to be non-negative.
    """
    if rel_hum < 0.1: return 0.0
    e_s = 610.78 * (10 ** (7.5 * temp_c / (237.3 + temp_c)))
    e = e_s * (rel_hum / 100.0)
    wabs = 0.62198 * e / (pressure_pa - e)
    return max(0, wabs)


def _set_epw_values(epw_obj, field_name, new_vals):
    """
    Assign *new_vals* to a Ladybug ``EPW`` hourly field, compensating for
    Ladybug's internal "point-in-time" index offset. Thin backward-compatible
    wrapper; the real (shared) implementation now lives in
    :func:`~pyweatherfiles.epw_field_utils.set_epw_values`, also used by
    :mod:`~pyweatherfiles.hourly_epw_converter` (see
    ``INFORME_REVISION_GENERAL.md`` §3.1/Fase 1).

    ``.met`` files index ``Hour=1`` as the first record (01:00), whereas
    Ladybug's *point-in-time* fields (e.g. dry-bulb temperature) expect index
    0 to correspond to January 1st, 00:00 (i.e. the *end* of the last hour of
    the year, rotated to the front). This helper shifts the values one
    position (``[last] + values[:-1]``) before assigning them so the
    resulting EPW file is correctly aligned; fields that are **not**
    point-in-time (e.g. cumulative/integrated quantities) are assigned as-is.

    Args:
        epw_obj (ladybug.epw.EPW): The EPW object being populated.
        field_name (str): Name of the EPW data-collection attribute to set
            (e.g. ``'dry_bulb_temperature'``, ``'global_horizontal_radiation'``).
        new_vals (list or tuple): The new hourly values (length 8760/8784),
            with index 0 corresponding to ``.met`` ``Hour=1``.

    Returns:
        None: The field is updated in place on *epw_obj*.
    """
    _shared_set_epw_values(epw_obj, field_name, new_vals)


def _get_epw_values(epw_obj, field_name):
    """
    Read hourly values from a Ladybug ``EPW`` field, compensating for the
    same "point-in-time" index offset described in :func:`_set_epw_values`,
    so that index 0 of the returned list corresponds to ``.met`` ``Hour=1``
    (01:00) rather than Ladybug's internal Jan-1st-00:00 convention. Thin
    backward-compatible wrapper around
    :func:`~pyweatherfiles.epw_field_utils.get_epw_values`.

    Args:
        epw_obj (ladybug.epw.EPW): The EPW object to read from.
        field_name (str): Name of the EPW data-collection attribute to read
            (e.g. ``'dry_bulb_temperature'``).

    Returns:
        list: The hourly values (length 8760/8784), re-aligned so index 0
        corresponds to ``.met`` ``Hour=1``.
    """
    return _shared_get_epw_values(epw_obj, field_name)


# --- MET -> EPW CONVERSION ---
def convert_met_to_epw(met_path: str, epw_path: str, base_epw_path: str, replace_unused_with_missing: bool = False, save_session: bool = True, session_dir: str = None) -> bool:
    """
    Convert a Spanish ``.met`` reference-climate file into an EPW file.

    This is the main conversion entry point of the module. It parses the
    ``.met`` metadata line (latitude/longitude/elevation, auto-located within
    the first 10 lines if not where expected) and its 13- or 15-column data
    block (see :data:`COLS_MET_13` / :data:`COLS_MET_15`), then:

    1. Loads *base_epw_path* as a template (for header fields and any EPW
       variable not present in ``.met``, such as illuminance).
    2. Reconstructs dew point (:func:`_calculate_dew_point`), atmospheric
       pressure (:func:`_calculate_variable_pressure_from_met`) and
       horizontal infrared radiation (Stefan-Boltzmann, from ``SkyTemp``).
    3. Reconstructs **GHI** (``RadDirectaHoriz + RadDifusaHoriz``, negative
       inputs clipped to 0) and **DNI** using the exact solar position at the
       midpoint of each hour (``ladybug.sunpath.Sunpath``), clipping to the
       solar constant (:data:`_DNI_MAX_PHYSICAL`) and printing a short
       quality-control report (DNI percentiles, number of low-sun hours,
       number of clips, and the radiation-balance residual
       ``GHI - (DHI + DNI*cos(zenith))``).
    4. Forces a standard, non-leap, 8760-hour ``AnalysisPeriod``.
    5. Optionally (``replace_unused_with_missing=True``) fills the 15 EPW
       fields that EnergyPlus does not use (illuminances, sky cover,
       visibility, precipitable water, etc.) with their official EPW
       "missing value" codes instead of leaving them at 0.
    6. Saves the resulting EPW to *epw_path* and, if ``save_session=True``
       (default), persists a reproducible session via
       :func:`~pyweatherfiles.session_manager.save_function_session`.

    Args:
        met_path (str): Path to the input ``.met`` file.
        epw_path (str): Path where the resulting ``.epw`` file will be
            written.
        base_epw_path (str): Path to a template EPW file used for header
            fields (city, comments) and for any variable not derivable from
            ``.met``.
        replace_unused_with_missing (bool, optional): If ``True``, neutralise
            the 15 EnergyPlus-unused EPW fields with their official missing-
            value codes. Defaults to ``False``.
        save_session (bool, optional): If ``True`` (default), save a
            reproducible ``.pkl``/``.json`` session next to *met_path* (or in
            *session_dir* if given).
        session_dir (str, optional): Directory to write the session files to.
            Defaults to the directory of *met_path*.

    Returns:
        bool: ``True`` if the conversion succeeded and the EPW file was
        written; ``False`` if any step failed (details are printed to the
        console).

    Example:
        >>> from pyweatherfiles import met_epw_converter
        >>> met_epw_converter.convert_met_to_epw(
        ...     met_path="seville.met",
        ...     base_epw_path="ESP_Sevilla.083910_IWEC.epw",
        ...     epw_path="sevilla_met.epw",
        ...     replace_unused_with_missing=True,
        ... )  # doctest: +SKIP
        True
    """
    print(f"Starting conversion of '{met_path}' to '{epw_path}'...")

    try:
        epw_data = EPW(base_epw_path)
        # EPW() is lazily loaded: the constructor itself never raises for a
        # missing/corrupt file, only a later attribute access does. Touch
        # .location here so any such error surfaces inside this try/except
        # instead of the unprotected code below (same pattern already fixed
        # in epw_comparator.py and hourly_epw_converter.py).
        _ = epw_data.location
    except Exception as e:
        print(f"Error loading template: {e}")
        return False

    try:
        with open(met_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        print(f"Error: File not found.")
        return False

    # --- HEADER PROCESSING ---
    if len(lines) < 3:
        print("Critical Error: The .met file is too short.")
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
        print("Critical Error: No valid geographic metadata found.")
        return False

    tz_hour = round(lon / 15.0)

    epw_data.location.city = os.path.basename(met_path).split('.')[0].capitalize()
    epw_data.location.latitude = lat
    epw_data.location.longitude = lon
    epw_data.location.time_zone = tz_hour
    epw_data.location.elevation = elev
    epw_data.comments_1 = f"Converted from {os.path.basename(met_path)}"
    epw_data.comments_2 = "Direct Normal Radiation recalculated astronomically."

    # --- DATA START DETECTION ---
    data_start_index = meta_line_index + 1
    first_data_line = lines[data_start_index].split()

    if first_data_line[0] != '1' or first_data_line[1] != '1' or first_data_line[2] != '1':
        for i in range(data_start_index, min(data_start_index + 10, len(lines))):
            parts = lines[i].split()
            if len(parts) > 5 and parts[0] == '1' and parts[1] == '1' and parts[2] == '1':
                data_start_index = i
                break

    # --- PANDAS READ ---
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
            print(f"Critical Error: The file has {num_cols} columns.")
            return False

    except Exception as e:
        print(f"Error processing MET data: {e}")
        return False

    # --- STANDARD YEAR CORRECTION ---
    try:
        epw_data._analysis_period = AnalysisPeriod(st_month=1, st_day=1, st_hour=1, end_month=12, end_day=31, end_hour=24)
        epw_data._is_leap_year = False
    except Exception:
        pass

    # --- DIRECT ASSIGNMENT WITH CORRECTED OFFSET ---
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

    # --- INFRARED RADIATION CONVERSION ---
    ir_values = []
    for t_sky in df['SkyTemp']:
        t_sky_k = t_sky + 273.15
        ir = _STEFAN_BOLTZMANN * (t_sky_k ** 4)
        ir_values.append(ir)
    _set_epw_values(epw_data, 'horizontal_infrared_radiation_intensity', ir_values)

    # --- SOLAR RADIATION CONVERSION WITH ASTRONOMICAL PRECISION ---
    print("  - Recalculating zenith angle (theta_z) and balancing radiation...")
    # FIX: Sunpath does not accept 'elevation', only lat, lon, and tz.
    sp = Sunpath(latitude=lat, longitude=lon, time_zone=tz_hour)

    ghi_values = []
    dni_values = []
    balance_residual_values = []
    negative_direct_input_count = 0
    dni_clipped_count = 0
    low_sun_count = 0

    for m, d, h, dir_horiz, diff_horiz in zip(df['Month'], df['Day'], df['Hour'], df['RadDirectaHoriz'], df['RadDifusaHoriz']):

        raw_dir_horiz = float(dir_horiz)
        raw_diff_horiz = float(diff_horiz)
        if raw_dir_horiz < 0:
            negative_direct_input_count += 1

        # Avoids propagating negative input radiation caused by MET rounding/noise.
        dir_horiz = max(0.0, raw_dir_horiz)
        diff_horiz = max(0.0, raw_diff_horiz)

        # 1. GHI = Direct Horizontal + Diffuse Horizontal
        ghi = dir_horiz + diff_horiz
        ghi_values.append(ghi)

        # 2. Calculate the precise theta_z for the midpoint of the hour
        # NOTE on the -0.5 offset (see also hourly_epw_converter.py, which
        # uses +0.5): the `Hour` column of .met files runs from 1 to 24 and
        # marks the END of the hourly interval (e.g. Hour=10 -> the
        # [9:00, 10:00) interval), whose midpoint is Hour - 0.5. CSV/XLSX
        # hourly files instead use `dt.hour` from 0 to 23 marking the START of
        # the interval, whose midpoint is hour + 0.5. Both are correct for
        # their respective source convention; this is not an inconsistency to fix.
        calc_hour = float(h) - 0.5
        sun = sp.calculate_sun(month=int(m), day=int(d), hour=calc_hour)
        zenith_deg = 90.0 - sun.altitude

        # 3. Calculate DNI
        cos_zenith = math.cos(math.radians(zenith_deg))

        if cos_zenith <= _COS_ZENITH_MIN or dir_horiz <= 0.0:
            low_sun_count += 1
            dni = 0.0
        else:
            dni = max(0.0, dir_horiz / cos_zenith)
            if dni > _DNI_MAX_PHYSICAL:
                dni = _DNI_MAX_PHYSICAL
                dni_clipped_count += 1

        dni_values.append(dni)
        balance_residual = ghi - (diff_horiz + dni * max(cos_zenith, 0.0))
        balance_residual_values.append(balance_residual)

    if dni_values:
        dni_arr = np.array(dni_values, dtype=float)
        residual_arr = np.array(balance_residual_values, dtype=float)
        print(
            "  - QA DNI -> "
            f"min={np.min(dni_arr):.1f}, p95={np.percentile(dni_arr, 95):.1f}, max={np.max(dni_arr):.1f} W/m2 | "
            f"low_sun={low_sun_count}, clipped={dni_clipped_count}, negative_dir_horiz={negative_direct_input_count}"
        )
        print(
            "  - QA balance (GHI - (DHI + DNI*cos(theta_z))) -> "
            f"abs_mean={np.mean(np.abs(residual_arr)):.2f} W/m2, abs_p95={np.percentile(np.abs(residual_arr), 95):.2f} W/m2"
        )

    _set_epw_values(epw_data, 'global_horizontal_radiation', ghi_values)
    _set_epw_values(epw_data, 'direct_normal_radiation', dni_values)

    if replace_unused_with_missing:
        # Only variables marked 'N' (Not used by EnergyPlus) are included
        # (map and logic shared with hourly_epw_converter.py — see
        # pyweatherfiles.epw_field_utils.neutralize_unused_epw_fields)
        neutralize_unused_epw_fields(epw_data, len(df))

    try:
        with suppress_stdout_stderr():
            epw_data.save(epw_path)
    except Exception as e:
        print(f"Error saving EPW: {e}")
        return False

    print("MET -> EPW conversion completed (radiation balance ensured)!")

    # --- Session persistence ---
    if save_session:
        _inputs = {
            "met_path": met_path,
            "epw_path": epw_path,
            "base_epw_path": base_epw_path,
        }
        _extra = {"replace_unused_with_missing": replace_unused_with_missing}
        _dir = session_dir or os.path.dirname(os.path.abspath(met_path)) or os.getcwd()
        try:
            save_function_session("convert_met_to_epw", _inputs, result=True,
                                  session_dir=_dir, extra=_extra)
        except Exception as _e:
            print(f"[SESSION] Could not save the session: {_e}")

    return True


# --- EPW -> MET CONVERSION ---
def convert_epw_to_met(epw_path: str, met_path: str) -> bool:
    """
    Convert an EPW file back into the 13-column ``.met`` reference-climate
    format (the inverse of :func:`convert_met_to_epw`).

    Reads dry-bulb temperature, relative humidity, wind speed/direction,
    global/diffuse horizontal radiation and horizontal infrared radiation
    from *epw_path* (via :func:`_get_epw_values`, which corrects Ladybug's
    point-in-time index offset), then reconstructs the ``.met``-specific
    fields:

    - ``RadDirectaHoriz = GHI - DHI`` (clipped to be ``>= 0``);
      ``RadDifusaHoriz = DHI`` directly (DNI is **not** stored, since the
      ``.met`` format only keeps horizontal components).
    - ``Tcielo`` (sky temperature) via Stefan-Boltzmann inversion of the
      horizontal infrared radiation intensity (see
      :func:`_calculate_sky_temperature`).
    - ``wabs`` (absolute humidity) via the standard psychrometric formula
      (see :func:`_calculate_absolute_humidity`), using the standard
      barometric pressure estimate for the EPW's elevation (see
      :func:`_calculate_atmos_pressure`).
    - Timestamps are fixed to the (arbitrary, non-leap) year 2005;
      ``Azimuth``/``Zenith`` are written as ``0`` (not reconstructed, since
      the ``.met`` format's own file header already fixes the time zone
      implicitly via longitude).

    The metadata line is written first (``tz*15`` "solar longitude" plus the
    filename, then ``lat  lon  elevation  0.0``), followed by the
    space-separated, header-less data block.

    Args:
        epw_path (str): Path to the source EPW file.
        met_path (str): Path where the resulting ``.met`` file will be
            written.

    Returns:
        bool: ``True`` if the conversion succeeded; ``False`` if reading the
        EPW or writing the ``.met`` file failed (details are printed to the
        console).

    Example:
        >>> from pyweatherfiles import met_epw_converter
        >>> met_epw_converter.convert_epw_to_met(
        ...     epw_path="sevilla_tmy.epw",
        ...     met_path="sevilla_tmy_roundtrip.met",
        ... )  # doctest: +SKIP
        True
    """
    print(f"\n--- Starting conversion of '{epw_path}' to '{met_path}' ---")

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
        print(f"Error reading EPW: {e}")
        return False

    df_met = pd.DataFrame()

    df_met['Mes'] = [pd.Timestamp(2005, 1, 1) + pd.Timedelta(hours=i) for i in range(8760)]
    df_met['Mes_Num'] = df_met['Mes'].dt.month
    df_met['Dia'] = df_met['Mes'].dt.day
    df_met['Hora'] = df_met['Mes'].dt.hour + 1

    df_met['Taire'] = dry_bulb

    # RESTORED: _calculate_sky_temperature function
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

        print("EPW -> MET conversion completed!")
        return True

    except Exception as e:
        print(f"Error writing MET: {e}")
        return False