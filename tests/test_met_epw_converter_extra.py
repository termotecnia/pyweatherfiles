# -*- coding: utf-8 -*-
"""
tests/test_met_epw_converter_extra.py
========================================

Additional tests for :mod:`pyweatherfiles.met_epw_converter`'s two main
entry points, :func:`~pyweatherfiles.met_epw_converter.convert_met_to_epw`
and :func:`~pyweatherfiles.met_epw_converter.convert_epw_to_met`
(``met_epw_converter.py`` was 64% covered before this file per
``INFORME_REVISION_GENERAL.md``'s Fase 2 coverage analysis:
``tests/test_met_epw_converter_physics.py`` only covers the pure physical
helper functions, and ``tests/test_regression_epw_pipeline.py`` only
exercises the simplest 13-column happy path of ``convert_met_to_epw()``).
This file complements both with the header/data-start auto-detection
fallbacks, the 15-column variant, error handling, the DNI QA branches,
session persistence, and the entire ``convert_epw_to_met()`` direction
(never exercised before this file).
"""

import os

import numpy as np
import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

from pyweatherfiles.met_epw_converter import convert_epw_to_met, convert_met_to_epw

LAT, LON, ELEV, TZ = 37.38, -5.98, 15.0, 1.0
N_HOURS = 8760


@pytest.fixture
def base_epw_path(tmp_path):
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city="TestCity", latitude=LAT, longitude=LON, time_zone=TZ, elevation=ELEV)
    path = tmp_path / "template.epw"
    epw.save(str(path))
    return str(path)


def _met_data_rows(num_cols=13, negative_dir_at=None):
    """Build 8760 rows of plausible .met data (see COLS_MET_13/COLS_MET_15),
    with Month/Day/Hour derived the same way convert_epw_to_met() itself
    builds them (guarantees row 0 is exactly Month=1, Day=1, Hour=1)."""
    dir_horiz = np.clip(250 * np.sin(np.linspace(0, 40 * np.pi, N_HOURS)), 0, None)
    if negative_dir_at is not None:
        dir_horiz = dir_horiz.copy()
        dir_horiz[negative_dir_at] = -50.0
    diff_horiz = np.full(N_HOURS, 50.0)

    rows = []
    for i in range(N_HOURS):
        ts = pd.Timestamp(2005, 1, 1) + pd.Timedelta(hours=i)
        base = [ts.month, ts.day, ts.hour + 1, 15.0, 5.0, round(float(dir_horiz[i]), 2),
                diff_horiz[i], 0.008, 60.0, 3.0, 180.0, 90.0, 45.0]
        if num_cols == 13:
            rows.append(base)
        else:  # 15-column variant: no WindDir, +2 unused placeholder columns
            rows.append(base[:10] + [0] + base[11:13] + [0, 0])
    return rows


def _write_met_file(path, num_cols=13, negative_dir_at=None,
                     extra_line_before_meta=None, extra_line_before_data=None,
                     lat=LAT, lon=LON, elev=ELEV):
    lines = [f"test_city {round(lon / 15.0) * 15.0}"]
    if extra_line_before_meta:
        lines.append(extra_line_before_meta)
    lines.append(f"{lat} {lon} {elev} 0.0")
    if extra_line_before_data:
        lines.append(extra_line_before_data)
    for row in _met_data_rows(num_cols=num_cols, negative_dir_at=negative_dir_at):
        lines.append(" ".join(str(v) for v in row))
    path.write_text("\n".join(lines))


