# -*- coding: utf-8 -*-
"""
climate_evolution_trend.py
===========================

Section 3.1 of the manuscript ("The climate in Spain: evolution and trend"):
analyses the 20-year historical EPW series (``longterm_epw/``) for the five
study locations (Granada, León, Madrid, Málaga, Seville) and produces the
three headline indicators agreed between Daniel (D) and Rafa (R):

    1. Heating degree-hours,  T_base = 20 degC, all day (0-24h)
    2. Cooling degree-hours,  T_base = 25 degC, all day (0-24h)
    3. Night cooling potential (NCDH), T_base = 25 degC, night window
       (00:00-08:00, inclusive), restricted to summer months (July-
       September) -- how many degrees the outdoor air is *still below*
       the comfort/cooling threshold during the night (deficit, 25 - T),
       NOT how far above it (excess, T - 25): a proxy for how much passive
       night ventilation could still cool the building down, evaluated
       only in the months when overheating risk (and therefore night
       ventilation) actually matters.

As a bonus (Rafa's open question -- "no se si la irradiancia solar anual ha
aumentado o si se mantiene mas o menos uniforme"), annual GHI is also
extracted from the same EPWs and plotted/reported separately.

Run from the repository root:

    python analysis_scripts/climate_evolution_trend.py

Outputs (written to ``analysis_scripts/``):
    - climate_trend_variables.csv         (long-format table, one row per city-year)
    - climate_trend_summary.txt           (trend statistics per city and pooled)
    - fig3_climate_trend_dh.png           (3-panel figure: HDH20 / CDH25 / night CDH25 0-8h)
    - fig3a_heating_dh_20.png             (panel a, standalone)
    - fig3b_cooling_dh_25.png             (panel b, standalone)
    - fig3c_night_cooling_potential.png   (panel c, standalone -- NCDH,
      Jul-Sep, 00:00-08:00)
    - figS1_ghi_annual_trend.png          (bonus: annual GHI trend, all cities)

Author: Daniel Sanchez-Garcia
"""

import contextlib
import glob
import io
import os
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from pyweatherfiles.degree_hours import DegreeHoursCalculator

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
EPW_DIR = os.path.join(REPO_ROOT, 'longterm_epw')
OLD_CSV = os.path.join(REPO_ROOT, 'dh_recalculated_city_year.csv')

OUT_CSV = os.path.join(SCRIPT_DIR, 'climate_trend_variables.csv')
OUT_SUMMARY = os.path.join(SCRIPT_DIR, 'climate_trend_summary.txt')
OUT_FIG_COMBINED = os.path.join(SCRIPT_DIR, 'fig3_climate_trend_dh.png')
OUT_FIG_GHI = os.path.join(SCRIPT_DIR, 'figS1_ghi_annual_trend.png')

# Setpoints agreed with Rafa: heating base 20 degC, cooling/night base 25 degC
SETPOINTS = {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}
NIGHT_HOURS = list(range(0, 9))  # 00:00-08:00, inclusive (9 hourly values)
NIGHT_SUMMER_MONTHS = [7, 8, 9]  # July-September, inclusive

CITY_LABELS = {
    'granada': 'Granada',
    'leon': 'León',
    'madrid': 'Madrid',
    'malaga': 'Málaga',
    'seville': 'Seville',
}
CITY_COLORS = {
    'granada': 'tab:orange',
    'leon': 'tab:green',
    'madrid': 'tab:red',
    'malaga': 'tab:purple',
    'seville': 'tab:blue',
}
CITY_ORDER = ['granada', 'leon', 'madrid', 'malaga', 'seville']

# 'leon' only has data from 2015 onwards (colder baseline than the other four
# cities), so a naive "mean across all available cities per year" trend is
# confounded by a composition change in 2015 (Simpson's-paradox-like effect).
# BALANCED_CITIES restricts the robustness trend line to the four cities
# present throughout the whole 2005-2025 period.
BALANCED_CITIES = ['granada', 'madrid', 'malaga', 'seville']


