# -*- coding: utf-8 -*-
"""
epw_utils.py
=============

Small, dependency-light helpers shared by every "analyse a whole *set* of
EPW files, classified into named groups from their filename" class in the
package (currently used by
:class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer`).

Kept in its own module (rather than duplicated in each analyser) so the
filename-classification convention — a regex with named groups ``group``
(e.g. city/climate) and ``year`` — stays identical everywhere it is used.

Author: Daniel Sánchez-García
"""

import glob
import os
import re
from typing import Dict, List, Optional

# Matches '<group>_<year>.epw', e.g. 'granada_2005.epw' -> group='granada', year=2005
DEFAULT_EPW_GROUP_YEAR_PATTERN = r'^(?P<group>[a-zA-Z]+)_(?P<year>\d{4})\.epw$'


def classify_epw_files(
    epw_dir: Optional[str] = None,
    epw_paths: Optional[List[str]] = None,
    filename_pattern: str = DEFAULT_EPW_GROUP_YEAR_PATTERN,
) -> Dict[str, Dict[int, str]]:
    """
    Classify a set of EPW files into ``{group: {year: path}}`` from their
    filename, using a regex with named groups ``group`` (the classification
    key, e.g. city) and ``year`` (4-digit).

    Parameters
    ----------
    epw_dir : str, optional
        Folder scanned (non-recursively) for ``*.epw`` files. Ignored if
        *epw_paths* is given.
    epw_paths : list of str, optional
        Explicit list of EPW paths to classify, instead of scanning
        *epw_dir*.
    filename_pattern : str, optional
        Regex matched against ``os.path.basename(path)``. Must define named
        groups ``group`` (or ``city``, accepted as an alias — see below)
        and ``year``. Default matches ``'<group>_<year>.epw'`` (e.g.
        ``'granada_2005.epw'``). Files that do not match are skipped with
        a warning.

    Returns
    -------
    dict
        ``{group: {year: epw_path}}``.

    Raises
    ------
    ValueError
        If neither *epw_dir* nor *epw_paths* is provided, or if
        *filename_pattern* does not define a usable ``year`` group for a
        matched file.

    Notes
    -----
    The classification key is read from the regex's ``group`` named group
    if present, falling back to ``city`` (the name used by
    :class:`~pyweatherfiles.epw_trend_analyzer.EpwTrendAnalyzer`'s
    ``TrendConfig.filename_regex``, e.g. ``r"^(?P<city>[A-Za-z]+)_(?P<year>\\d{4})\\.epw$"``),
    and finally to the file name without its extension. This lets both
    analyzers in the package share this single classification helper
    regardless of which name they historically gave to that regex group
    (see ``INFORME_REVISION_GENERAL.md`` §3.3/Fase 4).

    Example
    -------
    >>> classify_epw_files(epw_dir="longterm_epw")  # doctest: +SKIP
    {'granada': {2005: '...granada_2005.epw', ...}, ...}
    """
    if epw_dir is None and not epw_paths:
        raise ValueError("Provide either 'epw_dir' or 'epw_paths'.")

    pattern = re.compile(filename_pattern)
    paths = list(epw_paths) if epw_paths else sorted(glob.glob(os.path.join(epw_dir, '*.epw')))

    found: Dict[str, Dict[int, str]] = {}
    for path in paths:
        fname = os.path.basename(path)
        m = pattern.match(fname)
        if not m:
            print(f"[WARNING] Filename does not match filename_pattern, skipping: {fname}")
            continue
        gd = m.groupdict()
        group = gd.get('group') or gd.get('city') or os.path.splitext(fname)[0]
        try:
            year = int(gd['year'])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "filename_pattern must define a named group 'year' (4-digit) "
                f"— got groups: {gd}"
            )
        found.setdefault(group, {})[year] = path

    print(
        f"[INFO] Classified {sum(len(v) for v in found.values())} EPW file(s) "
        f"into {len(found)} group(s): {list(found.keys())}"
    )
    return found


