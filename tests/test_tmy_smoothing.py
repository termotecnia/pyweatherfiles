# -*- coding: utf-8 -*-
"""
tests/test_tmy_smoothing.py
===========================

Tests for **Step 7** (month-junction smoothing) of
:mod:`pyweatherfiles.tmy._assembly_smoothing`, i.e. ``_apply_smoothing`` /
``sandia_step_7_smooth_junctions``.

Historically ``s_factor`` defaulted to ``0.0``, which is *exact interpolation*
in ``scipy.interpolate.UnivariateSpline``: Step 7 ran but was a numerical
no-op (``tmy_final == tmy_raw``), and nothing in the suite noticed. The
default is now ``'auto'``, a variance-normalized (hence unit-invariant)
smoothing factor: ``s = auto_s_strength * n * var(y)``. These tests pin down
both behaviours, the per-junction ``smoothing_config`` overrides, the
argument validation and the fact that GHI/DNI are never touched.
"""

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles import TMYGenerator

YEARS = list(range(2015, 2021))  # 6 synthetic years -> 5 FS candidates per month
SMOOTHED_COLS = ["T_air", "T_dew", "Wind_speed"]


def _make_synthetic_hourly_csv(path, years=YEARS, seed=7):
    """Synthetic hourly weather with a realistic diurnal swing (so that the
    smoothing has some actual structure to preserve) and a different random
    offset per year (so that consecutive TMY months do show junction jumps)."""
    rng = np.random.default_rng(seed)
    frames = []
    for i, year in enumerate(years):
        idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
        doy = idx.dayofyear.values.astype(float)
        hod = idx.hour.values.astype(float)

        seasonal = 15.0 - 10.0 * np.cos(2 * np.pi * (doy - 15) / 365.0)
        diurnal = 5.0 * np.sin(2 * np.pi * (hod - 9) / 24.0)
        t_air = seasonal + diurnal + (i - len(years) / 2.0) * 0.8 + rng.normal(0, 1.0, len(idx))
        t_dew = t_air - 5.0 - np.abs(rng.normal(0, 0.5, len(idx)))
        wind = np.clip(2.0 + rng.normal(0, 0.8, len(idx)), 0, None)

        daylight = np.clip(np.sin(np.pi * (hod - 6) / 12.0), 0, None)
        ghi = np.clip(daylight * (500 + 300 * -np.cos(2 * np.pi * (doy - 15) / 365.0))
                      + rng.normal(0, 5, len(idx)), 0, None)

        frames.append(pd.DataFrame({"time": idx, "T_air": t_air, "T_dew": t_dew,
                                    "Wind_speed": wind, "GHI": ghi}))

    pd.concat(frames, ignore_index=True).to_csv(path, index=False)
    return str(path)


@pytest.fixture(scope="module")
def tmy(tmp_path_factory):
    """A fully generated TMYGenerator (default Step 7 settings). Module-scoped:
    the full pipeline is expensive, and the tests below only re-run Step 7,
    which is cheap and fully re-entrant."""
    tmp_path = tmp_path_factory.mktemp("tmy_smoothing")
    csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv")
    gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly",
                       save_session=False, save_validation_dfs=False)
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    return gen


def _changed_hours(gen, col, tol=1e-6):
    return (gen.tmy_final[col] - gen.tmy_raw[col]).abs() > tol


def _junction_jumps(df, col):
    """|first hour of month m+1 - last hour of month m| for the 11 junctions."""
    return np.array([
        abs(df[df.index.month == m + 1][col].iloc[0] - df[df.index.month == m][col].iloc[-1])
        for m in range(1, 12)
    ])


