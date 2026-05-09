# -*- coding: utf-8 -*-
"""
Degree Hours Calculator
Calculates heating and cooling degree hours from EPW files
using setpoint temperatures from IDF files or custom dictionaries.

Author: Daniel Sánchez-García
"""

import datetime
import os
import re
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    from ladybug.epw import EPW
except ImportError:
    raise ImportError("La librería 'ladybug-core' no está instalada.")

try:
    from accim.utils import remove_accents
except ImportError:
    remove_accents = None

try:
    from besos.eppy_funcs import get_building
except ImportError:
    get_building = None


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Maps lowercase EnergyPlus day-type tokens → Python weekday() values
# Python weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
_EP_DAYTYPE_WEEKDAYS: Dict[str, List[int]] = {
    'sunday':    [6],
    'monday':    [0],
    'tuesday':   [1],
    'wednesday': [2],
    'thursday':  [3],
    'friday':    [4],
    'saturday':  [5],
    'weekdays':  [0, 1, 2, 3, 4],
    'weekends':  [5, 6],
    'alldays':   [0, 1, 2, 3, 4, 5, 6],
}

# SCHEDULE:WEEK:DAILY field index for each Python weekday()
# Fields after Name: [Sun, Mon, Tue, Wed, Thu, Fri, Sat, Holiday, SDD, WDD]
_WEEKDAILY_FIELD: Dict[int, int] = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _until_to_hour(time_str: str) -> int:
    """'HH:MM' → exclusive upper-bound hour index (0-24)."""
    return int(time_str.strip().split(':')[0])


def _build_24h_profile(pairs: List[Tuple[int, float]]) -> np.ndarray:
    """Convert [(exclusive_upper_hour, value)] pairs to a 24-element array."""
    profile = np.full(24, np.nan)
    prev = 0
    for until_h, val in sorted(pairs, key=lambda x: x[0]):
        profile[prev:until_h] = val
        prev = until_h
    return profile


def _idf_objects(idf, key: str) -> list:
    """
    Case-insensitive idf.idfobjects lookup.
    Accepts both besos Building objects and raw eppy IDF objects.
    """
    # Unwrap besos Building → eppy IDF if needed
    idf_inner = getattr(idf, 'idf', idf)
    for k in (key, key.upper(), key.lower()):
        objs = idf_inner.idfobjects.get(k, [])
        if objs:
            return list(objs)
    return []


# ---------------------------------------------------------------------------
# DegreeHoursCalculator
# ---------------------------------------------------------------------------

