# -*- coding: utf-8 -*-
"""
epw_field_utils.py
====================

Low-level EPW field helpers shared by
:mod:`~pyweatherfiles.hourly_epw_converter` and
:mod:`~pyweatherfiles.met_epw_converter`.

Those two modules independently write EPW files from different source
formats (cleaned hourly CSV/Excel series, and the Spanish ``.met``
reference-climate format respectively), but both need the exact same
low-level EPW plumbing:

- Compensating Ladybug's internal "point-in-time" index offset when
  reading/writing hourly fields (:func:`set_epw_values` / :func:`get_epw_values`).
- Estimating standard atmospheric pressure by elevation when the source has
  no pressure column (:func:`calculate_atmos_pressure`).
- Neutralising the 15 EPW fields that EnergyPlus does not actually use with
  their official "missing value" codes (:data:`UNUSED_EPW_FIELDS` /
  :func:`neutralize_unused_epw_fields`).

Centralising them here (instead of keeping near-identical copies in both
converter modules, as in versions prior to this module) means a single
place to fix bugs or extend behaviour. See ``INFORME_REVISION_GENERAL.md``
§3.1 for the duplication this module replaces.
"""

from typing import Dict, Iterable, List, Optional

# =============================================================================
# Standard atmospheric pressure by elevation (international barometric formula)
# =============================================================================


def calculate_atmos_pressure(elevation_m: float) -> float:
    """Estimate the standard atmospheric pressure at *elevation_m* using the
    international barometric formula (ISA, constant lapse-rate model).

    ``P(h) = P0 * (1 - L*h/T0) ** (g*M / (R*L))`` with the standard sea-level
    constants ``P0=101325 Pa``, ``L=0.0065 K/m``, ``T0=288.15 K``,
    ``g=9.80665 m/s2``, ``M=0.0289644 kg/mol``, ``R=8.31447 J/(mol*K)``.

    Used as a fallback wherever a source format does not provide atmospheric
    pressure directly (e.g. hourly CSV/Excel series without a pressure
    column, or the ``.met`` format when the pressure reverse-engineered from
    absolute humidity is not physically plausible).

    Args:
        elevation_m (float): Site elevation above sea level, in metres.

    Returns:
        float: Estimated standard atmospheric pressure in Pascals.

    Example:
        >>> round(calculate_atmos_pressure(0), 0)
        101325.0
    """
    p0 = 101325
    lapse_rate = 0.0065
    t0 = 288.15
    g = 9.80665
    m = 0.0289644
    r = 8.31447
    return p0 * (1 - (lapse_rate * elevation_m) / t0) ** ((g * m) / (r * lapse_rate))


# =============================================================================
# Ladybug "point-in-time" offset compensation
# =============================================================================


def set_epw_values(epw_obj, field_name: str, new_vals) -> None:
    """
    Assign *new_vals* to a Ladybug ``EPW`` hourly field, compensating for
    Ladybug's internal "point-in-time" index offset.

    Source formats used across this package (hourly CSV/Excel series,
    ``.met`` files) index their first hourly record as hour 1 (01:00) of
    January 1st, whereas Ladybug's *point-in-time* fields (e.g. dry-bulb
    temperature) expect index 0 to correspond to the *end* of the last hour
    of the year, rotated to the front. This helper shifts the values one
    position (``[last] + values[:-1]``) before assigning them so the
    resulting EPW file is correctly aligned; fields that are **not**
    point-in-time (e.g. cumulative/integrated quantities) are assigned as-is.

    Args:
        epw_obj (ladybug.epw.EPW): The EPW object being populated.
        field_name (str): Name of the EPW data-collection attribute to set
            (e.g. ``'dry_bulb_temperature'``).
        new_vals (list or tuple): The new hourly values, index 0 = first
            hour of the source data (typically Jan 1st, 01:00).

    Returns:
        None: The field is updated in place on *epw_obj*.
    """
    field = getattr(epw_obj, field_name)
    if field.header.data_type.point_in_time:
        shifted = [new_vals[-1]] + list(new_vals[:-1])
        field.values = tuple(shifted) if isinstance(field.values, tuple) else list(shifted)
    else:
        field.values = tuple(new_vals) if isinstance(field.values, tuple) else list(new_vals)


def get_epw_values(epw_obj, field_name: str) -> List:
    """
    Read hourly values from a Ladybug ``EPW`` field, compensating for the
    same "point-in-time" index offset described in :func:`set_epw_values`,
    so that index 0 of the returned list corresponds to hour 1 (01:00) of
    January 1st rather than Ladybug's internal Jan-1st-00:00 convention.

    Args:
        epw_obj (ladybug.epw.EPW): The EPW object to read from.
        field_name (str): Name of the EPW data-collection attribute to read
            (e.g. ``'dry_bulb_temperature'``).

    Returns:
        list: The hourly values (length 8760/8784), re-aligned so index 0
        corresponds to hour 1 (01:00) of January 1st.
    """
    field = getattr(epw_obj, field_name)
    vals = list(field.values)
    if field.header.data_type.point_in_time:
        return vals[1:] + [vals[0]]
    return vals


# =============================================================================
# EPW fields not used by EnergyPlus: neutralise with the official "missing"
# value codes instead of leaving them at 0 (which EnergyPlus could otherwise
# silently misinterpret as valid data).
# =============================================================================

UNUSED_EPW_FIELDS: Dict[str, float] = {
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
    'liquid_precipitation_quantity': 99,
}
"""dict[str, float]: The 15 EPW hourly fields that EnergyPlus does not
actually read, mapped to their official "missing value" codes (see the EPW
data-dictionary in the EnergyPlus Auxiliary Programs documentation)."""


def neutralize_unused_epw_fields(epw_obj, num_rows: int, skip_fields: Optional[Iterable[str]] = None) -> None:
    """
    Fill every field in :data:`UNUSED_EPW_FIELDS` with its official EPW
    "missing value" code, for every field that exists on *epw_obj*.

    Args:
        epw_obj (ladybug.epw.EPW): The EPW object being populated.
        num_rows (int): Number of hourly rows (8760 or 8784) to fill.
        skip_fields (Iterable[str], optional): Field names to leave
            untouched instead of neutralising (e.g. ``{'total_sky_cover'}``
            when a real cloud-cover column is available and should be
            preserved — see ``preserve_extra`` in
            :class:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`).

    Returns:
        None: Fields are updated in place on *epw_obj*.
    """
    skip = set(skip_fields or ())
    for field_name, missing_val in UNUSED_EPW_FIELDS.items():
        if field_name in skip or not hasattr(epw_obj, field_name):
            continue
        replacement_list = [missing_val] * num_rows
        field_obj = getattr(epw_obj, field_name)
        if hasattr(field_obj, 'header') and hasattr(field_obj, 'values'):
            set_epw_values(epw_obj, field_name, replacement_list)
        else:
            try:
                setattr(epw_obj, field_name, tuple(replacement_list))
            except Exception:
                pass

