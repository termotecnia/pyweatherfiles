# -*- coding: utf-8 -*-
"""
tests/test_regression_epw_pipeline.py
========================================

End-to-end regression tests for the EPW-writing pipelines refactored in
Fase 1 (``INFORME_REVISION_GENERAL.md`` §6): both
:meth:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter.transform_to_epw`
and :func:`~pyweatherfiles.met_epw_converter.convert_met_to_epw` now share
their low-level EPW plumbing via :mod:`pyweatherfiles.epw_field_utils`; these
tests confirm the full pipelines still produce physically sensible, valid
EPW files.

Unlike a manual check against real files under ``onedrive_backup/`` (which
is git-ignored and therefore not reproducible on a clean checkout / CI),
everything here is generated synthetically:

- The base EPW template is built in-memory with
  ``ladybug.epw.EPW.from_missing_values()`` (no file needed).
- The hourly source series (for ``HourlyEPWConverter``) and the ``.met``
  file (for ``convert_met_to_epw``) are generated on the fly with a fixed
  random seed, matching the column-naming defaults of each converter.
"""

import math

import numpy as np
import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles import hourly_epw_converter, met_epw_converter

LAT, LON, ELEV, TZ = 37.38, -5.98, 15.0, 1.0
YEAR = 2005  # non-leap


@pytest.fixture
def base_epw_path(tmp_path):
    """A fully synthetic, minimal-but-valid EPW template (no external file)."""
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(
        city="TestCity", latitude=LAT, longitude=LON, time_zone=TZ, elevation=ELEV
    )
    path = tmp_path / "template.epw"
    epw.save(str(path))
    return str(path)


def _synthetic_hourly_dataframe():
    """8760-row synthetic hourly weather series, columns matching
    HourlyEPWConverter's default column-name expectations."""
    idx = pd.date_range(f"{YEAR}-01-01 00:00", periods=8760, freq="h")
    hour = idx.hour.values
    doy = idx.dayofyear.values

    t_db = 18 + 8 * np.sin(2 * np.pi * (doy / 365.0)) + 4 * np.sin(2 * np.pi * (hour / 24.0))
    t_dp = t_db - 6.0
    is_day = (hour >= 6) & (hour <= 19)
    ghi = np.where(is_day, np.maximum(0.0, 400 * np.sin(np.pi * (hour - 6) / 13.0)), 0.0)
    dni = np.where(is_day, np.maximum(0.0, 500 * np.sin(np.pi * (hour - 6) / 13.0)), 0.0)

    return pd.DataFrame(
        {
            "time": idx,
            "Dry-bulb temperature": t_db,
            "Dew Point temperature": t_dp,
            "Wind Speed": np.full(8760, 10.8),  # km/h -> 3.0 m/s after conversion
            "Global Horizontal Irradiance ": ghi,
            "Beam Normal Irradiance ": dni,
        }
    )


def _synthetic_met_file(path):
    """8760-row synthetic .met file (13-column variant, see met_epw_converter.py)."""
    idx = pd.date_range(f"{YEAR}-01-01 01:00", periods=8760, freq="h")
    rows = []
    for ts in idx:
        hour = ts.hour + 1  # .met Hour column is 1..24 (end of interval)
        t_db = 18 + 8 * math.sin(2 * math.pi * (ts.dayofyear / 365.0)) + 4 * math.sin(
            2 * math.pi * (ts.hour / 24.0)
        )
        sky_t = t_db - 10
        is_day = 6 <= ts.hour <= 19
        rad_dir = max(0.0, 400 * math.sin(math.pi * (ts.hour - 6) / 13.0)) if is_day else 0.0
        rad_dif = max(0.0, 100 * math.sin(math.pi * (ts.hour - 6) / 13.0)) if is_day else 0.0
        rows.append(
            [ts.month, ts.day, hour, round(t_db, 2), round(sky_t, 2),
             round(rad_dir, 1), round(rad_dif, 1), 0.008, 55.0, 3.0, 180, 0, 0]
        )
    df = pd.DataFrame(rows)
    with open(path, "w") as f:
        f.write("synthetic.met 0.0\n")
        f.write(f"{LAT} {LON} {ELEV} 0.0\n")
        df.to_csv(f, sep=" ", header=False, index=False)


class TestHourlyEPWConverterRegression:
    def test_transform_to_epw_produces_valid_epw(self, tmp_path, base_epw_path):
        source_path = tmp_path / "hourly_source.csv"
        _synthetic_hourly_dataframe().to_csv(source_path, index=False)

        converter = hourly_epw_converter.HourlyEPWConverter(
            file_path=str(source_path), base_epw_path=base_epw_path
        )
        out_path = tmp_path / "out.epw"
        success = converter.process(
            output_dir=str(tmp_path), years=[YEAR],
            output_pattern="out.epw", save_session=False,
        )
        assert success == [YEAR]
        assert out_path.exists()

        epw = EPW(str(out_path))
        tdb = list(epw.dry_bulb_temperature.values)
        patm = list(epw.atmospheric_station_pressure.values)
        illum = list(epw.global_horizontal_illuminance.values)

        assert len(tdb) == 8760
        assert -10 < min(tdb) and max(tdb) < 45  # physically plausible range
        # Pressure column absent from source -> filled via the shared
        # epw_field_utils.calculate_atmos_pressure fallback.
        assert all(p == pytest.approx(patm[0]) for p in patm[:5])
        # One of the 15 EnergyPlus-unused fields must be neutralised.
        assert illum[0] == 999999


class TestMetEpwConverterRegression:
    def test_convert_met_to_epw_produces_valid_epw(self, tmp_path, base_epw_path):
        met_path = tmp_path / "synthetic.met"
        _synthetic_met_file(met_path)
        out_path = tmp_path / "out_met.epw"

        ok = met_epw_converter.convert_met_to_epw(
            met_path=str(met_path),
            base_epw_path=base_epw_path,
            epw_path=str(out_path),
            replace_unused_with_missing=True,
            save_session=False,
        )
        assert ok is True
        assert out_path.exists()

        epw = EPW(str(out_path))
        tdb = list(epw.dry_bulb_temperature.values)
        ghi = list(epw.global_horizontal_radiation.values)
        illum = list(epw.global_horizontal_illuminance.values)

        assert len(tdb) == 8760
        assert -10 < min(tdb) and max(tdb) < 45
        assert sum(ghi) > 0
        # One of the 15 EnergyPlus-unused fields must be neutralised.
        assert illum[0] == 999999