# =============================================================================
# Step 1 -- discover EPW files
# =============================================================================

def discover_epw_files(epw_dir):
    """Return {city: {year: path}} parsed from '<city>_<year>.epw' filenames."""
    pattern = re.compile(r'^([a-zA-Z]+)_(\d{4})\.epw$')
    found = {}
    for path in sorted(glob.glob(os.path.join(epw_dir, '*.epw'))):
        fname = os.path.basename(path)
        m = pattern.match(fname)
        if not m:
            continue
        city, year = m.group(1).lower(), int(m.group(2))
        found.setdefault(city, {})[year] = path
    return found


# =============================================================================
# Step 2 -- per city-year metrics
# =============================================================================

def compute_city_year_metrics(epw_path, year):
    """
    Compute the 3 headline degree-hour indicators + annual GHI for one EPW.

    Returns
    -------
    dict with keys: heating_dh_20_allday, cooling_dh_25_allday,
    night_cdh_25_0_8h, ghi_annual_kwh_m2
    """
    with contextlib.redirect_stdout(io.StringIO()):  # silence verbose [INFO] prints
        calc = DegreeHoursCalculator(epw_path, year=year)

        res_allday = calc.calculate(
            SETPOINTS, frequency=['yearly'], mode='both', save_session=False,
        )['yearly']

        res_night = calc.calculate(
            SETPOINTS, frequency=['yearly'], mode='cooling',
            hours=NIGHT_HOURS, months=NIGHT_SUMMER_MONTHS,
            invert_cooling=True,  # cooling POTENTIAL (25 - T), not excess (T - 25)
            save_session=False,
        )['yearly']

        ghi_wh_m2 = calc.epw_data['global_horizontal_radiation'].sum() \
            if 'global_horizontal_radiation' in calc.epw_data.columns else np.nan

    return {
        'heating_dh_20_allday': float(res_allday['heating_dh'].sum()),
        'cooling_dh_25_allday': float(res_allday['cooling_dh'].sum()),
        'night_cooling_potential_25_jul_sep': float(res_night['cooling_dh'].sum()),
        'ghi_annual_kwh_m2': float(ghi_wh_m2) / 1000.0,
    }


def build_dataset():
    """Loop over every discovered EPW and assemble the long-format DataFrame."""
    files_by_city = discover_epw_files(EPW_DIR)
    rows = []
    for city in CITY_ORDER:
        years = files_by_city.get(city, {})
        for year in sorted(years):
            path = years[year]
            try:
                metrics = compute_city_year_metrics(path, year)
            except Exception as e:
                print(f"[WARNING] Skipping {city} {year}: {e}")
                continue
            row = {'city': city, 'year': year, **metrics}
            rows.append(row)
            print(
                f"[OK] {city:8s} {year} -> "
                f"HDH20={metrics['heating_dh_20_allday']:9.1f}  "
                f"CDH25={metrics['cooling_dh_25_allday']:8.1f}  "
                f"NCDH25(Jul-Sep,0-8h)={metrics['night_cooling_potential_25_jul_sep']:7.1f}  "
                f"GHI={metrics['ghi_annual_kwh_m2']:7.1f} kWh/m2"
            )
    df = pd.DataFrame(rows).sort_values(['city', 'year']).reset_index(drop=True)
    return df


# =============================================================================
# Step 3 -- cross-check against the pre-existing CSV (sanity check)
# =============================================================================

