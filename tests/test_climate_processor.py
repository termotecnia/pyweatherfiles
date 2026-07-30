# -*- coding: utf-8 -*-
"""
tests/test_climate_processor.py
==================================

Regression tests for :class:`pyweatherfiles.climate_processor.ClimateProcessor`,
focused on the ``export_annual_statistics``/``export_complete_report`` methods
refactored in Fase 6 of ``INFORME_REVISION_GENERAL.md`` (§6) to use the new
shared :func:`pyweatherfiles._export_utils.export_frames_to_excel` helper.

Requires the optional ``pvlib`` dependency (extra ``climate``); the whole
module is skipped automatically if it is not installed.
"""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pvlib")

from pyweatherfiles.climate_processor import ClimateProcessor  # noqa: E402


def _make_station_csv(path, hours=5 * 24, gap_hours=(30, 31, 32)):
    """Builds a synthetic hourly weather-station CSV with deterministic
    values and a deliberate gap (dropped rows, at *gap_hours*) so that
    ``ClimateProcessor``'s gap-filling/statistics logic (``gaps_df``,
    ``annual_stats``, ``max_gaps_df``) has something non-empty to report,
    exercising every sheet of ``export_complete_report``.
    """
    idx = pd.date_range("2020-01-01", periods=hours, freq="h")
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "Date": idx.strftime("%d/%m/%Y %H:%M"),
        "Dry Bulb Temp": 15 + 5 * np.sin(np.linspace(0, 6, hours)) + rng.normal(0, 0.2, hours),
        "Dew Point Temp": 10 + 3 * np.sin(np.linspace(0, 6, hours)),
        "Humidity": np.clip(60 + rng.normal(0, 5, hours), 0, 100),
        "Wind Direction": rng.uniform(0, 360, hours),
        "Wind Speed": np.clip(2 + rng.normal(0, 0.5, hours), 0, None),
        "Pressure": 101325 + rng.normal(0, 50, hours),
        "Global Horizontal Irradiance": np.clip(300 + 200 * np.sin(np.linspace(0, 20, hours)), 0, None),
        "Beam Horizontal Irradiance": np.clip(150 + 100 * np.sin(np.linspace(0, 20, hours)), 0, None),
        "Diffuse Horizontal Irradiance": np.clip(100 + 50 * np.sin(np.linspace(0, 20, hours)), 0, None),
        "Normal Radiation": np.clip(400 + 150 * np.sin(np.linspace(0, 20, hours)), 0, None),
    })
    df = df.drop(index=list(gap_hours)).reset_index(drop=True)
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def processor(tmp_path):
    csv_path = _make_station_csv(tmp_path / "station.csv")
    return ClimateProcessor(csv_path, lat=37.38, lon=-5.98, alt=15)


class TestClimateProcessorExports:
    def test_export_annual_statistics_creates_expected_sheets(self, processor, tmp_path):
        out = tmp_path / "annual.xlsx"
        result = processor.export_annual_statistics(str(out))

        assert result == str(out)
        assert out.exists()
        sheets = pd.read_excel(out, sheet_name=None)
        # Both non-empty given the deliberate gap in the fixture
        assert "annual_stats" in sheets
        assert "max_gaps" in sheets
        assert not sheets["max_gaps"].empty

    def test_export_complete_report_creates_expected_sheets(self, processor, tmp_path):
        out = tmp_path / "full.xlsx"
        result = processor.export_complete_report(str(out))

        assert result == str(out)
        sheets = pd.read_excel(out, sheet_name=None)
        assert "filled" in sheets
        assert "summary" in sheets
        assert len(sheets["filled"]) == 5 * 24  # reindexed to a full, gap-free hourly series
        for col in processor.working_cols:
            assert col in sheets["filled"].columns

