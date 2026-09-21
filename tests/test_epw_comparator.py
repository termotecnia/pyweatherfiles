# -*- coding: utf-8 -*-
"""
tests/test_epw_comparator.py
===============================

Tests for :mod:`pyweatherfiles.epw_comparator` (0% test coverage before this
file — see ``INFORME_REVISION_GENERAL.md`` §6, Fase 2 continuation).

Covers all 4 public functions against fully synthetic EPW fixtures built
with ``ladybug.epw.EPW.from_missing_values()``:

- :func:`explore_epw_structure`
- :func:`compare_epw_files`
- :func:`create_comparison_dataframe`
- :func:`create_comparison_hourly_dataframe`

Also includes an explicit regression test for a real bug found and fixed
while writing this file: :func:`create_comparison_dataframe`'s internal
``get_header_name()`` only looked for ``header['name']``, but the installed
``ladybug-core`` version nests the variable name one level deeper, under
``header['data_type']['name']`` — this made the function silently return a
**completely empty** DataFrame (0 rows, 0 columns) for every call, and also
prevented the time index from being built even after that fix, because the
lookup for the ``'year'``/``'month'``/``'day'``/``'hour'`` columns was
case-sensitive while the real column names are capitalised
(``'Year'``/``'Month'``/``'Day'``/``'Hour'``). Both are now fixed.

Requires the optional ``tabulate`` dependency (extra ``comparator``), which
:mod:`pyweatherfiles.epw_comparator` raises ``ImportError`` for at import
time; the whole module is skipped automatically if it is not installed, so a
minimal environment reports a skip instead of aborting collection.
"""

import pandas as pd
import pytest
from ladybug.epw import EPW
from ladybug.location import Location

pytest.importorskip("tabulate")

from pyweatherfiles import epw_comparator  # noqa: E402

FIELDS = [
    "dry_bulb_temperature", "dew_point_temperature", "relative_humidity",
    "atmospheric_station_pressure", "direct_normal_radiation",
    "diffuse_horizontal_radiation", "horizontal_infrared_radiation_intensity",
    "wind_speed", "wind_direction",
]


def _write_synthetic_epw(path, city="TestCity", temp=20.0):
    """Builds a fully synthetic EPW with deterministic, constant values for
    every field used by :mod:`epw_comparator`, so comparisons between two
    such files have known, exact expected results."""
    epw = EPW.from_missing_values(is_leap_year=False)
    epw.location = Location(city=city, latitude=37.0, longitude=-5.0, time_zone=1.0, elevation=10.0)
    epw.comments_1 = f"Synthetic base for {city}"
    epw.comments_2 = "Generated for tests"
    epw.dry_bulb_temperature.values = [temp] * 8760
    epw.dew_point_temperature.values = [temp - 5.0] * 8760
    epw.relative_humidity.values = [60] * 8760
    epw.atmospheric_station_pressure.values = [101325] * 8760
    epw.direct_normal_radiation.values = [400] * 8760
    epw.diffuse_horizontal_radiation.values = [100] * 8760
    epw.horizontal_infrared_radiation_intensity.values = [350] * 8760
    epw.wind_speed.values = [3.0] * 8760
    epw.wind_direction.values = [180] * 8760
    epw.save(str(path))
    return str(path)


@pytest.fixture
def base_and_generated(tmp_path):
    """A pair of synthetic EPWs with a known, deterministic +5 degC dry-bulb
    temperature offset between 'base' and 'generated'."""
    base = _write_synthetic_epw(tmp_path / "base.epw", city="Seville", temp=15.0)
    generated = _write_synthetic_epw(tmp_path / "generated.epw", city="Seville", temp=20.0)
    return base, generated


class TestExploreEpwStructure:
    def test_runs_without_error_on_valid_epw(self, base_and_generated, capsys):
        base, _ = base_and_generated
        epw_comparator.explore_epw_structure(base)
        captured = capsys.readouterr()
        assert "Exploring EPW File Structure" in captured.out
        assert "Exploration Finished" in captured.out
        assert ".to_dict() executed successfully" in captured.out

    def test_handles_missing_file_gracefully(self, capsys):
        epw_comparator.explore_epw_structure("does_not_exist_at_all.epw")
        captured = capsys.readouterr()
        # EPW() lazily loads the file (the constructor itself never raises),
        # so the failure actually surfaces at the .to_dict() call, still
        # handled gracefully (no unhandled exception propagates).
        assert ".to_dict() failed with error" in captured.out


