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

# SCHEDULE:WEEK:DAILY field index for each Python weekday()
# Fields after Name: [Sun, Mon, Tue, Wed, Thu, Fri, Sat, Holiday, SDD, WDD]
WEEKDAILY_FIELD: Dict[int, int] = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}


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

