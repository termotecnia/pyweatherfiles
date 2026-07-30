# -*- coding: utf-8 -*-
"""
hourly_epw_converter.py
=========================

Convert already-cleaned hourly weather series (CSV/Excel) into EPW
(EnergyPlus Weather) files.

This module provides the "last mile" export step of the package's pipeline:
once a series is clean (no gaps — see
:class:`~pyweatherfiles.climate_processor.ClimateProcessor` if it is not) and
either represents several real years or the synthetic Typical Meteorological
Year produced by :class:`~pyweatherfiles.tmy.TMYGenerator`, it needs to become
one ``.epw`` file per year that EnergyPlus (or any EPW-compatible tool) can
consume. That is exactly what :class:`HourlyEPWConverter` does for a single
data source, and what :class:`BatchHourlyEPWConverter` does for many
cities/zones at once.

Two public classes
-------------------
- :class:`HourlyEPWConverter` — reads one hourly CSV/Excel file, derives any
  missing physical quantity (relative humidity, atmospheric pressure,
  diffuse horizontal radiation) with well-known formulas, and writes one EPW
  file per available year (or per a requested subset of years).
- :class:`BatchHourlyEPWConverter` — a thin orchestration layer that
  instantiates one :class:`HourlyEPWConverter` per city/zone in a
  configuration list/DataFrame and runs them all, optionally auto-detecting
  the configuration by matching file names against a list of identifiers
  (see :meth:`BatchHourlyEPWConverter.suggest_config`).

Unit conventions (important!)
------------------------------
Input wind speed is assumed to be in **km/h** (converted to m/s by dividing
by 3.6) and input pressure is assumed to be in **hPa** (converted to Pa by
multiplying by 100). If your source file already uses SI units, convert it
back to km/h / hPa first, or the resulting EPW will be silently wrong.

Example
-------
Converting a multi-year clean hourly series into one EPW per year::

    from pyweatherfiles import hourly_epw_converter

    converter = hourly_epw_converter.HourlyEPWConverter(
        file_path="weather_data.csv",      # already clean, no gaps
        base_epw_path="template.epw",      # provides lat/lon/elevation/time zone
    )
    converter.process(output_pattern="city_{year}.epw")

Batch-processing several cities at once, auto-matching data files to EPW
templates by name::

    from pyweatherfiles import hourly_epw_converter

    config = hourly_epw_converter.BatchHourlyEPWConverter.suggest_config(
        identifiers=["MADRID", "SEVILLE"],
        data_files="path/to/data/",
        base_epw_files="path/to/epws/",
    )
    batch = hourly_epw_converter.BatchHourlyEPWConverter(config, output_dir="output/")
    batch.process_all(output_pattern="{identifier}_{year}.epw")
"""
import pandas as pd
import numpy as np
import math
import os
from .session_manager import save_object_session
from .epw_field_utils import calculate_atmos_pressure, set_epw_values, neutralize_unused_epw_fields

try:
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    from ladybug.analysisperiod import AnalysisPeriod
except ImportError:
    raise ImportError("La librería 'ladybug-core' no está instalada.")