def validate_against_old_csv(df):
    if not os.path.exists(OLD_CSV):
        print("[VALIDATION] No pre-existing dh_recalculated_city_year.csv found; skipping.")
        return
    old = pd.read_csv(OLD_CSV)
    merged = df.merge(
        old, on=['city', 'year'], suffixes=('_new', '_old'), how='inner'
    )
    if merged.empty:
        print("[VALIDATION] No overlapping city-year rows to compare.")
        return
    diff_h = (merged['heating_dh_20_allday'] - merged['heating_dh_all_day']).abs()
    diff_c = (merged['cooling_dh_25_allday'] - merged['cooling_dh_all_day']).abs()
    print(
        f"[VALIDATION] Compared {len(merged)} city-year rows against "
        f"dh_recalculated_city_year.csv:"
    )
    print(f"    max |HDH_new - HDH_old| = {diff_h.max():.3f}")
    print(f"    max |CDH_new - CDH_old| = {diff_c.max():.3f}")
    if diff_h.max() < 1.0 and diff_c.max() < 1.0:
        print("    -> OK: matches exactly (same constant 20/25 degC, all-day setpoints).")
    else:
        print(
            "    -> NOTE: values differ from dh_recalculated_city_year.csv. This is "
            "EXPECTED: this script uses simple constant setpoints (20/25 degC, 24h/day), "
            "the classic climate-only HDH/CDH definition requested for Section 3.1. The "
            "pre-existing CSV was almost certainly built with building-specific IDF "
            "schedules (setback temperatures / HVAC availability hours), which is a "
            "different indicator relevant to Section 3.3 (building demand), not to the "
            "pure-climate trend analysis here."
        )


# =============================================================================
# Step 4 -- trend statistics
# =============================================================================

def trend_stats(df, value_col):
    """Linear regression (year -> value), pooled across all cities and per city."""
    lines = []
    x = df['year'].values.astype(float)
    y = df[value_col].values.astype(float)
    mask = ~np.isnan(y)
    res = stats.linregress(x[mask], y[mask])
    lines.append(
        f"  Pooled (all cities, all years, n={mask.sum()}): "
        f"slope={res.slope:+.2f} /yr, R2={res.rvalue**2:.3f}, p={res.pvalue:.4f}"
        + ("  [significant, p<0.05]" if res.pvalue < 0.05 else "  [not significant]")
    )
    for city in CITY_ORDER:
        sub = df[df['city'] == city]
        if len(sub) < 3:
            continue
        r = stats.linregress(sub['year'].values.astype(float), sub[value_col].values.astype(float))
        lines.append(
            f"    {CITY_LABELS[city]:8s} (n={len(sub):2d}): "
            f"slope={r.slope:+.2f} /yr, R2={r.rvalue**2:.3f}, p={r.pvalue:.4f}"
            + ("  [significant]" if r.pvalue < 0.05 else "")
        )
    # Trend on the across-city yearly mean (cleaner signal, removes city-level offset)
    yearly_mean = df.groupby('year')[value_col].mean()
    r_mean = stats.linregress(yearly_mean.index.values.astype(float), yearly_mean.values)
    lines.append(
        f"  Trend of the across-city YEARLY MEAN (all available cities/year): "
        f"slope={r_mean.slope:+.2f} /yr, R2={r_mean.rvalue**2:.3f}, p={r_mean.pvalue:.4f}"
        + ("  [significant]" if r_mean.pvalue < 0.05 else "  [not significant]")
    )
    # Robustness check: same yearly-mean trend restricted to the 4-city balanced
    # panel present throughout 2005-2025 (removes the 2015 'leon joins in' composition jump)
    bal = df[df['city'].isin(BALANCED_CITIES)]
    yearly_mean_bal = bal.groupby('year')[value_col].mean()
    r_bal = stats.linregress(yearly_mean_bal.index.values.astype(float), yearly_mean_bal.values)
    lines.append(
        f"  Trend of the YEARLY MEAN, balanced 4-city panel "
        f"({'/'.join(CITY_LABELS[c] for c in BALANCED_CITIES)}): "
        f"slope={r_bal.slope:+.2f} /yr, R2={r_bal.rvalue**2:.3f}, p={r_bal.pvalue:.4f}"
        + ("  [significant]" if r_bal.pvalue < 0.05 else "  [not significant]")
    )
    return "\n".join(lines)


# =============================================================================
# Step 5 -- plotting helpers
# =============================================================================

