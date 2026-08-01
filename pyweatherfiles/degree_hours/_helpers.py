# -*- coding: utf-8 -*-
"""
degree_hours/_helpers.py
===========================

Low-level, dependency-free helpers shared by
:mod:`~pyweatherfiles.degree_hours.calculator` (IDF schedule parsing).

Extracted from the former monolithic ``degree_hours.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6) when the module was split into a
package (``calculator.py`` / ``batch_analyzer.py`` / ``group_trend_analyzer.py``),
keeping the exact same logic — this file only groups the small
module-level constants/functions that do not belong to any single class.
"""

from typing import Dict, List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Maps lowercase EnergyPlus day-type tokens → Python weekday() values
# Python weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
EP_DAYTYPE_WEEKDAYS: Dict[str, List[int]] = {
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

# SCHEDULE:WEEK:DAILY field index for each Python weekday(), as an index into
# eppy's raw fieldvalues list — which always starts with the object type
# (fieldvalues[0] == 'Schedule:Week:Daily'), then Name (1), then
# [Sun(2), Mon(3), Tue(4), Wed(5), Thu(6), Fri(7), Sat(8), Holiday, SDD, WDD].
# (Bug fixed here: this used to be {6: 1, 0: 2, ...}, i.e. off by one — it
# assumed fieldvalues[0] was already the Name, not the object type. Never
# previously exercised by any real IDF in this repo, which only uses
# SCHEDULE:COMPACT, never SCHEDULE:WEEK:DAILY.)
WEEKDAILY_FIELD: Dict[int, int] = {6: 2, 0: 3, 1: 4, 2: 5, 3: 6, 4: 7, 5: 8}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def until_to_hour(time_str: str) -> int:
    """'HH:MM' → exclusive upper-bound hour index (0-24)."""
    return int(time_str.strip().split(':')[0])


def build_24h_profile(pairs: List[Tuple[int, float]]) -> np.ndarray:
    """Convert [(exclusive_upper_hour, value)] pairs to a 24-element array."""
    profile = np.full(24, np.nan)
    prev = 0
    for until_h, val in sorted(pairs, key=lambda x: x[0]):
        profile[prev:until_h] = val
        prev = until_h
    return profile


def idf_objects(idf, key: str) -> list:
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

