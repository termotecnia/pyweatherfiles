# -*- coding: utf-8 -*-
"""
tests/test_export_utils.py
=============================

Unit tests for :func:`pyweatherfiles._export_utils.export_frames_to_excel`
(Fase 6 of ``INFORME_REVISION_GENERAL.md`` §6: shared Excel-export helper
factored out of ``climate_processor.py``, ``degree_hours/*.py`` and
``epw_trend_analyzer/_core.py``).
"""

import pandas as pd
import pytest

from pyweatherfiles._export_utils import export_frames_to_excel


def _df(n=2):
    return pd.DataFrame({"a": range(n), "b": range(n, 2 * n)})


class TestExportFramesToExcel:
    def test_writes_one_sheet_per_dataframe(self, tmp_path):
        out = tmp_path / "out.xlsx"
        export_frames_to_excel({"sheet1": _df(), "sheet2": _df(3)}, out)

        sheets = pd.read_excel(out, sheet_name=None)
        assert set(sheets.keys()) == {"sheet1", "sheet2"}
        assert len(sheets["sheet2"]) == 3

    def test_default_index_true_matches_pandas_default(self, tmp_path):
        out = tmp_path / "out.xlsx"
        df = _df().set_index("a")
        export_frames_to_excel({"sheet1": df}, out)

        # Default index=True means the 'a' index is written back as a column
        result = pd.read_excel(out, sheet_name="sheet1")
        assert "a" in result.columns

    def test_index_false_global(self, tmp_path):
        out = tmp_path / "out.xlsx"
        df = _df().set_index("a")
        export_frames_to_excel({"sheet1": df}, out, index=False)

        result = pd.read_excel(out, sheet_name="sheet1")
        assert "a" not in result.columns

    def test_index_per_sheet_dict(self, tmp_path):
        out = tmp_path / "out.xlsx"
        df1 = _df().set_index("a")
        df2 = _df(3).set_index("a")
        export_frames_to_excel(
            {"with_index": df1, "without_index": df2},
            out,
            index={"without_index": False},
        )

        with_index = pd.read_excel(out, sheet_name="with_index")
        without_index = pd.read_excel(out, sheet_name="without_index")
        assert "a" in with_index.columns  # not overridden -> pandas default True
        assert "a" not in without_index.columns

    def test_none_entries_are_skipped(self, tmp_path):
        out = tmp_path / "out.xlsx"
        export_frames_to_excel({"present": _df(), "missing": None}, out)

        sheets = pd.read_excel(out, sheet_name=None)
        assert set(sheets.keys()) == {"present"}

    def test_empty_dataframes_skipped_by_default(self, tmp_path):
        out = tmp_path / "out.xlsx"
        export_frames_to_excel({"present": _df(), "empty": pd.DataFrame()}, out)

        sheets = pd.read_excel(out, sheet_name=None)
        assert set(sheets.keys()) == {"present"}

    def test_skip_empty_false_keeps_empty_sheets(self, tmp_path):
        out = tmp_path / "out.xlsx"
        export_frames_to_excel(
            {"present": _df(), "empty": pd.DataFrame({"col": []})},
            out,
            skip_empty=False,
        )

        sheets = pd.read_excel(out, sheet_name=None)
        assert set(sheets.keys()) == {"present", "empty"}

    def test_sheet_name_truncated_to_excel_limit(self, tmp_path):
        out = tmp_path / "out.xlsx"
        long_name = "a" * 40
        export_frames_to_excel({long_name: _df()}, out)

        sheets = pd.read_excel(out, sheet_name=None)
        assert list(sheets.keys()) == [long_name[:31]]

    def test_returns_path_unchanged(self, tmp_path):
        out = tmp_path / "out.xlsx"
        result = export_frames_to_excel({"sheet1": _df()}, out)
        assert result == out