def _boxplot_panel(ax, df, value_col, ylabel, panel_label, title):
    years = sorted(df['year'].unique())
    data_by_year = [df.loc[df['year'] == y, value_col].dropna().values for y in years]

    bp = ax.boxplot(
        data_by_year, positions=years, widths=0.6, showfliers=False,
        patch_artist=True, manage_ticks=False,
        boxprops=dict(facecolor='0.85', edgecolor='0.3'),
        medianprops=dict(color='black', linewidth=1.3),
        whiskerprops=dict(color='0.3'), capprops=dict(color='0.3'),
    )

    # Overlay individual city points (small horizontal jitter per city)
    n_cities = len(CITY_ORDER)
    jitter_span = 0.5
    for i, city in enumerate(CITY_ORDER):
        offset = (i - (n_cities - 1) / 2) * (jitter_span / n_cities)
        sub = df[df['city'] == city]
        ax.scatter(
            sub['year'].values + offset, sub[value_col].values,
            s=22, color=CITY_COLORS[city], label=CITY_LABELS[city],
            alpha=0.85, zorder=3, edgecolors='white', linewidths=0.4,
        )

    # Trend line on the across-city yearly mean (all cities available that year)
    yearly_mean = df.groupby('year')[value_col].mean()
    r_mean = stats.linregress(yearly_mean.index.values.astype(float), yearly_mean.values)
    x_line = np.array([min(years), max(years)], dtype=float)
    ax.plot(
        x_line, r_mean.intercept + r_mean.slope * x_line,
        color='crimson', linestyle='--', linewidth=1.8, zorder=4,
        label=f"Trend, all cities: {r_mean.slope:+.1f}/yr (p={r_mean.pvalue:.3f})",
    )

    # Robustness trend line: 4-city balanced panel (excludes 'leon', which only
    # joins from 2015 and would otherwise bias the pooled mean from that year on)
    bal = df[df['city'].isin(BALANCED_CITIES)]
    yearly_mean_bal = bal.groupby('year')[value_col].mean()
    r_bal = stats.linregress(yearly_mean_bal.index.values.astype(float), yearly_mean_bal.values)
    x_line_bal = np.array([yearly_mean_bal.index.min(), yearly_mean_bal.index.max()], dtype=float)
    ax.plot(
        x_line_bal, r_bal.intercept + r_bal.slope * x_line_bal,
        color='navy', linestyle=':', linewidth=1.8, zorder=4,
        label=f"Trend, balanced 4-city panel: {r_bal.slope:+.1f}/yr (p={r_bal.pvalue:.3f})",
    )

    ax.set_ylabel(ylabel)
    ax.set_title(f"({panel_label}) {title}", loc='left', fontsize=11, fontweight='bold')
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_xlim(min(years) - 1, max(years) + 1)
    return r_mean