class TestConvertMetToEpwHappyPath:
    def test_creates_valid_epw_with_13_columns(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is True

        epw = EPW(str(out_path))
        assert len(list(epw.dry_bulb_temperature.values)) == 8760
        assert list(epw.dry_bulb_temperature.values)[0] == pytest.approx(15.0)
        assert epw.location.latitude == pytest.approx(LAT)
        # tz_hour is always derived as round(lon / 15.0), independent of the
        # base EPW template's own time zone (TZ=1.0 in the fixture).
        assert epw.location.time_zone == round(LON / 15.0)

    def test_creates_valid_epw_with_15_columns(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville15.met"
        _write_met_file(met_path, num_cols=15)
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is True
        epw = EPW(str(out_path))
        # The 15-column variant has no WindDir column -> defaults to all zero.
        assert list(epw.wind_direction.values)[0] == 0
        assert len(list(epw.dry_bulb_temperature.values)) == 8760

    def test_replace_unused_with_missing_neutralizes_fields(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"

        convert_met_to_epw(str(met_path), str(out_path), base_epw_path,
                            replace_unused_with_missing=True, save_session=False)
        epw = EPW(str(out_path))
        assert list(epw.global_horizontal_illuminance.values)[0] == pytest.approx(999999.0)

    def test_replace_unused_with_missing_false_leaves_fields_untouched(self, tmp_path):
        # EPW.from_missing_values() already defaults global_horizontal_illuminance
        # to 999999, so a dedicated template with a distinguishable custom
        # value is needed to prove replace_unused_with_missing=False truly
        # leaves it untouched (instead of trivially matching the default).
        epw = EPW.from_missing_values(is_leap_year=False)
        epw.location = Location(city="TestCity", latitude=LAT, longitude=LON, time_zone=TZ, elevation=ELEV)
        epw.global_horizontal_illuminance.values = [12345.0] * 8760
        custom_base_epw_path = tmp_path / "custom_template.epw"
        epw.save(str(custom_base_epw_path))

        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"

        convert_met_to_epw(str(met_path), str(out_path), str(custom_base_epw_path),
                            replace_unused_with_missing=False, save_session=False)
        result_epw = EPW(str(out_path))
        assert list(result_epw.global_horizontal_illuminance.values)[0] == pytest.approx(12345.0)

    def test_negative_direct_radiation_input_is_reported_and_clipped(self, tmp_path, base_epw_path, capsys):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13, negative_dir_at=100)
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is True  # negative input must not crash, only be clipped and reported in the QA log
        assert "negative_dir_horiz=1" in capsys.readouterr().out

    def test_save_session_creates_pkl_and_json(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        convert_met_to_epw(str(met_path), str(out_path), base_epw_path,
                            save_session=True, session_dir=str(session_dir))
        assert list(session_dir.glob("*.pkl"))
        assert list(session_dir.glob("*.json"))

    def test_save_session_false_creates_no_files(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        convert_met_to_epw(str(met_path), str(out_path), base_epw_path,
                            save_session=False, session_dir=str(session_dir))
        assert not list(session_dir.glob("*.pkl"))


class TestConvertMetToEpwAutoDetection:
    def test_metadata_not_on_expected_line_is_auto_detected(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13, extra_line_before_meta="Free-form comment, not metadata")
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is True
        epw = EPW(str(out_path))
        assert epw.location.latitude == pytest.approx(LAT)

    def test_data_start_not_on_expected_line_is_auto_detected(self, tmp_path, base_epw_path):
        met_path = tmp_path / "seville.met"
        _write_met_file(
            met_path, num_cols=13,
            extra_line_before_data="Mes Dia Hora Taire Tcielo Directa Difusa AbsHum RelHum Vviento DirViento Azimut Zenit",
        )
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is True
        epw = EPW(str(out_path))
        assert len(list(epw.dry_bulb_temperature.values)) == 8760


class TestConvertMetToEpwErrorHandling:
    def test_invalid_base_epw_returns_false(self, tmp_path, capsys):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), "does_not_exist.epw", save_session=False)
        assert ok is False
        assert "Error loading template" in capsys.readouterr().out

    def test_met_file_not_found_returns_false(self, tmp_path, base_epw_path):
        out_path = tmp_path / "out.epw"
        ok = convert_met_to_epw("does_not_exist.met", str(out_path), base_epw_path, save_session=False)
        assert ok is False

    def test_met_file_too_short_returns_false(self, tmp_path, base_epw_path, capsys):
        met_path = tmp_path / "short.met"
        met_path.write_text("line1\nline2")
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is False
        assert "too short" in capsys.readouterr().out

    def test_no_valid_geographic_metadata_returns_false(self, tmp_path, base_epw_path, capsys):
        met_path = tmp_path / "no_meta.met"
        # Every candidate line has a single token, so header2 never reaches
        # the length-3 threshold needed to even attempt float(header2[0]);
        # this is what makes the function fail gracefully instead of raising.
        met_path.write_text("\n".join(["onlyoneword"] * 12))
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is False
        assert "No valid geographic metadata found" in capsys.readouterr().out

    def test_invalid_column_count_returns_false(self, tmp_path, base_epw_path, capsys):
        met_path = tmp_path / "bad_cols.met"
        lines = ["test_city 0.0", f"{LAT} {LON} {ELEV} 0.0"]
        # 10 columns: neither the 13- nor the 15-column variant.
        lines.append("1 1 1 15.0 5.0 100.0 50.0 0.008 60.0 3.0")
        met_path.write_text("\n".join(lines))
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is False
        assert "10 columns" in capsys.readouterr().out

    def test_malformed_data_block_returns_false(self, tmp_path, base_epw_path, capsys):
        met_path = tmp_path / "ragged.met"
        lines = ["test_city 0.0", f"{LAT} {LON} {ELEV} 0.0"]
        lines.append("1 1 1 15.0 5.0 100.0 50.0 0.008 60.0 3.0 180.0 90.0 45.0")
        # A ragged row with far more tokens than the first row confuses
        # pandas' tokenizer (inconsistent column count across rows).
        lines.append("1 1 2 " + " ".join(str(x) for x in range(30)))
        met_path.write_text("\n".join(lines))
        out_path = tmp_path / "out.epw"

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is False
        assert "Error processing MET data" in capsys.readouterr().out

    def test_save_error_returns_false(self, tmp_path, base_epw_path, monkeypatch, capsys):
        met_path = tmp_path / "seville.met"
        _write_met_file(met_path, num_cols=13)
        out_path = tmp_path / "out.epw"

        # The failure is forced here instead of relying on ladybug's path
        # handling: passing a directory as the output path used to make
        # EPW.save() raise, but ladybug-core 0.44.61 normalises such a path and
        # writes the file anyway (the test passed on the locally pinned 0.44.42
        # and failed on every CI job, which resolves the newest release). What
        # this test must cover is *our* error handling, so the third-party call
        # is patched to raise deterministically.
        def _failing_save(self, *args, **kwargs):
            raise OSError("simulated save failure")

        monkeypatch.setattr(EPW, "save", _failing_save)

        ok = convert_met_to_epw(str(met_path), str(out_path), base_epw_path, save_session=False)
        assert ok is False
        assert "Error saving EPW" in capsys.readouterr().out
        assert not out_path.exists()


class TestConvertEpwToMet:
    def test_creates_met_file_with_expected_header_and_shape(self, tmp_path, base_epw_path):
        met_out = tmp_path / "roundtrip.met"
        ok = convert_epw_to_met(base_epw_path, str(met_out))
        assert ok is True
        assert met_out.exists()

        lines = met_out.read_text().splitlines()
        # Header: filename + tz*15 on line 1, lat/lon/elev/0.0 on line 2.
        assert os.path.basename(str(met_out)) in lines[0]
        header2 = lines[1].split()
        assert float(header2[0]) == pytest.approx(LAT, abs=0.01)
        assert float(header2[1]) == pytest.approx(LON, abs=0.01)
        # Exactly 8760 data rows follow the 2-line header.
        assert len(lines) - 2 == 8760
        first_row = lines[2].split()
        assert first_row[0] == "1" and first_row[1] == "1" and first_row[2] == "1"

    def test_invalid_epw_path_returns_false(self, tmp_path, capsys):
        ok = convert_epw_to_met("does_not_exist.epw", str(tmp_path / "out.met"))
        assert ok is False
        assert "Error reading EPW" in capsys.readouterr().out

    def test_write_error_returns_false(self, tmp_path, base_epw_path, capsys):
        # A directory instead of a file path: open(met_path, 'w') must fail.
        ok = convert_epw_to_met(base_epw_path, str(tmp_path))
        assert ok is False
        assert "Error writing MET" in capsys.readouterr().out

    def test_roundtrip_met_to_epw_to_met_preserves_plausible_values(self, tmp_path, base_epw_path):
        met_path = tmp_path / "original.met"
        _write_met_file(met_path, num_cols=13)
        epw_path = tmp_path / "converted.epw"
        convert_met_to_epw(str(met_path), str(epw_path), base_epw_path, save_session=False)

        met_roundtrip = tmp_path / "roundtrip.met"
        ok = convert_epw_to_met(str(epw_path), str(met_roundtrip))
        assert ok is True

        lines = met_roundtrip.read_text().splitlines()
        assert len(lines) - 2 == 8760
        first_data_values = lines[2].split()
        # Taire (dry-bulb) round-trips back to the original constant 15.0 input.
        assert float(first_data_values[3]) == pytest.approx(15.0, abs=0.5)