class TestCompareEpwFiles:
    def test_prints_console_report_in_english(self, base_and_generated, capsys):
        base, generated = base_and_generated
        epw_comparator.compare_epw_files(base, generated)
        captured = capsys.readouterr()

        assert "Starting EPW File Comparison" in captured.out
        assert "Metadata Comparison" in captured.out
        assert "Statistical Summary of the Difference" in captured.out
        assert "Comparison Finished" in captured.out
        assert "dry_bulb_temperature" in captured.out
        # No leftover Spanish diagnostic text (Fase 6 language convention).
        assert "Comparaci" not in captured.out

    def test_handles_missing_file_gracefully(self, capsys):
        epw_comparator.compare_epw_files("missing_base.epw", "missing_gen.epw")
        captured = capsys.readouterr()
        # ladybug-core raises a generic AssertionError (not FileNotFoundError)
        # for a missing file, caught by the function's generic except clause.
        assert "Error loading the EPW files with Ladybug" in captured.out


class TestCreateComparisonDataframe:
    """Also serves as the regression test for the get_header_name() bug
    described in the module docstring above."""

    def test_returns_expected_columns_and_values(self, base_and_generated):
        base, generated = base_and_generated
        df = epw_comparator.create_comparison_dataframe(base, generated)

        # Regression check: this used to return an entirely empty (0, 0)
        # DataFrame due to get_header_name() not finding any column names.
        assert not df.empty
        assert len(df) == 8760

        assert "TempBulboSeco_Base" in df.columns
        assert "TempBulboSeco_Generado" in df.columns
        assert df["TempBulboSeco_Base"].iloc[0] == pytest.approx(15.0)
        assert df["TempBulboSeco_Generado"].iloc[0] == pytest.approx(20.0)

        # All 9 mapped variables should produce a _Base/_Generado pair.
        assert len(df.columns) == 18

    def test_time_index_is_built_not_numeric_fallback(self, base_and_generated, capsys):
        base, generated = base_and_generated
        df = epw_comparator.create_comparison_dataframe(base, generated)
        captured = capsys.readouterr()

        # Regression check: the fallback warning should NOT fire now that
        # the case-insensitive year/month/day/hour lookup is fixed.
        assert "Could not create the exact time index" not in captured.out
        assert df.index.name == "Timestamp"
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_returns_empty_dataframe_on_missing_file(self, capsys):
        df = epw_comparator.create_comparison_dataframe("missing_base.epw", "missing_gen.epw")
        assert df.empty
        captured = capsys.readouterr()
        # EPW() lazily loads the file, so the failure surfaces at the
        # .to_dict() call rather than at construction time.
        assert "Error processing Ladybug dictionaries" in captured.out


class TestCreateComparisonHourlyDataframe:
    def test_returns_expected_columns_and_shape(self, base_and_generated):
        base, generated = base_and_generated
        df = epw_comparator.create_comparison_hourly_dataframe(base, generated, save_session=False)

        assert len(df) == 8760
        assert "Base_DryBulbTemp" in df.columns
        assert "Generated_DryBulbTemp" in df.columns
        assert df["Base_DryBulbTemp"].iloc[0] == pytest.approx(15.0)
        assert df["Generated_DryBulbTemp"].iloc[0] == pytest.approx(20.0)

    def test_every_epw_field_gets_a_base_and_generated_column(self, base_and_generated):
        base, generated = base_and_generated
        df = epw_comparator.create_comparison_hourly_dataframe(base, generated, save_session=False)

        # 35 official EPW data-dictionary fields -> 70 columns total.
        assert len(df.columns) == 70
        assert all(c.startswith("Base_") or c.startswith("Generated_") for c in df.columns)

    def test_returns_empty_dataframe_on_missing_file(self):
        df = epw_comparator.create_comparison_hourly_dataframe(
            "missing_base.epw", "missing_gen.epw", save_session=False
        )
        assert df.empty

    def test_save_session_creates_session_files(self, base_and_generated, tmp_path):
        base, generated = base_and_generated
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        epw_comparator.create_comparison_hourly_dataframe(
            base, generated, save_session=True, session_dir=str(session_dir)
        )

        assert list(session_dir.glob("*.pkl"))
        assert list(session_dir.glob("*.json"))

    def test_save_session_false_creates_no_files(self, base_and_generated, tmp_path):
        base, generated = base_and_generated
        session_dir = tmp_path / "sessions_off"
        session_dir.mkdir()

        epw_comparator.create_comparison_hourly_dataframe(
            base, generated, save_session=False, session_dir=str(session_dir)
        )

        assert not list(session_dir.glob("*.pkl"))




