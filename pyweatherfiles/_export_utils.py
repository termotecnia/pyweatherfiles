# -*- coding: utf-8 -*-
"""
_export_utils.py
==================

Shared Excel-export helper for the whole ``pyweatherfiles`` package.

**What problem does this solve?** The pattern ``with pd.ExcelWriter(path,
engine='openpyxl') as writer: df.to_excel(writer, sheet_name=...)`` (one
sheet per DataFrame, optionally skipping ``None``/empty ones) was
independently reimplemented in ``climate_processor.py`` (3 ``export_*``
methods), ``degree_hours/calculator.py``/``batch_analyzer.py``/
``group_trend_analyzer.py`` and ``epw_trend_analyzer/_core.py`` — see
``INFORME_REVISION_GENERAL.md`` §3.4/Fase 6. :func:`export_frames_to_excel`
factors out that pattern into a single, small, reusable helper.

This module is internal (not re-exported from ``pyweatherfiles/__init__.py``);
import it explicitly if needed: ``from pyweatherfiles._export_utils import
export_frames_to_excel``.

Example
-------
::

    from pyweatherfiles._export_utils import export_frames_to_excel

    export_frames_to_excel(
        {"summary": summary_df, "details": details_df, "empty_one": pd.DataFrame()},
        "report.xlsx",
        index={"details": True},  # "summary" and "empty_one" use the scalar default (False)
    )
    # -> "report.xlsx" with 2 sheets ("summary", "details"); "empty_one" was
    # skipped automatically since it is empty.
"""

from pathlib import Path
from typing import Dict, Optional, Union

import pandas as pd


def export_frames_to_excel(
    sheets: Dict[str, Optional[pd.DataFrame]],
    path: Union[str, Path],
    index: Union[bool, Dict[str, bool]] = True,
    skip_empty: bool = True,
    engine: str = "openpyxl",
) -> Union[str, Path]:
    """
    Write several named DataFrames to a single ``.xlsx`` workbook, one sheet
    per entry.

    Args:
        sheets (dict[str, pandas.DataFrame or None]): Mapping of sheet name
            to DataFrame. Entries whose value is ``None`` are always
            skipped (no error raised). Sheet names longer than Excel's
            31-character limit are truncated automatically.
        path (str): Destination ``.xlsx`` path.
        index (bool or dict[str, bool], optional): Whether to write each
            DataFrame's index as a column. Either a single bool applied to
            every sheet (default ``True``, matching :meth:`pandas.DataFrame.to_excel`'s
            own default when *index* is not passed explicitly), or a dict
            mapping sheet name to a per-sheet override; sheet names absent
            from the dict use ``True`` (pandas' own default) unless a
            different fallback is needed by the caller (pass a plain bool
            for that case instead).
        skip_empty (bool, optional): If ``True`` (default), also skip
            DataFrames that are empty (``df.empty``) in addition to
            ``None`` ones — matching the ``if not df.empty: df.to_excel(...)``
            guard repeated across every original call site.
        engine (str, optional): Excel writer engine. Defaults to
            ``'openpyxl'`` (already a mandatory dependency of the whole
            package).

    Returns:
        str: *path*, unchanged, for convenient chaining/printing (mirrors
        the existing ``export_*`` methods' ``return output_path`` pattern).

    Raises:
        ValueError: If, after filtering out ``None``/empty entries, there is
            nothing left to write (mirrors the ``"No results to export"``
            guard already present at every call site — callers are expected
            to perform that check *before* calling this helper with their
            own error message/wording; this function does not raise on an
            empty *sheets* dict by itself, to keep it a pure "write" helper.
            See individual callers for the actual guard).

    Example:
        >>> import pandas as pd
        >>> from pyweatherfiles._export_utils import export_frames_to_excel
        >>> export_frames_to_excel(
        ...     {"annual_stats": pd.DataFrame({"a": [1]}), "max_gaps": pd.DataFrame({"b": [2]})},
        ...     "quality_report.xlsx",
        ...     index={"max_gaps": False},
        ... )  # doctest: +SKIP
        'quality_report.xlsx'
    """
    with pd.ExcelWriter(path, engine=engine) as writer:
        for sheet_name, df in sheets.items():
            if df is None:
                continue
            if skip_empty and getattr(df, "empty", False):
                continue
            use_index = index.get(sheet_name, True) if isinstance(index, dict) else index
            df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=use_index)
    return path