class DegreeHoursCalculator:
    """
    Calculates heating and cooling degree hours from EPW weather data
    using setpoint temperatures from IDF files or custom dictionaries.

    Attributes
    ----------
    temperatures : pd.Series
        Hourly dry-bulb temperatures from the EPW.
    year : int
        Reference year assigned to the EPW data.
    result_hourly : pd.DataFrame or None
        Hourly degree-hours after calling calculate().
    result_daily : pd.DataFrame or None
        Daily totals after calling calculate().
    result_monthly : pd.DataFrame or None
        Monthly totals after calling calculate().
    """

    def __init__(self, epw_path: str, year: Optional[int] = None):
        """
        Parameters
        ----------
        epw_path : str
            Path to the EPW weather file.
        year : int, optional
            Override the year to assign to the EPW data index.
        """
        if not os.path.exists(epw_path):
            raise FileNotFoundError(f"EPW file not found: {epw_path}")

        self.epw_path = epw_path
        self._epw = EPW(epw_path)

        epw_year = getattr(self._epw, 'year', None) or 2000
        self.year: int = int(year) if year is not None else epw_year

        self.temperatures: pd.Series = pd.Series(
            self._epw.dry_bulb_temperature.values,
            index=pd.date_range(
                start=f'{self.year}-01-01',
                periods=len(self._epw.dry_bulb_temperature.values),
                freq='h',
            ),
        )

        self.result_hourly:  Optional[pd.DataFrame] = None
        self.result_daily:   Optional[pd.DataFrame] = None
        self.result_monthly: Optional[pd.DataFrame] = None
        self.result_yearly:  Optional[pd.DataFrame] = None

        # Hourly DataFrame with all available EPW climate variables
        self.epw_data: pd.DataFrame = self._build_epw_dataframe()

    # =========================================================================
    # EPW data helpers
    # =========================================================================

    # Ladybug EPW attribute names to expose in epw_data
    _EPW_ATTRS: List[str] = [
        'dry_bulb_temperature',
        'dew_point_temperature',
        'relative_humidity',
        'atmospheric_pressure',
        'global_horizontal_radiation',
        'direct_normal_radiation',
        'diffuse_horizontal_radiation',
        'global_horizontal_illuminance',
        'direct_normal_illuminance',
        'diffuse_horizontal_illuminance',
        'zenith_luminance',
        'wind_direction',
        'wind_speed',
        'total_sky_cover',
        'opaque_sky_cover',
        'visibility',
        'ceiling_height',
        'horizontal_infrared_radiation_intensity',
        'precipitable_water',
        'aerosol_optical_depth',
        'snow_depth',
        'liquid_precipitation_depth',
    ]

    def _build_epw_dataframe(self) -> pd.DataFrame:
        """
        Build a DataFrame with all available EPW hourly variables.

        Returns
        -------
        pd.DataFrame
            Hourly DataFrame indexed by the same DatetimeIndex as
            ``self.temperatures``. Columns are ladybug EPW attribute names
            (e.g. ``'global_horizontal_radiation'``). Only attributes that
            exist on the EPW object *and* have the expected length are included.
        """
        data: Dict[str, list] = {}
        n = len(self.temperatures)
        for attr in self._EPW_ATTRS:
            obj = getattr(self._epw, attr, None)
            if obj is None:
                continue
            try:
                vals = list(obj.values)
                if len(vals) == n:
                    data[attr] = vals
            except Exception:
                pass
        return pd.DataFrame(data, index=self.temperatures.index)

    # =========================================================================
    # IDF loading
    # =========================================================================

    def _load_idf(self, idf_path: str):
        """Load IDF. Returns a besos Building (preferred) or eppy IDF as fallback."""
        if remove_accents is not None:
            remove_accents(idf_path)

        if get_building is not None:
            try:
                return get_building(idf_path)
            except Exception as e:
                print(f"[WARNING] besos.get_building falló: {e}. Probando eppy...")

        try:
            from eppy.modeleditor import IDF as EppyIDF
            return EppyIDF(idf_path)
        except Exception as e:
            raise RuntimeError(f"No se pudo cargar el IDF con besos ni eppy: {e}")

    # =========================================================================
    # SCHEDULE:COMPACT parser
    # =========================================================================

    def _parse_compact(self, idf, name: str) -> Optional[pd.Series]:
        """Parse a SCHEDULE:COMPACT to an hourly pd.Series. Returns None if not found."""
        target = next(
            (o for o in _idf_objects(idf, 'SCHEDULE:COMPACT')
             if o.Name.strip().lower() == name.strip().lower()),
            None,
        )
        if target is None:
            return None

        # Skip field 0 (Name) and field 1 (Schedule Type Limits)
        tokens = [f.strip() for f in target.fieldvalues if str(f).strip()][2:]

        # State variables for the flat token scanner
        ranges: List[Tuple[int, int, Dict]] = []             # collected date-range blocks
        end_month = end_day = 12                              # default end of year
        day_profiles: Dict[str, List[Tuple[int, float]]] = {}  # Until/value pairs per day-type
        active_types: List[str] = []                          # day-type tokens currently active
        i = 0

        while i < len(tokens):
            t = tokens[i]
            tl = t.lower()

            if tl.startswith('through:'):
                # Save the just-finished date-range block before starting the next one
                if day_profiles:
                    ranges.append((end_month, end_day, day_profiles))
                # Parse 'Through: MM/DD'
                m_str, d_str = t[8:].strip().split('/')
                end_month, end_day = int(m_str), int(d_str)
                day_profiles = {}   # reset for the new range
                active_types = []

            elif tl.startswith('for:'):
                # 'For: Weekdays', 'For: AllDays', etc. (may list multiple tokens)
                active_types = t[4:].strip().lower().split()
                for dt in active_types:
                    if dt not in day_profiles:
                        day_profiles[dt] = []

            elif tl.startswith('until:'):
                # 'Until: HH:MM' is always followed by its numeric value on the next token
                time_str = t[6:].strip()
                if i + 1 < len(tokens):
                    try:
                        val = float(tokens[i + 1])
                        uh = _until_to_hour(time_str)   # exclusive upper-bound hour index
                        for dt in active_types:
                            day_profiles[dt].append((uh, val))
                        i += 1   # consume the value token
                    except ValueError:
                        pass
            i += 1

        # Flush the last range block
        if day_profiles:
            ranges.append((end_month, end_day, day_profiles))

        return self._compact_ranges_to_series(ranges)

    def _compact_ranges_to_series(
        self, ranges: List[Tuple[int, int, Dict]]
    ) -> pd.Series:
        """Build an 8760-h pd.Series from parsed SCHEDULE:COMPACT date-range blocks."""
        idx    = self.temperatures.index
        values = np.full(len(idx), np.nan)

        # 'prev_end' tracks the inclusive start date of each block
        prev_end = datetime.date(self.year, 1, 1)
        for (em, ed, raw_profiles) in ranges:
            end_date = datetime.date(self.year, em, ed)

            # Convert raw (until_hour, value) pairs to 24-element numpy arrays
            profiles: Dict[str, np.ndarray] = {
                dt: _build_24h_profile(pairs)
                for dt, pairs in raw_profiles.items()
                if pairs
            }
            alldays_prof  = profiles.get('alldays')     # applies to every day
            allother_prof = profiles.get('allotherdays') # catch-all fallback

            for pos, ts in enumerate(idx):
                d  = ts.date()
                if not (prev_end <= d <= end_date):
                    continue
                h  = ts.hour
                wd = ts.weekday()   # 0=Monday … 6=Sunday

                # 'AllDays' overrides all other day-type rules
                if alldays_prof is not None:
                    values[pos] = alldays_prof[h]
                    continue

                # Find the first explicit day-type rule that matches this weekday
                profile = None
                for dt, prof in profiles.items():
                    if dt in ('alldays', 'allotherdays'):
                        continue
                    wd_list = _EP_DAYTYPE_WEEKDAYS.get(dt)
                    if wd_list is not None and wd in wd_list:
                        profile = prof
                        break   # first match wins

                # Fall back to 'AllOtherDays' when no explicit rule matched
                if profile is None and allother_prof is not None:
                    profile = allother_prof

                if profile is not None:
                    values[pos] = profile[h]

            # Advance the start boundary past the current range
            prev_end = end_date + datetime.timedelta(days=1)

        return pd.Series(values, index=idx)

    # =========================================================================
    # SCHEDULE:DAY:HOURLY / DAY:INTERVAL parsers
    # =========================================================================

    def _parse_day_schedule(self, idf, name: str) -> Optional[np.ndarray]:
        """
        Return a 24-element hourly array from a SCHEDULE:DAY object.

        Supports both ``SCHEDULE:DAY:HOURLY`` (24 explicit values) and
        ``SCHEDULE:DAY:INTERVAL`` (``Until:``/value pairs).
        Returns ``None`` if no matching object is found.
        """
        nl = name.strip().lower()

        # --- SCHEDULE:DAY:HOURLY: fields 2-25 are the 24 hourly values ------
        for obj in _idf_objects(idf, 'SCHEDULE:DAY:HOURLY'):
            if obj.Name.strip().lower() == nl:
                vals = []
                for v in obj.fieldvalues[2:]:   # skip Name and TypeLimits
                    s = str(v).strip()
                    if s:
                        try:
                            vals.append(float(s))
                        except ValueError:
                            pass
                    if len(vals) == 24:
                        break
                if len(vals) == 24:
                    return np.array(vals)

        # --- SCHEDULE:DAY:INTERVAL: Until/value pairs (field 3+) ------------
        # Field 0: Name, Field 1: TypeLimits, Field 2: Interpolate to Timestep
        for obj in _idf_objects(idf, 'SCHEDULE:DAY:INTERVAL'):
            if obj.Name.strip().lower() == nl:
                fields = [str(f).strip() for f in obj.fieldvalues[3:] if str(f).strip()]
                pairs: List[Tuple[int, float]] = []
                j = 0
                while j < len(fields) - 1:
                    try:
                        uh  = _until_to_hour(fields[j])   # e.g. '07:00' -> 7
                        val = float(fields[j + 1])
                        pairs.append((uh, val))
                        j += 2   # each pair occupies two fields
                    except (ValueError, IndexError):
                        j += 1
                if pairs:
                    return _build_24h_profile(pairs)

        return None

    # =========================================================================
    # SCHEDULE:YEAR / WEEK:DAILY parser
    # =========================================================================

    def _parse_year_schedule(self, idf, name: str) -> Optional[pd.Series]:
        """
        Parse a ``SCHEDULE:YEAR`` object to an 8760-h pd.Series.

        Resolves the chain:
        ``SCHEDULE:YEAR`` → ``SCHEDULE:WEEK:DAILY`` → ``SCHEDULE:DAY:*``.
        Returns ``None`` if no matching ``SCHEDULE:YEAR`` object is found.
        """
        target = next(
            (o for o in _idf_objects(idf, 'SCHEDULE:YEAR')
             if o.Name.strip().lower() == name.strip().lower()),
            None,
        )
        if target is None:
            return None

        # Fields after Name (0) and TypeLimits (1) are groups of 5:
        # [WeekScheduleName, StartMonth, StartDay, EndMonth, EndDay, ...]
        fv = [str(f).strip() for f in target.fieldvalues[2:] if str(f).strip()]
        idx    = self.temperatures.index
        values = np.full(len(idx), np.nan)

        i = 0
        while i + 4 < len(fv):
            week_name = fv[i]
            try:
                sm, sd, em, ed = int(fv[i+1]), int(fv[i+2]), int(fv[i+3]), int(fv[i+4])
            except ValueError:
                i += 5
                continue

            start_d = datetime.date(self.year, sm, sd)
            end_d   = datetime.date(self.year, em, ed)

            # Resolve the week schedule object
            week_obj = next(
                (o for o in _idf_objects(idf, 'SCHEDULE:WEEK:DAILY')
                 if o.Name.strip().lower() == week_name.strip().lower()),
                None,
            )
            if week_obj is None:
                i += 5
                continue

            # SCHEDULE:WEEK:DAILY field order (after Name):
            # [Sun, Mon, Tue, Wed, Thu, Fri, Sat, Holiday, SummerDD, WinterDD]
            week_fv = [str(f).strip() for f in week_obj.fieldvalues]

            for pos, ts in enumerate(idx):
                if not (start_d <= ts.date() <= end_d):
                    continue
                # Map Python weekday() to the corresponding day-schedule field index
                fi = _WEEKDAILY_FIELD.get(ts.weekday(), 1)  # default to Sunday (1) if unknown
                if fi < len(week_fv):
                    profile = self._parse_day_schedule(idf, week_fv[fi])
                    if profile is not None:
                        values[pos] = profile[ts.hour]

            i += 5   # advance to the next group of 5

        return pd.Series(values, index=idx)

    # =========================================================================
    # Unified schedule resolver
    # =========================================================================

    def _schedule_to_series(self, idf, name: str) -> pd.Series:
        """Resolve any supported schedule type to an 8760-h pd.Series."""
        series = self._parse_compact(idf, name)
        if series is not None:
            return series
        series = self._parse_year_schedule(idf, name)
        if series is not None:
            return series
        raise ValueError(
            f"No se pudo parsear el schedule '{name}'. "
            "Solo se soportan SCHEDULE:COMPACT y SCHEDULE:YEAR actualmente."
        )

    # =========================================================================
    # IDF setpoint extraction (public)
    # =========================================================================

    def _get_available_names(self, idf) -> Dict[str, List[str]]:
        """Return all Zone and Space names found in the IDF."""
        return {
            'zones':  [o.Name for o in _idf_objects(idf, 'ZONE')],
            'spaces': [o.Name for o in _idf_objects(idf, 'SPACE')],
        }

    def _extract_availability_from_idf(
        self,
        idf,
        zone_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, pd.Series]]:
        """
        Extract heating and cooling availability schedules from
        ``ZoneHVAC:IdealLoadsAirSystem`` objects.

        Resolves the chain:
        ``ZoneHVAC:EquipmentConnections`` → ``ZoneHVAC:EquipmentList``
        → ``ZoneHVAC:IdealLoadsAirSystem`` → availability schedule.

        Returns
        -------
        dict
            ``{zone_name: {'heating': pd.Series(0/1), 'cooling': pd.Series(0/1)}}``,
            where ``1`` = system available and ``0`` = system off (DH not counted).
            Zones without an IdealLoads system default to always-available (all 1).
        """
        idx     = self.temperatures.index
        default = pd.Series(1.0, index=idx)  # assume always available by default

        # Step 1: zone name → equipment list name
        zone_to_equip: Dict[str, str] = {}
        for conn in _idf_objects(idf, 'ZONEHVAC:EQUIPMENTCONNECTIONS'):
            z  = str(getattr(conn, 'Zone_Name', '')).strip()
            el = str(getattr(conn, 'Zone_Conditioning_Equipment_List_Name', '')).strip()
            if z and el:
                zone_to_equip[z] = el

        # Step 2: equipment list name → list of IdealLoads system names
        equip_to_ideal: Dict[str, List[str]] = {}
        for el_obj in _idf_objects(idf, 'ZONEHVAC:EQUIPMENTLIST'):
            el_name = str(getattr(el_obj, 'Name', '')).strip()
            ideal_names: List[str] = []
            fv = [str(f).strip() for f in el_obj.fieldvalues]
            for i, v in enumerate(fv):
                if 'idealloads' in v.lower() and i + 1 < len(fv):
                    ideal_names.append(fv[i + 1])
            equip_to_ideal[el_name] = ideal_names

        # Step 3: IdealLoads name → (heating_avail_sch, cooling_avail_sch)
        ideal_to_avail: Dict[str, Tuple[str, str]] = {}
        for il in _idf_objects(idf, 'ZONEHVAC:IDEALLOADSAIRSYSTEM'):
            name = str(getattr(il, 'Name', '')).strip()
            h_a  = str(getattr(il, 'Heating_Availability_Schedule_Name', '')).strip()
            c_a  = str(getattr(il, 'Cooling_Availability_Schedule_Name', '')).strip()
            ideal_to_avail[name] = (h_a, c_a)

        # Step 4: assemble per zone
        result: Dict[str, Dict[str, pd.Series]] = {}
        for zone, equip_list in zone_to_equip.items():
            if zone_name is not None and zone.lower() != zone_name.lower():
                continue

            h_avail = default.copy()
            c_avail = default.copy()

            for il_name in equip_to_ideal.get(equip_list, []):
                h_sch, c_sch = next(
                    (v for k, v in ideal_to_avail.items()
                     if k.lower() == il_name.lower()),
                    ('', '')
                )
                if h_sch:
                    try:
                        s = self._schedule_to_series(idf, h_sch)
                        h_avail = h_avail * (s > 0).astype(float)
                        print(f"[INFO] '{zone}' → heating availability: '{h_sch}'")
                    except Exception as e:
                        print(f"[WARNING] No se pudo parsear heating availability '{h_sch}': {e}")
                if c_sch:
                    try:
                        s = self._schedule_to_series(idf, c_sch)
                        c_avail = c_avail * (s > 0).astype(float)
                        print(f"[INFO] '{zone}' → cooling availability: '{c_sch}'")
                    except Exception as e:
                        print(f"[WARNING] No se pudo parsear cooling availability '{c_sch}': {e}")

            result[zone] = {'heating': h_avail, 'cooling': c_avail}

        if not result:
            print("[INFO] No se encontraron sistemas IdealLoads. Disponibilidad = 100%.")

        return result

    def extract_setpoints_from_idf(
        self,
        idf_path: str,
        zone_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, pd.Series]]:
        """
        Extract heating and cooling setpoints from an IDF as hourly series.
        Also extracts ``ZoneHVAC:IdealLoadsAirSystem`` availability schedules
        and stores them under ``'heating_avail'`` / ``'cooling_avail'`` keys.

        Parameters
        ----------
        idf_path : str
            Path to the IDF file.
        zone_name : str, optional
            Zone or Space name to extract. If None, all zones with thermostats
            are returned. If specified but not found, raises a ``ValueError``
            with the list of available names.

        Returns
        -------
        dict
            ``{zone_name: {'heating': Series, 'cooling': Series,
                           'heating_avail': Series, 'cooling_avail': Series}}``
        """
        if not os.path.exists(idf_path):
            raise FileNotFoundError(f"IDF file not found: {idf_path}")

        print(f"[INFO] Cargando IDF: {idf_path}")
        # idf = self._load_idf(idf_path)
        idf = get_building(idf_path)
        avail = self._get_available_names(idf)
        all_names = avail['zones'] + avail['spaces']

        if zone_name is not None and zone_name not in all_names:
            raise ValueError(
                f"Zone/Space '{zone_name}' no encontrado en el IDF.\n"
                f"  Zones:  {avail['zones']}\n"
                f"  Spaces: {avail['spaces']}"
            )

        # Index dual setpoint objects by name
        dual_by_name: Dict[str, object] = {}
        for key in ('THERMOSTATSETPOINT:DUALSETPOINT', 'THERMOSTATSETPOINTDUALSETPOINT'):
            for obj in _idf_objects(idf, key):
                dual_by_name[obj.Name.strip().lower()] = obj

        result: Dict[str, Dict[str, pd.Series]] = {}

        for tstat in _idf_objects(idf, 'ZONECONTROL:THERMOSTAT'):
            # Retrieve zone name (field name varies across E+ versions)
            t_zone = None
            for attr in (
                'Zone_or_ZoneList_Name',
                'Zone_or_ZoneList_or_Space_or_SpaceList_Name',
            ):
                val = getattr(tstat, attr, None)
                if val:
                    t_zone = str(val).strip()
                    break
            if t_zone is None:
                continue
            if zone_name is not None and t_zone != zone_name:
                continue

            # Find associated DualSetpoint object
            dual_obj = None
            for attr in ('Control_Name_1', 'Control_Name', 'Control_Name_2'):
                ctrl = str(getattr(tstat, attr, '')).strip().lower()
                if ctrl in dual_by_name:
                    dual_obj = dual_by_name[ctrl]
                    break
            if dual_obj is None and dual_by_name:
                dual_obj = next(iter(dual_by_name.values()))
            if dual_obj is None:
                print(f"[WARNING] No se encontró consigna dual para zona '{t_zone}'")
                continue

            h_sch = str(dual_obj.Heating_Setpoint_Temperature_Schedule_Name).strip()
            c_sch = str(dual_obj.Cooling_Setpoint_Temperature_Schedule_Name).strip()
            print(
                f"[INFO] '{t_zone}' → heating: '{h_sch}',  cooling: '{c_sch}'"
            )

            result[t_zone] = {
                'heating': self._schedule_to_series(idf, h_sch),
                'cooling': self._schedule_to_series(idf, c_sch),
            }

        if not result:
            raise ValueError(
                "No se encontraron consignas en el IDF.\n"
                f"Zones disponibles: {avail['zones']}"
            )

        print(f"[SUCCESS] Consignas extraídas para {len(result)} zona(s).")

        # --- Availability schedules (ZoneHVAC:IdealLoadsAirSystem) ----------
        avail_dict = self._extract_availability_from_idf(idf, zone_name)
        for zone, sp in result.items():
            av = avail_dict.get(zone, {})
            sp['heating_avail'] = av.get('heating', pd.Series(1.0, index=self.temperatures.index))
            sp['cooling_avail'] = av.get('cooling', pd.Series(1.0, index=self.temperatures.index))

        return result

    # =========================================================================
    # Custom dictionary setpoints (new API)
    # =========================================================================

    def _setpoints_from_dict(
        self, config: Dict
    ) -> Tuple[pd.Series, pd.Series]:
        """
        Build (heating_series, cooling_series) from a configuration dict.

        Supported ``type`` values
        -------------------------
        ``'constant'``
            Keys: ``heating`` (float), ``cooling`` (float).

        ``'daily'``
            Keys: ``heating`` (list of 365/366 values), ``cooling`` (list).

        ``'weekly'``
            Keys:
            - ``periods``: ``{name: ('MM-DD', 'MM-DD')}``
            - ``patterns``: ``{period: {day_key: {'heating': val, 'cooling': val}}}``
            where ``day_key`` ∈ ``{'weekday', 'weekend', 'monday', ..., 'alldays'}``.

        ``'hourly_weekly'``
            Like ``'weekly'`` but pattern values are lists of 24 hourly floats.
        """
        tipo = config.get('type', config.get('tipo', '')).lower()
        idx  = self.temperatures.index

        if tipo == 'constant':
            h = float(config.get('heating', 21.0))
            c = float(config.get('cooling', 26.0))
            return pd.Series(h, index=idx), pd.Series(c, index=idx)

        if tipo == 'daily':
            n_days = len(idx) // 24
            h_vals = list(config.get('heating', []))
            c_vals = list(config.get('cooling', []))
            for label, vals in (('heating', h_vals), ('cooling', c_vals)):
                if len(vals) != n_days:
                    raise ValueError(
                        f"'daily' → '{label}': se esperan {n_days} valores, "
                        f"se proporcionaron {len(vals)}."
                    )
            return (
                pd.Series(np.repeat(h_vals, 24), index=idx),
                pd.Series(np.repeat(c_vals, 24), index=idx),
            )

        if tipo in ('weekly', 'hourly_weekly'):
            periods  = config.get('periods', {})
            patterns = config.get('patterns', {})
            h_arr = np.full(len(idx), np.nan)
            c_arr = np.full(len(idx), np.nan)

            for period_name, (start_str, end_str) in periods.items():
                pat = patterns.get(period_name, {})
                try:
                    start_d = pd.Timestamp(f'{self.year}-{start_str}').date()
                    end_d   = pd.Timestamp(f'{self.year}-{end_str}').date()
                except Exception:
                    start_d = pd.Timestamp(start_str).replace(year=self.year).date()
                    end_d   = pd.Timestamp(end_str).replace(year=self.year).date()

                for pos, ts in enumerate(idx):
                    if not (start_d <= ts.date() <= end_d):
                        continue
                    is_weekend = ts.weekday() >= 5
                    h_of_day   = ts.hour

                    day_key = None
                    for dk in (
                        ts.day_name().lower(),
                        'weekend' if is_weekend else 'weekday',
                        'alldays',
                    ):
                        if dk in pat:
                            day_key = dk
                            break
                    if day_key is None:
                        continue

                    day_pat = pat[day_key]
                    h_raw = day_pat.get('heating')
                    c_raw = day_pat.get('cooling')

                    if tipo == 'hourly_weekly':
                        if h_raw is not None:
                            h_arr[pos] = float(h_raw[h_of_day])
                        if c_raw is not None:
                            c_arr[pos] = float(c_raw[h_of_day])
                    else:
                        if h_raw is not None:
                            h_arr[pos] = float(h_raw)
                        if c_raw is not None:
                            c_arr[pos] = float(c_raw)

            return pd.Series(h_arr, index=idx), pd.Series(c_arr, index=idx)

        raise ValueError(
            f"Tipo de configuración desconocido: '{tipo}'. "
            "Valores válidos: 'constant', 'daily', 'weekly', 'hourly_weekly'."
        )

    # =========================================================================
    # Core degree-hours computation
    # =========================================================================

    def _compute_dh(
        self,
        h_sp: pd.Series,
        c_sp: pd.Series,
        hours: Optional[List[int]],
        mode: str,
    ) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
        """
        Compute hourly heating and/or cooling degree-hours.

        Parameters
        ----------
        h_sp, c_sp : pd.Series
            Heating / cooling setpoint series (same index as temperatures).
        hours : list of int or None
            Hours of day to include (0-23). None = all 24 h.
        mode : str
            'heating', 'cooling', or 'both'.

        Returns
        -------
        (heating_dh, cooling_dh) — None for the component not requested.
        """
        temps = self.temperatures
        if hours is None:
            hours = list(range(24))

        hour_mask = temps.index.hour.isin(hours)

        h_sp = h_sp.reindex(temps.index, method='ffill')
        c_sp = c_sp.reindex(temps.index, method='ffill')

        hdh = cdh = None

        if mode in ('heating', 'both'):
            hdh = pd.Series(0.0, index=temps.index)
            hdh[hour_mask] = np.maximum(0.0, h_sp[hour_mask] - temps[hour_mask])

        if mode in ('cooling', 'both'):
            cdh = pd.Series(0.0, index=temps.index)
            cdh[hour_mask] = np.maximum(0.0, temps[hour_mask] - c_sp[hour_mask])

        return hdh, cdh

    @staticmethod
    def _aggregate(s: pd.Series, freq: str) -> pd.Series:
        """Aggregate a Series to daily ('D') or monthly ('ME') totals."""
        return s.resample(freq).sum()

    def _build_result_df(
        self,
        hdh: Optional[pd.Series],
        cdh: Optional[pd.Series],
        mode: str,
        agg_freq: Optional[str] = None,
    ) -> pd.DataFrame:
        """Build a result DataFrame, optionally aggregated."""
        if agg_freq:
            if hdh is not None:
                hdh = self._aggregate(hdh, agg_freq)
            if cdh is not None:
                cdh = self._aggregate(cdh, agg_freq)

        if mode == 'both':
            return pd.DataFrame({'heating_dh': hdh, 'cooling_dh': cdh})
        if mode == 'heating':
            return pd.DataFrame({'heating_dh': hdh})
        return pd.DataFrame({'cooling_dh': cdh})

    # =========================================================================
    # Public: calculate
    # =========================================================================

    def calculate(
        self,
        setpoint_source: Union[str, Dict],
        frequency: Union[str, List[str]] = None,
        hours: Optional[List[int]] = None,
        mode: str = 'both',
        zone_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Calculate degree hours from the EPW loaded in the constructor.

        Parameters
        ----------
        setpoint_source : str or dict
            - **str**: path to an IDF file.
            - **dict**: custom configuration (see ``_setpoints_from_dict``).
        frequency : str or list of str, optional
            Which aggregation levels to compute. Any combination of
            ``'hourly'``, ``'daily'``, ``'monthly'``.
            Default: all three.
        hours : list of int, optional
            Hours of the day to include [0-23]. Default: all 24.
        mode : str
            ``'heating'``, ``'cooling'``, or ``'both'`` (default).
        zone_name : str, optional
            Zone/Space name from IDF. If None (default), all zones are
            processed and the **mean setpoint** across zones is used.
            If specified and not found, a ``ValueError`` is raised listing
            available names.
        start_date : str, optional
            Start date in ``'DD/MM'`` format. Data outside the period is set to 0.
        end_date : str, optional
            End date in ``'DD/MM'`` format.

        Returns
        -------
        dict
            Keys present depend on *frequency*:
            ``{'hourly': df, 'daily': df, 'monthly': df}``.
            Results are also stored in ``self.result_hourly``,
            ``self.result_daily``, ``self.result_monthly``.
        """
        if frequency is None:
            frequency = ['hourly', 'daily', 'monthly']
        if isinstance(frequency, str):
            frequency = [frequency]

        valid_freqs = {'hourly', 'daily', 'monthly', 'yearly'}
        bad = set(frequency) - valid_freqs
        if bad:
            raise ValueError(f"Frecuencias no válidas: {bad}. Usa: {valid_freqs}")

        if mode not in ('heating', 'cooling', 'both'):
            raise ValueError("mode debe ser 'heating', 'cooling' o 'both'.")

        # ------------------------------------------------------------------
        # Resolve setpoints
        # ------------------------------------------------------------------
        if isinstance(setpoint_source, str):
            sp_dict = self.extract_setpoints_from_idf(setpoint_source, zone_name)

            if zone_name is not None:
                # Single zone
                h_sp = sp_dict[zone_name]['heating']
                c_sp = sp_dict[zone_name]['cooling']
            else:
                # Average across all zones
                h_sp = pd.concat(
                    [v['heating'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                c_sp = pd.concat(
                    [v['cooling'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                print(f"[INFO] Consigna promediada sobre {len(sp_dict)} zona(s).")

        elif isinstance(setpoint_source, dict):
            h_sp, c_sp = self._setpoints_from_dict(setpoint_source)
        else:
            raise TypeError(
                "setpoint_source debe ser una ruta a IDF (str) o un dict de configuración."
            )

        # ------------------------------------------------------------------
        # Availability masks (only when source is IDF)
        # ------------------------------------------------------------------
        h_avail = c_avail = None
        if isinstance(setpoint_source, str):
            if zone_name is not None:
                h_avail = sp_dict[zone_name].get('heating_avail')
                c_avail = sp_dict[zone_name].get('cooling_avail')
            else:
                # AND-logic across zones: system must be active in ALL zones
                # (simplification: use mean — >0.5 treated as active)
                h_arr = pd.concat(
                    [v['heating_avail'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                c_arr = pd.concat(
                    [v['cooling_avail'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                h_avail = (h_arr > 0).astype(float)
                c_avail = (c_arr > 0).astype(float)

        # ------------------------------------------------------------------
        # Compute hourly degree-hours
        # ------------------------------------------------------------------
        print(f"[INFO] Calculando grados-hora (mode='{mode}', horas={hours or 'todas'})…")
        hdh, cdh = self._compute_dh(h_sp, c_sp, hours, mode)

        # Apply availability masks: zero out DH when system is inactive
        if hdh is not None and h_avail is not None:
            h_avail_r = h_avail.reindex(hdh.index, fill_value=1.0)
            hdh = hdh * h_avail_r
        if cdh is not None and c_avail is not None:
            c_avail_r = c_avail.reindex(cdh.index, fill_value=1.0)
            cdh = cdh * c_avail_r

        # Apply date period filter if specified
        if start_date or end_date:
            idx = self.temperatures.index
            sd_str = start_date or "01/01"
            ed_str = end_date or "31/12"
            try:
                sd = pd.to_datetime(f"{self.year}/{sd_str}", format="%Y/%d/%m")
                ed = pd.to_datetime(f"{self.year}/{ed_str}", format="%Y/%d/%m") + pd.Timedelta(days=1, microseconds=-1)
            except Exception as e:
                raise ValueError(f"Formato de fecha inválido. Usa 'DD/MM': {e}")
            
            if sd <= ed:
                mask = (idx >= sd) & (idx <= ed)
            else:
                mask = (idx >= sd) | (idx <= ed)
                
            if hdh is not None:
                hdh.loc[~mask] = 0.0
            if cdh is not None:
                cdh.loc[~mask] = 0.0

        # ------------------------------------------------------------------
        # Aggregate and store
        # ------------------------------------------------------------------
        results: Dict[str, pd.DataFrame] = {}

        if 'hourly' in frequency:
            self.result_hourly = self._build_result_df(hdh, cdh, mode)
            results['hourly'] = self.result_hourly

        if 'daily' in frequency:
            self.result_daily = self._build_result_df(hdh, cdh, mode, agg_freq='D')
            results['daily'] = self.result_daily

        if 'monthly' in frequency:
            self.result_monthly = self._build_result_df(hdh, cdh, mode, agg_freq='ME')
            results['monthly'] = self.result_monthly

        if 'yearly' in frequency:
            self.result_yearly = self._build_result_df(hdh, cdh, mode, agg_freq='YE')
            results['yearly'] = self.result_yearly

        print("[INFO] Cálculo completado.")
        for freq_key, df in results.items():
            print(f"  {freq_key}: {df.shape} → {df.sum().to_dict()}")

        return results

    # =========================================================================
    # Public: plot
    # =========================================================================

    def plot(
        self,
        setpoint_source: Union[str, Dict],
        period: str = 'year',
        period_value: Optional[Union[int, str, List]] = None,
        zone_name: Optional[str] = None,
        show_heating: bool = True,
        show_cooling: bool = True,
        show_air_temp: bool = False,
    ) -> None:
        """
        Visualize setpoint temperatures extracted from *setpoint_source*
        and, optionally, the EPW dry-bulb air temperature.

        Parameters
        ----------
        setpoint_source : str or dict
            IDF path or custom configuration dict.
        period : str
            Temporal resolution for the plot:

            - ``'year'``  — full year, daily mean with min/max band.
            - ``'month'`` — one or more months at hourly resolution.
            - ``'week'``  — one or more ISO weeks at hourly resolution.
            - ``'day'``   — one or more specific days at hourly resolution.

        period_value : int, str, or list, optional
            - ``'month'``: month number(s) 1-12.
            - ``'week'``:  ISO week number(s).
            - ``'day'``:   date string(s) ``'YYYY-MM-DD'`` or ``'MM-DD'``.
            - ``'year'``:  ignored.
        zone_name : str, optional
            Zone/Space to show. If None and source is IDF, the mean of all
            zones is shown.
        show_heating : bool
            Whether to plot the heating setpoint series (default True).
        show_cooling : bool
            Whether to plot the cooling setpoint series (default True).
        show_air_temp : bool
            Whether to overlay the EPW dry-bulb air temperature
            (default False).
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            raise ImportError("matplotlib es necesario para visualización.")

        if period not in ('year', 'month', 'week', 'day'):
            raise ValueError("period debe ser 'year', 'month', 'week' o 'day'.")

        # --- Resolve setpoint series ----------------------------------------
        if isinstance(setpoint_source, str):
            sp_dict = self.extract_setpoints_from_idf(setpoint_source, zone_name)
            if zone_name is not None:
                h_sp     = sp_dict[zone_name]['heating'].copy()
                c_sp     = sp_dict[zone_name]['cooling'].copy()
                h_avail  = sp_dict[zone_name]['heating_avail']
                c_avail  = sp_dict[zone_name]['cooling_avail']
                title_suffix = f" — Zona: {zone_name}"
            else:
                h_sp = pd.concat(
                    [v['heating'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                c_sp = pd.concat(
                    [v['cooling'] for v in sp_dict.values()], axis=1
                ).mean(axis=1)
                h_avail = (pd.concat(
                    [v['heating_avail'] for v in sp_dict.values()], axis=1
                ).mean(axis=1) > 0).astype(float)
                c_avail = (pd.concat(
                    [v['cooling_avail'] for v in sp_dict.values()], axis=1
                ).mean(axis=1) > 0).astype(float)
                title_suffix = f" — Media de {len(sp_dict)} zona(s)"

            # Apply availability: where system is off → NaN (gap in plot)
            h_sp[h_avail < 1] = np.nan
            c_sp[c_avail < 1] = np.nan

        elif isinstance(setpoint_source, dict):
            h_sp, c_sp = self._setpoints_from_dict(setpoint_source)
            title_suffix = " — Diccionario personalizado"
        else:
            raise TypeError("setpoint_source debe ser str o dict.")


        # --- Slice data by period -------------------------------------------
        def _slice(s: pd.Series) -> pd.Series:
            if period == 'year':
                return s

            vals = period_value if isinstance(period_value, list) else [period_value]

            masks = []
            for v in vals:
                if period == 'month':
                    m = int(v)
                    masks.append(s.index.month == m)
                elif period == 'week':
                    w = int(v)
                    masks.append(s.index.isocalendar().week == w)
                elif period == 'day':
                    date_str = str(v)
                    try:
                        d = pd.Timestamp(date_str).date()
                    except Exception:
                        d = pd.Timestamp(f'{self.year}-{date_str}').date()
                    masks.append(pd.Series(s.index.date == d, index=s.index))

            combined = masks[0]
            for m in masks[1:]:
                combined = combined | m
            return s[combined]

        h_plot   = _slice(h_sp) if show_heating else None
        c_plot   = _slice(c_sp) if show_cooling else None
        air_plot = _slice(self.temperatures) if show_air_temp else None

        # --- Build plot -----------------------------------------------------
        fig, ax = plt.subplots(figsize=(14, 5))

        period_labels = {
            'year':  'Año completo — media diaria con banda min/máx',
            'month': f'Mes(es) {period_value} — resolución horaria',
            'week':  f'Semana(s) ISO {period_value} — resolución horaria',
            'day':   f'Día(s) {period_value} — resolución horaria',
        }

        if period == 'year':
            # Daily aggregation with min/max band
            if h_plot is not None:
                daily_h = h_plot.resample('D').agg(['min', 'max', 'mean'])
                ax.fill_between(daily_h.index, daily_h['min'], daily_h['max'],
                                alpha=0.2, color='tab:red', label='Calefacción (min/máx)')
                ax.plot(daily_h.index, daily_h['mean'],
                        color='tab:red', linewidth=1.5, label='Calefacción (media diaria)')
            if c_plot is not None:
                daily_c = c_plot.resample('D').agg(['min', 'max', 'mean'])
                ax.fill_between(daily_c.index, daily_c['min'], daily_c['max'],
                                alpha=0.2, color='tab:blue', label='Refrigeración (min/máx)')
                ax.plot(daily_c.index, daily_c['mean'],
                        color='tab:blue', linewidth=1.5, label='Refrigeración (media diaria)')
            if air_plot is not None:
                daily_a = air_plot.resample('D').agg(['min', 'max', 'mean'])
                ax.fill_between(daily_a.index, daily_a['min'], daily_a['max'],
                                alpha=0.15, color='tab:green', label='T. aire (min/máx)')
                ax.plot(daily_a.index, daily_a['mean'],
                        color='tab:green', linewidth=1.2, linestyle='--',
                        label='T. aire (media diaria)')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
        else:
            if h_plot is not None:
                ax.plot(h_plot.index, h_plot.values,
                        color='tab:red', linewidth=1.2, label='Consigna calefacción')
            if c_plot is not None:
                ax.plot(c_plot.index, c_plot.values,
                        color='tab:blue', linewidth=1.2, label='Consigna refrigeración')
            if air_plot is not None:
                ax.plot(air_plot.index, air_plot.values,
                        color='tab:green', linewidth=0.9, linestyle='--',
                        alpha=0.8, label='T. aire (EPW)')
            if period == 'day':
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
            elif period == 'week':
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d/%m'))
                ax.xaxis.set_major_locator(mdates.DayLocator())
            else:  # month
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))

        ax.set_title(f"Temperaturas — {period_labels[period]}{title_suffix}")
        ax.set_ylabel('Temperatura (°C)')
        ax.set_xlabel('Fecha / Hora')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.show()

    # =========================================================================
    # Public: export_results
    # =========================================================================

    def export_results(self, output_path: str = 'degree_hours_results.xlsx') -> str:
        """
        Export all computed result DataFrames to an Excel file.

        Parameters
        ----------
        output_path : str
            Destination file path. Default: ``'degree_hours_results.xlsx'``.

        Returns
        -------
        str
            Absolute path to the saved file.
        """
        sheets = {
            'hourly':  self.result_hourly,
            'daily':   self.result_daily,
            'monthly': self.result_monthly,
            'yearly':  self.result_yearly,
        }
        available = {k: v for k, v in sheets.items() if v is not None}
        if not available:
            raise ValueError(
                "No hay resultados para exportar. Ejecute calculate() primero."
            )

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for sheet_name, df in available.items():
                df.to_excel(writer, sheet_name=sheet_name)

        abs_path = os.path.abspath(output_path)
        print(f"[INFO] Resultados exportados a: {abs_path}")
        return abs_path


# =============================================================================
# EpwBatchAnalyzer
# =============================================================================

# Variables whose monthly aggregate is a SUM (energy); all others use MEAN
_RADIATION_VARS = frozenset({
    'global_horizontal_radiation',
    'direct_normal_radiation',
    'diffuse_horizontal_radiation',
    'global_horizontal_illuminance',
    'direct_normal_illuminance',
    'diffuse_horizontal_illuminance',
    'zenith_luminance',
    'horizontal_infrared_radiation_intensity',
    'liquid_precipitation_depth',
})


class EpwBatchAnalyzer:
    """
    Run :class:`DegreeHoursCalculator` over multiple EPW files and compile
    a comparative monthly summary table.

    For each EPW the following columns are computed:

    - **Heating / cooling degree-hours (all 24 h)** — ``heating_dh_24h``,
      ``cooling_dh_24h``.
    - **Heating / cooling degree-hours (custom hour range)** — e.g.
      ``heating_dh_0-8h``, ``cooling_dh_0-8h``.
    - **EPW climate variables** (monthly sum for radiation/illuminance,
      monthly mean for the rest) — column name = EPW attribute name.

    Attributes
    ----------
    results : pd.DataFrame or None
        MultiIndex-column DataFrame ``(epw_name, variable)`` with months
        1-12 as index. Populated after calling :meth:`run`.
    calculators : dict
        Maps EPW base name → :class:`DegreeHoursCalculator` instance,
        giving access to hourly data and individual results after :meth:`run`.
    """

    def __init__(
        self,
        epw_paths: List[str],
        setpoint_source: Union[str, Dict],
        epw_variables: Optional[Union[List[str], Dict[str, Union[str, List[str]]]]] = None,
        hours2: Optional[List[int]] = None,
        zone_name: Optional[str] = None,
        mode: str = 'both',
        year: Optional[int] = None,
        frequencies: Optional[Union[str, List[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        epw_paths : list of str
            Paths to the EPW files to analyse.
        setpoint_source : str or dict
            IDF file path or custom setpoint configuration dict passed
            directly to :meth:`DegreeHoursCalculator.calculate`.
        epw_variables : list of str  *or*  dict, optional
            Climate variables to include as monthly columns.

            **List form** (backward-compatible)::

                ['global_horizontal_radiation', 'wind_speed']

            One column per variable.  Aggregation is auto-detected:
            *sum* for radiation/energy variables, *mean* for the rest.

            **Dict form** — explicit aggregation(s) per variable::

                {
                    'global_horizontal_radiation': 'sum',
                    'dry_bulb_temperature': ['mean', 'max', 'min'],
                    'wind_speed': 'mean',
                }

            When multiple aggregations are requested the column names become
            ``<variable>_<aggfunc>`` (e.g. ``dry_bulb_temperature_mean``).
            Supported aggregation strings:
            ``'sum'``, ``'mean'``, ``'max'``, ``'min'``, ``'std'``.

            Defaults to ``{'global_horizontal_radiation': 'sum'}``.
            Available variable names: :attr:`DegreeHoursCalculator._EPW_ATTRS`.
        hours2 : list of int, optional
            Second set of hours for the degree-hour calculation
            (any subset of 0-23). Defaults to ``[0..7]`` (00:00–07:59).
            The column label is derived automatically from the provided values
            (e.g. ``heating_dh_0-8h``).
        zone_name : str, optional
            Zone/Space name forwarded to :meth:`DegreeHoursCalculator.calculate`.
        mode : str
            ``'heating'``, ``'cooling'``, or ``'both'`` (default).
        year : int, optional
            Year to assign to EPW data (overrides EPW header).
        frequencies : str or list of str, optional
            Frequencies to compute: ``'hourly'``, ``'daily'``, ``'monthly'``, ``'yearly'``.
            Defaults to ``['monthly']``.
        start_date : str, optional
            Start date in ``'DD/MM'`` format to restrict calculations.
        end_date : str, optional
            End date in ``'DD/MM'`` format to restrict calculations.
        """
        if not epw_paths:
            raise ValueError("epw_paths must contain at least one file path.")

        self.epw_paths        = list(epw_paths)
        self.setpoint_source  = setpoint_source
        self.epw_variables    = epw_variables   # stored as-is; resolved in run()
        self.hours2           = hours2 if hours2 is not None else list(range(8))
        self.zone_name        = zone_name
        self.mode             = mode
        self.year             = year
        self.start_date       = start_date
        self.end_date         = end_date

        if frequencies is None:
            frequencies = ['monthly']
        self.frequencies = [frequencies] if isinstance(frequencies, str) else list(frequencies)

        self.results: Optional[Dict[str, pd.DataFrame]] = None
        self.calculators: Dict[str, 'DegreeHoursCalculator'] = {}

    # -------------------------------------------------------------------------

    def _resolve_epw_variables(
        self,
    ) -> Dict[str, List[str]]:
        """
        Normalise ``self.epw_variables`` to the canonical internal format::

            {variable_name: [aggfunc, ...]}

        ``'auto'`` is a sentinel meaning "pick sum or mean based on variable
        type" (used when the caller supplied a plain list).

        Returns
        -------
        dict
            ``{var: ['aggfunc1', 'aggfunc2', ...]}``
        """
        raw = self.epw_variables

        # Default when nothing is specified
        if raw is None:
            return {'global_horizontal_radiation': ['sum']}

        # Plain list  → auto-detect aggregation, single column per variable
        if isinstance(raw, list):
            return {var: ['auto'] for var in raw}

        # Dict form  → normalise values to lists
        if isinstance(raw, dict):
            resolved: Dict[str, List[str]] = {}
            for var, agg in raw.items():
                if isinstance(agg, str):
                    resolved[var] = [agg]
                else:
                    resolved[var] = list(agg)
            return resolved

        raise TypeError(
            "epw_variables must be a list of strings or a dict "
            "{variable: aggfunc | [aggfunc, ...]}."
        )

    # -------------------------------------------------------------------------

    def run(self) -> Dict[str, pd.DataFrame]:
        """
        Execute the analysis for every EPW file.

        Returns
        -------
        dict
            A dictionary mapping each frequency to its corresponding summary
            DataFrame with a two-level column MultiIndex: ``(epw_name, variable)``.
        """
        # Store dataframes grouped by frequency and then by EPW
        # Structure: {freq: {epw_name: dataframe}}
        all_frames_by_freq: Dict[str, Dict[str, pd.DataFrame]] = {
            f: {} for f in self.frequencies
        }

        # Label for the custom hour range (e.g. '0-8h')
        h_label = f"{self.hours2[0]}-{self.hours2[-1] + 1}h"

        for epw_path in self.epw_paths:
            if not os.path.exists(epw_path):
                print(f"[WARNING] EPW not found, skipping: {epw_path}")
                continue

            epw_name = os.path.splitext(os.path.basename(epw_path))[0]
            print(f"\n{'='*60}\n[BATCH] {epw_name}\n{'='*60}")

            calc = DegreeHoursCalculator(epw_path, year=self.year)
            self.calculators[epw_name] = calc

            # --- Degree-hours: all 24 hours ---------------------------------
            res_24h_dict = calc.calculate(
                self.setpoint_source,
                frequency=self.frequencies,
                hours=None,
                mode=self.mode,
                zone_name=self.zone_name,
                start_date=self.start_date,
                end_date=self.end_date,
            )

            # --- Degree-hours: custom hour range ----------------------------
            res2_dict = calc.calculate(
                self.setpoint_source,
                frequency=self.frequencies,
                hours=self.hours2,
                mode=self.mode,
                zone_name=self.zone_name,
                start_date=self.start_date,
                end_date=self.end_date,
            )

            # --- Process EPW climate variables and build DataFrames ---------
            var_spec = self._resolve_epw_variables()

            # Optional mask for EPW variables
            mask = None
            if self.start_date or self.end_date:
                idx = calc.temperatures.index
                sd_str = self.start_date or "01/01"
                ed_str = self.end_date or "31/12"
                try:
                    sd = pd.to_datetime(f"{calc.year}/{sd_str}", format="%Y/%d/%m")
                    ed = pd.to_datetime(f"{calc.year}/{ed_str}", format="%Y/%d/%m") + pd.Timedelta(days=1, microseconds=-1)
                except Exception as e:
                    raise ValueError(f"Formato de fecha inválido. Usa 'DD/MM': {e}")
                
                if sd <= ed:
                    mask = (idx >= sd) & (idx <= ed)
                else:
                    mask = (idx >= sd) | (idx <= ed)

            for freq in self.frequencies:
                cols: Dict[str, pd.Series] = {}
                
                res_24h = res_24h_dict[freq]
                for col in res_24h.columns:
                    cols[f'{col}_24h'] = res_24h[col]
                    
                res2 = res2_dict[freq]
                for col in res2.columns:
                    cols[f'{col}_{h_label}'] = res2[col]

                # Process climate variables
                freq_code = {'hourly': 'h', 'daily': 'D', 'monthly': 'ME', 'yearly': 'YE'}[freq]

                for var, aggfuncs in var_spec.items():
                    if var not in calc.epw_data.columns:
                        if freq == self.frequencies[0]:  # Only print warning once
                            print(f"[WARNING] Variable '{var}' not in EPW data for {epw_name}.")
                        continue

                    series = calc.epw_data[var].copy()
                    if mask is not None:
                        series.loc[~mask] = np.nan

                    use_suffix = len(aggfuncs) > 1 or isinstance(self.epw_variables, dict)

                    for agg in aggfuncs:
                        if agg == 'auto':
                            if freq_code == 'h':
                                aggregated = series
                            else:
                                aggregated = (
                                    series.resample(freq_code).sum()
                                    if var in _RADIATION_VARS
                                    else series.resample(freq_code).mean()
                                )
                            col_name = var
                        else:
                            if freq_code == 'h':
                                # Without resampling, aggregation function doesn't make much sense, 
                                # but we pass it as-is (e.g. cumulative, though typically not used for hourly)
                                aggregated = series
                            else:
                                aggregated = series.resample(freq_code).agg(agg)
                            col_name = f'{var}_{agg}' if use_suffix else var

                        cols[col_name] = aggregated

                epw_df = pd.DataFrame(cols)
                
                # Align indices based on frequency
                if freq == 'monthly':
                    epw_df.index = epw_df.index.month
                    epw_df.index.name = 'month'
                elif freq == 'yearly':
                    epw_df.index = epw_df.index.year
                    epw_df.index.name = 'year'
                else:
                    epw_df.index.name = 'datetime'

                all_frames_by_freq[freq][epw_name] = epw_df

        if not any(all_frames_by_freq.values()):
            raise RuntimeError("No EPW files could be processed.")

        # Concatenate into MultiIndex-column DataFrames
        self.results = {}
        for freq, frames in all_frames_by_freq.items():
            if frames:
                df_concat = pd.concat(frames, axis=1)
                df_concat.columns.names = ['epw', 'variable']
                self.results[freq] = df_concat

        print("\n[BATCH] Análisis completado.")
        return self.results

    # -------------------------------------------------------------------------

    def export(self, output_path: str = 'batch_degree_hours.xlsx') -> str:
        """
        Export :attr:`results` to an Excel file.

        For each frequency requested, a combined sheet ``'all_epws_<freq>'`` is 
        created. If only one frequency is present, it may create individual 
        sheets per EPW (legacy behavior) or group them cleanly.

        Parameters
        ----------
        output_path : str
            Destination file path.

        Returns
        -------
        str
            Absolute path to the saved file.
        """
        if not self.results:
            raise ValueError("No results to export. Call run() first.")

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for freq, df in self.results.items():
                # Combined sheet for the frequency
                df.to_excel(writer, sheet_name=f'all_epws_{freq}'[:31])
                
                # If there's only one frequency, also create individual EPW sheets 
                # (backward compatible layout)
                if len(self.results) == 1:
                    for epw_name in df.columns.get_level_values('epw').unique():
                        epw_df = df[epw_name]
                        sheet = epw_name[:31]
                        epw_df.to_excel(writer, sheet_name=sheet)

        abs_path = os.path.abspath(output_path)
        print(f"[INFO] Results exported to: {abs_path}")
        return abs_path