def make_combined_figure(df):
    fig, axes = plt.subplots(3, 1, figsize=(11, 13), sharex=True)

    r1 = _boxplot_panel(
        axes[0], df, 'heating_dh_20_allday',
        'HDH$_{20}$ (°C·h)', 'a',
        'Heating degree-hours (T$_{base}$ = 20 °C, 24 h)',
    )
    r2 = _boxplot_panel(
        axes[1], df, 'cooling_dh_25_allday',
        'CDH$_{25}$ (°C·h)', 'b',
        'Cooling degree-hours (T$_{base}$ = 25 °C, 24 h)',
    )
    r3 = _boxplot_panel(
        axes[2], df, 'night_cooling_potential_25_jul_sep',
        'NCDH$_{25}$ (°C·h)', 'c',
        'Night cooling potential (T$_{base}$ = 25 °C, 00:00-08:00 h, Jul-Sep)',
    )

    axes[-1].set_xlabel('Year')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc='upper center', ncol=4, frameon=False,
        bbox_to_anchor=(0.5, 1.05), fontsize=9,
    )
    fig.suptitle(
        'Evolution of the 20-year historical climate series (2005-2025): '
        'boxplots across cities per year, oldest to newest',
        y=1.1, fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(OUT_FIG_COMBINED, dpi=300, bbox_inches='tight')
    print(f"[FIGURE] Saved combined 3-panel figure -> {OUT_FIG_COMBINED}")

    # Standalone panels too (useful for individual figure placement in the manuscript)
    panel_specs = [
        ('heating_dh_20_allday', 'HDH$_{20}$ (°C·h)', 'a',
         'Heating degree-hours (T$_{base}$ = 20 °C, 24 h)', 'fig3a_heating_dh_20.png'),
        ('cooling_dh_25_allday', 'CDH$_{25}$ (°C·h)', 'b',
         'Cooling degree-hours (T$_{base}$ = 25 °C, 24 h)', 'fig3b_cooling_dh_25.png'),
        ('night_cooling_potential_25_jul_sep', 'NCDH$_{25}$ (°C·h)', 'c',
         'Night cooling potential (T$_{base}$ = 25 °C, 00:00-08:00 h, Jul-Sep)',
         'fig3c_night_cooling_potential.png'),
    ]
    for col, ylabel, label, title, fname in panel_specs:
        fig_i, ax_i = plt.subplots(figsize=(9, 5))
        _boxplot_panel(ax_i, df, col, ylabel, label, title)
        ax_i.set_xlabel('Year')
        ax_i.legend(loc='upper left', ncol=2, fontsize=7.5, frameon=True)
        fig_i.tight_layout()
        out_path = os.path.join(SCRIPT_DIR, fname)
        fig_i.savefig(out_path, dpi=300, bbox_inches='tight')
        plt.close(fig_i)
        print(f"[FIGURE] Saved standalone panel -> {out_path}")

    plt.close(fig)
    return r1, r2, r3


def make_ghi_figure(df):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    _boxplot_panel(
        ax, df, 'ghi_annual_kwh_m2',
        'Annual GHI (kWh/m²/yr)', 'S1',
        'Annual global horizontal irradiance -- has solar resource changed over time?',
    )
    ax.set_xlabel('Year')
    ax.legend(loc='upper left', ncol=3, fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(OUT_FIG_GHI, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"[FIGURE] Saved bonus GHI trend figure -> {OUT_FIG_GHI}")


# =============================================================================
# Main
# =============================================================================

def main():
    print(f"[INFO] Scanning EPW files in: {EPW_DIR}")
    df = build_dataset()
    if df.empty:
        raise RuntimeError("No EPW files could be processed in longterm_epw/.")

    df.to_csv(OUT_CSV, index=False)
    print(f"\n[INFO] Saved long-format dataset -> {OUT_CSV} ({len(df)} city-year rows)")

    validate_against_old_csv(df)

    print("\n[TREND] Heating degree-hours (T_base=20 degC, all day):")
    s1 = trend_stats(df, 'heating_dh_20_allday')
    print(s1)
    print("\n[TREND] Cooling degree-hours (T_base=25 degC, all day):")
    s2 = trend_stats(df, 'cooling_dh_25_allday')
    print(s2)
    print("\n[TREND] Night cooling potential indicator (T_base=25 degC, 00:00-08:00, Jul-Sep):")
    s3 = trend_stats(df, 'night_cooling_potential_25_jul_sep')
    print(s3)
    print("\n[TREND] Annual GHI (bonus check requested by Rafa):")
    s4 = trend_stats(df, 'ghi_annual_kwh_m2')
    print(s4)

    with open(OUT_SUMMARY, 'w', encoding='utf-8') as f:
        f.write("Climate evolution and trend -- summary statistics\n")
        f.write("=" * 60 + "\n\n")
        f.write("Heating degree-hours (T_base=20 degC, all day):\n" + s1 + "\n\n")
        f.write("Cooling degree-hours (T_base=25 degC, all day):\n" + s2 + "\n\n")
        f.write("Night cooling potential indicator (T_base=25 degC, 00:00-08:00, Jul-Sep):\n" + s3 + "\n\n")
        f.write("Annual GHI (bonus check):\n" + s4 + "\n")
    print(f"\n[INFO] Saved trend summary -> {OUT_SUMMARY}")

    make_combined_figure(df)
    make_ghi_figure(df)

    print("\n[DONE] Section 3.1 figures/tables generated successfully.")


if __name__ == '__main__':
    main()