class HourlyEPWConverter:
    """
    Convert an already-cleaned hourly weather series (CSV/Excel) into one EPW
    file per available year, disabling the EPW fields that EnergyPlus does
    not actually use.

    The constructor only loads and prepares the data (see :meth:`_load_file`);
    call :meth:`process` (which internally calls :meth:`transform_to_epw` once
    per year) to actually write the EPW file(s).

    Attributes:
        file_path (str): Path to the source hourly CSV/Excel file, as passed
            to the constructor.
        base_epw_path (str): Path to the EPW template used for header fields
            and any variable not present in the source file.
        lat (float): Site latitude in degrees (explicit or auto-extracted
            from *base_epw_path*).
        lon (float): Site longitude in degrees.
        elev (float): Site elevation in metres.
        tz_hour (float): UTC time-zone offset in hours.
        preserve_extra (bool): If ``True``, an existing cloud-cover column is
            kept in ``total_sky_cover`` instead of it being overwritten by
            the "unused field" neutralisation step.
        remove_leap_day (bool): If ``True`` (default), drop
            February 29th from every processed year so the output always
            has 8760 hours.
        col_mapping (dict): The effective column-name mapping in use (merges
            the individual ``col_*``/``datetime_col`` constructor arguments
            with any *column_mapping* dict override); keys are canonical
            names (``'datetime'``, ``'temp'``, ``'dew'``, ``'wind_speed'``,
            ``'ghi'``, ``'dni'``, ``'rh'``, ``'pres'``, ``'wind_dir'``,
            ``'dhi'``, ``'cloud_cover'``, ``'irh'``), values are the actual
            column names expected in the source file.
        datetime_col, col_temp, col_dew, col_wind, col_ghi, col_dni,
        col_rh, col_pres, col_wind_dir, col_dhi, col_cloud_cover, col_irh (str):
            Convenience direct attributes mirroring the corresponding entries
            of :attr:`col_mapping`.
        df (pandas.DataFrame): The loaded hourly source data, sorted
            chronologically, with wind speed converted to m/s and pressure
            to Pa (see :meth:`_load_file`).
        available_years (list[int]): Calendar years present in :attr:`df`.

    Example:
        >>> from pyweatherfiles import hourly_epw_converter
        >>> converter = hourly_epw_converter.HourlyEPWConverter(
        ...     file_path="weather_data.csv",
        ...     base_epw_path="template.epw",
        ... )  # doctest: +SKIP
        >>> converter.available_years  # doctest: +SKIP
        [2018, 2019, 2020]
        >>> converter.process(output_pattern="city_{year}.epw")  # doctest: +SKIP
        [2018, 2019, 2020]
    """
    
    def __init__(self, file_path, base_epw_path, lat=None, lon=None, elev=None, tz_hour=None,
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
        """Load and prepare the hourly source file for conversion.

        If *lat*/*lon*/*elev*/*tz_hour* are not all given explicitly, they
        are auto-extracted from *base_epw_path* via
        ``ladybug.epw.EPW(base_epw_path).location`` — a ``ValueError`` is
        raised if any of the four cannot be determined either way.

        Args:
            file_path (str): Path to the source hourly CSV or Excel file
                (already cleaned/gap-filled).
            base_epw_path (str): Path to an EPW file used as a template for
                header fields (and for lat/lon/elev/tz_hour, if not given
                explicitly).
            lat (float, optional): Site latitude in degrees. Auto-extracted
                from *base_epw_path* if ``None``.
            lon (float, optional): Site longitude in degrees. Auto-extracted
                if ``None``.
            elev (float, optional): Site elevation in metres. Auto-extracted
                if ``None``.
            tz_hour (float, optional): UTC time-zone offset in hours.
                Auto-extracted if ``None``.
            datetime_col (str, optional): Name of the timestamp column.
                Defaults to ``'time'``.
            col_temp (str, optional): Name of the dry-bulb temperature
                column (degrees Celsius). Defaults to
                ``'Dry-bulb temperature'``.
            col_dew (str, optional): Name of the dew-point temperature
                column (degrees Celsius). Defaults to
                ``'Dew Point temperature'``.
            col_wind (str, optional): Name of the wind-speed column
                (**assumed to be in km/h**, converted to m/s on load).
                Defaults to ``'Wind Speed'``.
            col_ghi (str, optional): Name of the global horizontal
                irradiance column (Wh/m2). Defaults to
                ``'Global Horizontal Irradiance '`` (note the trailing
                space, matching common source-file headers).
            col_dni (str, optional): Name of the direct/beam normal
                irradiance column (Wh/m2). Defaults to
                ``'Beam Normal Irradiance '``.
            col_rh (str, optional): Name of the relative-humidity column
                (%). Reconstructed via :meth:`_calculate_rh` if the column
                is absent. Defaults to ``'Relative Humidity'``.
            col_pres (str, optional): Name of the atmospheric-pressure
                column (**assumed to be in hPa**, converted to Pa on load).
                Reconstructed via :meth:`_calculate_atmos_pressure` if
                absent. Defaults to ``'Pressure'``.
            col_wind_dir (str, optional): Name of the wind-direction column
                (degrees). Filled with 0 if absent. Defaults to
                ``'Wind Direction'``.
            col_dhi (str, optional): Name of the diffuse horizontal
                irradiance column (Wh/m2). Reconstructed from GHI/DNI and
                exact solar position if absent. Defaults to
                ``'Diffuse Horizontal Irradiance'``.
            col_cloud_cover (str, optional): Name of the total-cloud-cover
                column (used for the optional ``total_sky_cover`` EPW
                field). Defaults to ``'Total Cloud Cover'``.
            col_irh (str, optional): Name of the horizontal infrared
                radiation intensity column. Defaults to ``'IRh'``.
            column_mapping (dict, optional): Extra overrides merged on top
                of the individual ``col_*``/``datetime_col`` arguments
                (keys are the canonical names listed in :attr:`col_mapping`).
            preserve_extra (bool, optional): If ``True``, do not neutralise
                ``total_sky_cover`` when a cloud-cover column is available.
                Defaults to ``False``.
            remove_leap_day (bool, optional): If ``True`` (default), drop
                February 29th from every processed year so the output always
                has 8760 hours.

        Raises:
            ValueError: If latitude/longitude/elevation/time-zone could not
                be determined either explicitly or from *base_epw_path*.
        """

        # Atributos geográficos
        self.file_path = file_path
        self.base_epw_path = base_epw_path
        
        extracted_lat, extracted_lon, extracted_elev, extracted_tz = None, None, None, None
        if lat is None or lon is None or elev is None or tz_hour is None:
            try:
                epw_data = EPW(self.base_epw_path)
                extracted_lat = float(epw_data.location.latitude)
                extracted_lon = float(epw_data.location.longitude)
                extracted_elev = float(epw_data.location.elevation)
                extracted_tz = float(epw_data.location.time_zone)
            except Exception as e:
                print(f"Advertencia: No se pudieron extraer datos base de '{self.base_epw_path}': {e}")
                
        self.lat = lat if lat is not None else extracted_lat
        self.lon = lon if lon is not None else extracted_lon
        self.elev = elev if elev is not None else extracted_elev
        self.tz_hour = tz_hour if tz_hour is not None else extracted_tz
        
        if None in (self.lat, self.lon, self.elev, self.tz_hour):
            raise ValueError("No se pudieron determinar todos los parámetros geográficos (lat, lon, elev, tz_hour). Introdúzcalos manualmente.")
            
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
        """Read :attr:`file_path` (``.xlsx`` or ``.csv``, auto-detected by
        extension) into :attr:`df`, sort it chronologically by
        :attr:`datetime_col`, apply the fixed unit conversions, and record
        the available years.

        Unit conversions applied (package-wide convention, **not**
        configurable): wind speed is divided by 3.6 (assumed input km/h ->
        m/s) and pressure is multiplied by 100 (assumed input hPa -> Pa),
        whenever those columns are present.

        Returns:
            None: Populates ``self.df`` and ``self.available_years`` in
            place.
        """
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
        """Return an isolated copy of :attr:`df` restricted to a single
        calendar year.

        Args:
            year (int): Calendar year to extract; must be one of
                :attr:`available_years`.

        Returns:
            pandas.DataFrame: Rows of :attr:`df` whose :attr:`datetime_col`
            falls within *year* (a copy, safe to mutate).

        Raises:
            ValueError: If *year* is not in :attr:`available_years`.

        Example:
            >>> converter.get_year_data(2019).shape[0] in (8760, 8784)  # doctest: +SKIP
            True
        """
        if year not in self.available_years:
            raise ValueError(f"El año {year} no está disponible en este archivo.")
        return self.df[self.df[self.datetime_col].dt.year == year].copy()

    def _calculate_rh(self, tdb, tdp):
        """Estimate relative humidity from dry-bulb and dew-point
        temperature using a Magnus-type saturation-vapour-pressure ratio:
        ``RH = 100 * e_s(Tdp) / e_s(Tdb)``, clipped to ``[0, 100]``.

        Used as a fallback when :attr:`col_rh` is not present in the source
        file.

        Args:
            tdb (float): Dry-bulb temperature in degrees Celsius.
            tdp (float): Dew-point temperature in degrees Celsius (clipped
                to *tdb* if greater, which would be physically inconsistent).

        Returns:
            float: Relative humidity in percent (0-100). Returns ``50.0`` if
            either input is ``NaN``.
        """
        if pd.isna(tdb) or pd.isna(tdp):
            return 50.0
        if tdp > tdb:
            tdp = tdb
        es = 6.112 * math.exp((17.67 * tdb) / (tdb + 243.5))
        e = 6.112 * math.exp((17.67 * tdp) / (tdp + 243.5))
        rh = (e / es) * 100.0
        return min(max(rh, 0.0), 100.0)

    def _calculate_atmos_pressure(self):
        """Estimate the standard atmospheric pressure at :attr:`elev` using
        the international barometric formula (constant lapse-rate model),
        used as a fallback when :attr:`col_pres` is not present in the
        source file. Thin backward-compatible wrapper; the real (shared)
        implementation now lives in
        :func:`~pyweatherfiles.epw_field_utils.calculate_atmos_pressure`,
        also used by :mod:`~pyweatherfiles.met_epw_converter` (see
        ``INFORME_REVISION_GENERAL.md`` §3.1/Fase 1).

        Returns:
            float: Estimated atmospheric pressure in Pascals.
        """
        return calculate_atmos_pressure(self.elev)

    def _set_epw_values(self, epw_obj, field_name, new_vals):
        """
        Assign *new_vals* to a Ladybug ``EPW`` hourly field, compensating for
        Ladybug's internal "point-in-time" index offset. Thin backward-compatible
        wrapper kept for any external caller relying on this instance method;
        the real (shared) implementation now lives in
        :func:`~pyweatherfiles.epw_field_utils.set_epw_values`, also used by
        :mod:`~pyweatherfiles.met_epw_converter` (see
        ``INFORME_REVISION_GENERAL.md`` §3.1/Fase 1).

        Args:
            epw_obj (ladybug.epw.EPW): The EPW object being populated.
            field_name (str): Name of the EPW data-collection attribute to
                set (e.g. ``'dry_bulb_temperature'``).
            new_vals (list or tuple): The new hourly values, index 0 =
                first hour of the source data (typically Jan 1st, 00:00 or
                01:00 depending on the source file's convention).

        Returns:
            None: The field is updated in place on *epw_obj*.
        """
        set_epw_values(epw_obj, field_name, new_vals)

    def transform_to_epw(self, df_year, output_epw_path, base_epw_path=None):
        """
        Convert a single year's worth of hourly data into an EPW file.

        Steps: adjust the year to exactly 8760 (non-leap) or 8784 (leap)
        hours according to :attr:`remove_leap_day` (dropping February 29th,
        padding a warning if too short, or truncating if too long); load
        *base_epw_path* (or :attr:`base_epw_path`) as a template and update
        its header (lat/lon/elevation/time-zone/comments) and
        ``AnalysisPeriod``; extract and inject (via :meth:`_set_epw_values`)
        dry-bulb/dew-point temperature, relative humidity (reconstructed via
        :meth:`_calculate_rh` if absent), wind speed/direction (0 if
        direction absent), global/direct-normal/diffuse-horizontal radiation
        (diffuse reconstructed from GHI/DNI and exact solar position via
        ``ladybug.sunpath.Sunpath`` if absent) and atmospheric pressure
        (reconstructed via :meth:`_calculate_atmos_pressure` if absent);
        optionally inject cloud cover / horizontal infrared radiation if
        those columns exist; neutralise the 15 EnergyPlus-unused EPW fields
        with their official "missing value" codes; finally save the EPW.

        Args:
            df_year (pandas.DataFrame): A single year's hourly data (as
                returned by :meth:`get_year_data`).
            output_epw_path (str): Path where the resulting ``.epw`` file
                will be written.
            base_epw_path (str, optional): EPW template to use instead of
                :attr:`base_epw_path` for this specific call.

        Returns:
            bool: ``True`` if the EPW file was written successfully;
            ``False`` if loading the template or saving the result failed
            (details printed to the console).

        Example:
            >>> df_2019 = converter.get_year_data(2019)  # doctest: +SKIP
            >>> converter.transform_to_epw(df_2019, "city_2019.epw")  # doctest: +SKIP
            True
        """
        base_epw_path = base_epw_path or self.base_epw_path
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
                
                # NOTE on the +0.5 offset (see also met_epw_converter.py, which
                # uses -0.5): `dt.hour` here is 0-23 and marks the START of the
                # hourly interval (e.g. h=10 -> the [10:00, 11:00) interval),
                # so its midpoint is h + 0.5. `.met` files instead use an
                # `Hour` column of 1-24 marking the END of the interval (e.g.
                # Hour=10 -> the [9:00, 10:00) interval), whose midpoint is
                # Hour - 0.5. Both are correct for their respective source
                # convention; this is not an inconsistency to "fix".
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
        # (mapa y lógica compartidos con met_epw_converter.py — ver
        # pyweatherfiles.epw_field_utils.neutralize_unused_epw_fields)
        skip_fields = None
        if self.preserve_extra and self.col_cloud_cover in df_y.columns:
            skip_fields = {'total_sky_cover'}

        neutralize_unused_epw_fields(epw_data, len(df_y), skip_fields=skip_fields)

        # Guardado del EPW en disco
        try:
            epw_data.save(output_epw_path)
            return True
        except Exception as e:
            print(f"Error al guardar el EPW de salida: {e}")
            return False

    def process(self, output_dir=".", years=None, remove_leap_day=None, output_pattern=None, base_epw_path=None, save_session=True, session_dir=None, **kwargs):
        """
        Automate the full conversion process: generate one EPW file per
        requested year (or every year in :attr:`available_years` if *years*
        is ``None``) by calling :meth:`transform_to_epw` once per year.

        Args:
            output_dir (str, optional): Directory where the EPW files will
                be written. Defaults to ``"."`` (current directory).
            years (list[int], optional): Specific years to process. Years
                not present in :attr:`available_years` are skipped with a
                warning. Defaults to all available years.
            remove_leap_day (bool, optional): Overrides :attr:`remove_leap_day`
                for this call if given.
            output_pattern (str, optional): Filename pattern passed through
                ``str.format(year=..., **kwargs)`` (e.g.
                ``'city_{year}.epw'``). Falls back to
                ``'{source_basename}_{year}.epw'`` if ``None`` or if the
                pattern references an unknown key.
            base_epw_path (str, optional): Overrides :attr:`base_epw_path`
                for this call if given.
            save_session (bool, optional): If ``True`` (default), persist a
                reproducible ``.pkl``/``.json`` session (recording
                *file_path*, *base_epw_path* and the successfully processed
                years) via
                :func:`~pyweatherfiles.session_manager.save_object_session`.
            session_dir (str, optional): Directory for the session files.
                Defaults to the directory of :attr:`file_path`.
            **kwargs: Extra keyword arguments forwarded to
                ``output_pattern.format()`` (e.g. an ``identifier`` used by
                :class:`BatchHourlyEPWConverter`).

        Returns:
            list[int]: The years that were successfully converted and saved
            (a subset of the requested *years*/:attr:`available_years`).

        Example:
            >>> converter.process(output_pattern="seville_{year}.epw")  # doctest: +SKIP
            [2018, 2019, 2020]
        """
        base_epw_path = base_epw_path or self.base_epw_path
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
            success = self.transform_to_epw(df_year, output_path, base_epw_path=base_epw_path)
            if success:
                print(f"¡Éxito! Año {year} guardado en: {output_path}")
                success_list.append(year)
            else:
                print(f"Fallo al procesar guardado de {year}.")

        # --- Session persistence ---
        if save_session and success_list:
            _inputs = {
                "file_path": self.file_path,
                "base_epw_path": self.base_epw_path,
                "years": str(sorted(success_list)),
            }
            _dir = session_dir or os.path.dirname(os.path.abspath(self.file_path)) or os.getcwd()
            try:
                save_object_session(self, "HourlyEPWConverter", _inputs, session_dir=_dir)
            except Exception as _e:
                print(f"[SESSION] No se pudo guardar la sesión: {_e}")

        return success_list


class BatchHourlyEPWConverter:
    """
    Iterate :class:`HourlyEPWConverter` over multiple weather-data files
    (e.g. one per city or climate zone) and generate their respective EPW
    files in a single call.

    This class does not implement any conversion logic itself — it validates
    a configuration list, instantiates one :class:`HourlyEPWConverter` per
    entry, and delegates to :meth:`HourlyEPWConverter.process`.

    Attributes:
        cities_config (list[dict]): One configuration dict per city/zone,
            each containing at least the mandatory keys returned by
            :meth:`get_mandatory_config_keys` (``'file_path'``,
            ``'base_epw_path'``), plus any optional keys
            (``'lat'``/``'lon'``/``'elev'``/``'tz_hour'``, ``'years'``, any
            of the ``col_*``/``column_mapping``/``preserve_extra``
            :class:`HourlyEPWConverter` constructor options, and any free-
            form key used to format ``output_pattern``, e.g.
            ``'identifier'``). If a :class:`pandas.DataFrame` is passed to
            the constructor, it is converted to this list-of-dicts form via
            ``to_dict(orient='records')``.
        output_dir (str): Directory where every generated EPW file will be
            written.

    Example:
        >>> from pyweatherfiles import hourly_epw_converter
        >>> cities_config = [
        ...     {"file_path": "madrid.xlsx", "base_epw_path": "madrid_template.epw", "identifier": "MADRID"},
        ...     {"file_path": "seville.xlsx", "base_epw_path": "seville_template.epw", "identifier": "SEVILLE"},
        ... ]
        >>> batch = hourly_epw_converter.BatchHourlyEPWConverter(cities_config, output_dir="output/")  # doctest: +SKIP
        >>> batch.process_all(output_pattern="{identifier}_{year}.epw")  # doctest: +SKIP
    """

    # Atributo de clase con las llaves requeridas
    MANDATORY_KEYS = ['file_path', 'base_epw_path']
    """list[str]: Class attribute listing the configuration keys every
    entry of :attr:`cities_config` must contain (see
    :meth:`get_mandatory_config_keys`)."""

    @classmethod
    def get_mandatory_config_keys(cls):
        """
        Print and return the list of mandatory configuration keys every
        dict/DataFrame row in ``cities_config`` must contain.

        Returns:
            list[str]: ``['file_path', 'base_epw_path']`` (also available
            directly as :attr:`MANDATORY_KEYS`).

        Example:
            >>> from pyweatherfiles.hourly_epw_converter import BatchHourlyEPWConverter
            >>> BatchHourlyEPWConverter.get_mandatory_config_keys()
            Las llaves de configuración obligatorias para cada archivo son:
             - 'file_path': Ruta al Excel u origen de datos horario.
             - 'base_epw_path': Plantilla .epw a usar como base para este archivo.
            Las llaves opcionales (pero recomendables si no se pueden extraer del EPW de base) son: 'lat', 'lon', 'elev', 'tz_hour'.
            ['file_path', 'base_epw_path']
        """
        print("Las llaves de configuración obligatorias para cada archivo son:")
        for key in cls.MANDATORY_KEYS:
            if key == 'file_path':
                print(f" - '{key}': Ruta al Excel u origen de datos horario.")
            elif key == 'base_epw_path':
                print(f" - '{key}': Plantilla .epw a usar como base para este archivo.")
        print("Las llaves opcionales (pero recomendables si no se pueden extraer del EPW de base) son: 'lat', 'lon', 'elev', 'tz_hour'.")
        return cls.MANDATORY_KEYS

    def __init__(self, cities_config, output_dir="."):
        """Store the batch configuration and output directory (no
        conversion happens yet — call :meth:`process_all` for that).

        Args:
            cities_config (list[dict] or pandas.DataFrame): One entry per
                city/zone. Must contain at least the keys from
                :meth:`get_mandatory_config_keys` (``'file_path'``,
                ``'base_epw_path'``). Optional keys: ``'lat'``, ``'lon'``,
                ``'elev'``, ``'tz_hour'``, ``'years'`` (list of years to
                process for that entry only), any
                :class:`HourlyEPWConverter` ``col_*``/``column_mapping``/
                ``preserve_extra`` constructor option, and any free-form key
                used to format ``output_pattern`` in :meth:`process_all`
                (e.g. ``'identifier'``). A DataFrame is converted internally
                via ``to_dict(orient='records')``.
            output_dir (str, optional): Directory where every generated EPW
                file will be written. Defaults to ``"."``.
        """
        if isinstance(cities_config, pd.DataFrame):
            self.cities_config = cities_config.to_dict(orient='records')
        else:
            self.cities_config = cities_config

        self.output_dir = output_dir

    @classmethod
    def suggest_config(cls, identifiers, data_files, base_epw_files):
        """
        Auto-generate a ``cities_config`` list by matching a list of
        identifiers (e.g. city names, climate-zone codes) against two
        sources of files (hourly data files and EPW templates), and extract
        latitude/longitude/elevation/time-zone from each matched EPW
        template via Ladybug.

        Matching rule: for each *identifier*, the first *data_files* entry
        whose (lower-cased) base name contains the (lower-cased) identifier
        as a substring is taken as its data file, and likewise for
        *base_epw_files*. Identifiers with no match on either side are
        skipped (with a warning printed); no config entry is created for
        them.

        Args:
            identifiers (list[str]): Identifiers to search for, e.g.
                ``['MADRID', 'SEVILLE']``.
            data_files (list[str] or str): List of paths to ``.xlsx``/``.csv``
                data files, or a directory path (in which case every
                ``.xlsx``/``.csv`` file inside it is used).
            base_epw_files (list[str] or str): List of paths to ``.epw``
                template files, or a directory path (every ``.epw`` file
                inside it is used).

        Returns:
            list[dict]: One config dict per successfully matched identifier,
            with keys ``'identifier'``, ``'file_path'``, ``'base_epw_path'``,
            ``'lat'``, ``'lon'``, ``'elev'`` and ``'tz_hour'`` — ready to be
            passed straight to the :class:`BatchHourlyEPWConverter`
            constructor.

        Example:
            >>> from pyweatherfiles import hourly_epw_converter
            >>> config = hourly_epw_converter.BatchHourlyEPWConverter.suggest_config(
            ...     identifiers=["MADRID", "SEVILLE"],
            ...     data_files="path/to/data/",
            ...     base_epw_files="path/to/epws/",
            ... )  # doctest: +SKIP
            >>> batch = hourly_epw_converter.BatchHourlyEPWConverter(config, output_dir="output/")  # doctest: +SKIP
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

    def process_all(self, output_pattern=None, remove_leap_day=True, save_session=True, session_dir=None, **global_kwargs):
        """
        Run the conversion for every entry in :attr:`cities_config`: for
        each one, validate that the mandatory keys are present, instantiate
        a :class:`HourlyEPWConverter` (forwarding lat/lon/elev/tz_hour and
        any recognised ``col_*``/``column_mapping``/``preserve_extra``
        options found in the entry), and call
        :meth:`HourlyEPWConverter.process` on it.

        *global_kwargs* are merged with each entry's own free-form keys
        (entry-specific values win) to fill in ``output_pattern`` — this is
        how, for example, an ``'identifier'`` key set per-city in
        :attr:`cities_config` (see :meth:`suggest_config`) ends up
        substituted into a pattern like ``'{identifier}_{year}.epw'``.

        Args:
            output_pattern (str, optional): Filename pattern forwarded to
                :meth:`HourlyEPWConverter.process` for every entry (e.g.
                ``'{identifier}_{year}.epw'``).
            remove_leap_day (bool, optional): Forwarded to every
                :meth:`HourlyEPWConverter.process` call. Defaults to
                ``True``.
            save_session (bool, optional): If ``True`` (default), persist a
                reproducible ``.pkl``/``.json`` session for the **batch as a
                whole** (not per-city; each :class:`HourlyEPWConverter` call
                also saves/does not save its own session according to its
                own defaults) via
                :func:`~pyweatherfiles.session_manager.save_object_session`.
            session_dir (str, optional): Directory for the batch session
                files. Defaults to :attr:`output_dir`.
            **global_kwargs: Extra keyword arguments merged into every
                entry's ``output_pattern.format()`` call (entry-specific
                keys take precedence over these).

        Returns:
            dict[str, list[int]]: Mapping of each processed entry's
            ``file_path`` to the list of years it successfully converted
            (as returned by :meth:`HourlyEPWConverter.process`). Entries
            missing a mandatory key are skipped and absent from the result.

        Example:
            >>> batch.process_all(output_pattern="{identifier}_{year}.epw")  # doctest: +SKIP
            {'madrid.xlsx': [2018, 2019], 'seville.xlsx': [2018, 2019]}
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
            lat = config.get('lat')
            lon = config.get('lon')
            elev = config.get('elev')
            tz_hour = config.get('tz_hour')

            print(f"\n=======================================================")
            print(f"Iniciando procesamiento masivo para: {file_path}")
            print(f"Base EPW asignada: {base_epw_path}")
            print(f"=======================================================")

            # Preparar argumentos opcionales a pasar al converter base
            kwargs_for_converter = {
                'file_path': file_path, 'base_epw_path': base_epw_path
            }
            if lat is not None: kwargs_for_converter['lat'] = lat
            if lon is not None: kwargs_for_converter['lon'] = lon
            if elev is not None: kwargs_for_converter['elev'] = elev
            if tz_hour is not None: kwargs_for_converter['tz_hour'] = tz_hour

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

        # --- Session persistence ---
        if save_session and results_summary:
            _inputs = {
                "output_dir": self.output_dir,
                "n_cities": str(len(self.cities_config)),
                "cities_hash": str(hash(str(self.cities_config)))[:12],
            }
            _dir = session_dir or self.output_dir or os.getcwd()
            try:
                save_object_session(self, "BatchHourlyEPWConverter", _inputs, session_dir=_dir)
            except Exception as _e:
                print(f"[SESSION] No se pudo guardar la sesión: {_e}")

        return results_summary