class TestDefaultAutoSmoothing:
    def test_default_actually_modifies_the_tmy(self, tmy):
        tmy.sandia_step_7_smooth_junctions()  # defaults: hours=6, s_factor='auto'
        for col in SMOOTHED_COLS:
            assert _changed_hours(tmy, col).sum() > 0, f"{col} was not smoothed at all"

    def test_only_the_junction_windows_change(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        changed = _changed_hours(tmy, "T_air")
        # 11 junctions x (6 h before + 6 h after) is the hard upper bound
        assert 0 < changed.sum() <= 11 * 12
        for ts in tmy.tmy_final.index[changed]:
            # every changed hour must sit within 6 h of a month boundary
            assert ts.day in (1, 28, 29, 30, 31), f"{ts} is not near a month junction"

    def test_reduces_the_junction_discontinuities(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        raw_jumps = _junction_jumps(tmy.tmy_raw, "T_air")
        smoothed_jumps = _junction_jumps(tmy.tmy_final, "T_air")
        assert smoothed_jumps.mean() < raw_jumps.mean()

    def test_radiation_is_never_touched(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        for col in ("GHI", "DNI"):
            if col in tmy.tmy_final.columns:
                assert (tmy.tmy_final[col] == tmy.tmy_raw[col]).all()

    def test_annual_mean_is_preserved(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        assert tmy.tmy_final["T_air"].mean() == pytest.approx(tmy.tmy_raw["T_air"].mean(), abs=0.05)

    def test_stores_the_parameters_actually_used(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        cfg = tmy.smoothing_config[1]
        assert cfg["hours_before"] == 6 and cfg["hours_after"] == 6
        assert cfg["s_factor"] == "auto"
        assert cfg["auto_s_strength"] == TMYGenerator.AUTO_S_STRENGTH
        # the numeric s computed per variable is recorded for auditing
        assert set(cfg["s_factor_auto"]) >= {"T_air", "T_dew"}
        assert all(v > 0 for v in cfg["s_factor_auto"].values())

    def test_stronger_strength_smooths_more(self, tmy):
        tmy.sandia_step_7_smooth_junctions(auto_s_strength=0.02)
        weak = (tmy.tmy_final["T_air"] - tmy.tmy_raw["T_air"]).abs().max()
        tmy.sandia_step_7_smooth_junctions(auto_s_strength=0.10)
        strong = (tmy.tmy_final["T_air"] - tmy.tmy_raw["T_air"]).abs().max()
        assert strong > weak
        tmy.sandia_step_7_smooth_junctions()  # restore defaults for other tests

    def test_auto_is_case_insensitive(self, tmy):
        tmy.sandia_step_7_smooth_junctions(s_factor="AUTO")
        assert _changed_hours(tmy, "T_air").sum() > 0


class TestLegacyAndExplicitFactors:
    def test_zero_factor_is_still_an_exact_no_op(self, tmy, capsys):
        tmy.sandia_step_7_smooth_junctions(s_factor=0.0)
        for col in SMOOTHED_COLS:
            assert np.allclose(tmy.tmy_final[col].values, tmy.tmy_raw[col].values, atol=1e-9)
        assert "exact spline interpolation" in capsys.readouterr().out

    def test_explicit_positive_factor_smooths(self, tmy):
        tmy.sandia_step_7_smooth_junctions(s_factor=500.0)
        assert _changed_hours(tmy, "T_air").sum() > 0
        assert tmy.smoothing_config[1]["s_factor"] == 500.0
        # an explicit numeric s is not recorded as an "auto" value
        assert "s_factor_auto" not in tmy.smoothing_config[1]

    def test_none_uses_scipy_criterion(self, tmy):
        tmy.sandia_step_7_smooth_junctions(s_factor=None)
        assert _changed_hours(tmy, "T_air").sum() > 0
        # SciPy's documented default is s = n (number of fitted points)
        assert tmy.smoothing_config[1]["s_factor_auto"]["T_air"] > 1000

    def test_unknown_string_factor_raises(self, tmy):
        with pytest.raises(ValueError, match="Unknown s_factor"):
            tmy.sandia_step_7_smooth_junctions(s_factor="strong")

    def test_negative_auto_strength_raises(self, tmy):
        with pytest.raises(ValueError, match="auto_s_strength must be >= 0"):
            tmy.sandia_step_7_smooth_junctions(auto_s_strength=-0.5)


class TestSmoothingConfig:
    def test_per_junction_overrides_are_honoured(self, tmy):
        tmy.sandia_step_7_smooth_junctions(
            smoothing_config={1: {"hours_before": 12, "hours_after": 3},
                              7: {"s_factor": 0.0}}
        )
        cfg = tmy.smoothing_config
        assert cfg[1]["hours_before"] == 12 and cfg[1]["hours_after"] == 3
        assert cfg[7]["s_factor"] == 0.0
        # junction 7 (July->August) must be untouched, junction 1 must not
        changed = _changed_hours(tmy, "T_air")
        jan_feb = changed[(changed.index.month == 2) & (changed.index.day == 1)].sum()
        jul_aug = changed[(changed.index.month == 8) & (changed.index.day == 1)].sum()
        assert jan_feb == 3          # only 3 hours after the junction
        assert jul_aug == 0          # s_factor=0.0 -> exact interpolation
        tmy.sandia_step_7_smooth_junctions()  # restore defaults

    def test_hours_key_sets_both_sides(self, tmy):
        tmy.sandia_step_7_smooth_junctions(smoothing_config={2: {"hours": 4}})
        cfg = tmy.smoothing_config[2]
        assert cfg["hours_before"] == 4 and cfg["hours_after"] == 4
        tmy.sandia_step_7_smooth_junctions()


class TestGenerateTmyForwarding:
    def test_generate_tmy_forwards_smoothing_arguments(self, tmp_path):
        csv_path = _make_synthetic_hourly_csv(tmp_path / "weather.csv", seed=11)
        gen = TMYGenerator(file_path=csv_path, cdf_method="daily", data_frequency="hourly",
                           save_session=False, save_validation_dfs=False)
        gen.generate_tmy(smoothing_hours=3, smoothing_s_factor=0.0)
        assert gen.smoothing_config[1]["hours_before"] == 3
        assert gen.smoothing_config[1]["s_factor"] == 0.0
        assert np.allclose(gen.tmy_final["T_air"].values, gen.tmy_raw["T_air"].values, atol=1e-9)

    def test_regeneration_reuses_the_same_smoothing_settings(self, tmy):
        tmy.sandia_step_7_smooth_junctions(hours=4, s_factor=0.0)
        assert tmy._last_smoothing_kwargs["hours"] == 4
        assert tmy._last_smoothing_kwargs["s_factor"] == 0.0
        # correct_selection_by_temperature(regenerate=True) re-smooths through
        # _apply_smoothing(**_last_smoothing_kwargs); emulate that call here.
        tmy._create_raw_tmy()
        tmy._apply_smoothing(**tmy._last_smoothing_kwargs)
        assert tmy.smoothing_config[1]["hours_before"] == 4
        assert np.allclose(tmy.tmy_final["T_air"].values, tmy.tmy_raw["T_air"].values, atol=1e-9)
        tmy.sandia_step_7_smooth_junctions()  # restore defaults


class TestPlottingReflectsAutoFactor:
    def test_title_shows_the_computed_auto_factor(self, tmy):
        tmy.sandia_step_7_smooth_junctions()
        tmy.plot_smoothing_comparison([("T_air", 1)], save_figure_data=True)
        key = next(k for k in tmy.figures_data if k.startswith("Smoothing"))
        title = tmy.figures_data[key]["fig"].axes[0].get_title()
        assert "(auto)" in title

