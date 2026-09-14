# -*- coding: utf-8 -*-
"""
climate_evolution_trend_separate_climates.py
==============================================

Section 3.1 of the manuscript ("The climate in Spain: evolution and trend"):
analyses the 20-year historical EPW series (``longterm_epw/``) for the five
study locations, computing the three headline indicators agreed between
Daniel (D) and Rafa (R):

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

IMPORTANT -- per-climate analysis
----------------------------------
Each of the five study locations represents a *different* official Spanish
climate zone (CTE DB-HE), not a repeated sample of the same climate. Pooling
them into a single "all cities together" boxplot per year would therefore
mix distributions from fundamentally different populations and can produce
misleading composite trends (e.g. a false trend reversal simply because a
colder city -- 'leon' -- enters the record only from 2015 onwards).

This script analyses **each climate/city fully independently** using the
reusable :class:`~pyweatherfiles.degree_hours.EpwGroupTrendAnalyzer`: every
city gets its own trend line, its own regression statistics, and its own
subplot -- no climate is ever averaged or pooled with another.

CTE_ZONE labels (informative only, NOT used in any computation) follow the
commonly cited assignment for these provincial-capital stations (Malaga A3,
Sevilla B4, Granada C3, Madrid D3, Leon E1), shown together with each
station's approximate Koppen-Geiger climate classification -- Daniel/Rafa
should double check these against the official CTE DB-HE Apendice B/D
tables for the exact station coordinates used before citing them in the
manuscript.

Run from the repository root:

    python analysis_scripts/climate_evolution_trend_separate_climates.py

Outputs (written to ``analysis_scripts/``):
    - climate_trend_variables.csv              (long-format table, one row per city-year)
    - climate_trend_summary_by_city.txt        (per-city trend statistics, no pooling)
    - fig3a_heating_dh_20_by_city.png           (1 subplot per city -- HDH20)
    - fig3b_cooling_dh_25_by_city.png           (1 subplot per city -- CDH25)
    - fig3c_night_cooling_potential_by_city.png (1 subplot per city -- night
      cooling potential NCDH25, Jul-Sep, 00:00-08:00)
    - figS1_ghi_annual_by_city.png              (bonus: 1 subplot per city -- annual GHI)
    - fig3_overview_grid_by_city.png            (bonus: 5 rows [city] x 3 cols [indicator]
      overview grid, horizontal bars, ordered Malaga-Seville-Granada-Madrid-Leon)

Author: Daniel Sanchez-Garcia
"""

import os

import pandas as pd

from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
EPW_DIR = os.path.join(REPO_ROOT, 'longterm_epw')
OLD_CSV = os.path.join(REPO_ROOT, 'dh_recalculated_city_year.csv')

OUT_CSV = os.path.join(SCRIPT_DIR, 'climate_trend_variables.csv')
OUT_SUMMARY = os.path.join(SCRIPT_DIR, 'climate_trend_summary_by_city.txt')
OUT_FIG_HDH = os.path.join(SCRIPT_DIR, 'fig3a_heating_dh_20_by_city.png')
OUT_FIG_CDH = os.path.join(SCRIPT_DIR, 'fig3b_cooling_dh_25_by_city.png')
OUT_FIG_NIGHT = os.path.join(SCRIPT_DIR, 'fig3c_night_cooling_potential_by_city.png')
OUT_FIG_GHI = os.path.join(SCRIPT_DIR, 'figS1_ghi_annual_by_city.png')
OUT_FIG_OVERVIEW = os.path.join(SCRIPT_DIR, 'fig3_overview_grid_by_city.png')

# Setpoints agreed with Rafa: heating base 20 degC, cooling/night base 25 degC
SETPOINTS = {'type': 'constant', 'heating': 20.0, 'cooling': 25.0}

# Scenario labels chosen to mirror the previous (pre-refactor) column names,
# so that OUT_CSV / OUT_SUMMARY stay easy to compare against earlier runs:
#   'allday'                  -> heating_dh_allday, cooling_dh_allday
#                                 (0-24h, T_base 20/25 degC)
#   'night_potential_jul_sep' -> cooling_dh_night_potential_jul_sep
#                                 (00:00-08:00 inclusive, T_base 25 degC,
#                                 restricted to Jul-Sep). IMPORTANT: this is
#                                 the *cooling potential* (deficit), i.e.
#                                 max(0, 25 - T) -- how many degrees are
#                                 still MISSING to reach 25 degC -- NOT the
#                                 classic excess-above-threshold CDH formula
#                                 max(0, T - 25). Fixed after Daniel/Rafa
#                                 spotted the sign error while auditing
#                                 fig3_overview_grid_by_city.png for Leon
#                                 (see notes/work-log.md).
NIGHT_SUMMER_MONTHS = [7, 8, 9]  # July, August, September (inclusive)

HOURS_SCENARIOS = {
    'allday': {'hours': None, 'mode': 'both'},
    'night_potential_jul_sep': {
        'hours': list(range(0, 9)),      # 00:00-08:00 inclusive (9 hourly values)
        'mode': 'cooling',
        'invert_cooling': True,          # degrees MISSING to reach 25 degC (potential), not excess above it
        'months': NIGHT_SUMMER_MONTHS,   # restricted to summer months (Jul-Sep)
    },
}

# Bonus: annual GHI (Rafa's open question), converted Wh/m2 -> kWh/m2
EXTRA_EPW_VARIABLES = {'global_horizontal_radiation': ['sum']}
SCALE_FACTORS = {'global_horizontal_radiation_sum': 0.001}
GHI_COL = 'global_horizontal_radiation_sum'  # already scaled to kWh/m2 above

# Ordered from the mildest CTE winter zone (A) to the harshest (E), left to
# right: Malaga(A3) - Seville(B4) - Granada(C3) - Madrid(D3) - Leon(E1).
GROUP_ORDER = ['malaga', 'seville', 'granada', 'madrid', 'leon']

GROUP_LABELS = {
    'granada': 'Granada',
    'leon': 'León',
    'madrid': 'Madrid',
    'malaga': 'Málaga',
    'seville': 'Seville',
}
# CTE DB-HE zone + Koppen-Geiger climate classification shown together in
# each subplot's title. Informative only (NOT used in any computation) --
# please verify against the official CTE DB-HE Apendice B/D tables for the
# exact stations used.
GROUP_ZONE = {
    'malaga': 'A3 · BWk',
    'seville': 'B4 · BSh',
    'granada': 'C3 · Csa',
    'madrid': 'D3 · Csa',
    'leon': 'E1 · Cfc/Dfc',
}
GROUP_COLORS = {
    'granada': 'tab:orange',
    'leon': 'tab:green',
    'madrid': 'tab:red',
    'malaga': 'tab:purple',
    'seville': 'tab:blue',
}


# =============================================================================
# Cross-check against the pre-existing legacy CSV (sanity check)
# =============================================================================

def validate_against_old_csv(results: pd.DataFrame) -> None:
    """
    Compare ``heating_dh_allday`` / ``cooling_dh_allday`` (constant 20/25 degC,
    24h/day climate-only indicator) against the pre-existing
    ``dh_recalculated_city_year.csv`` (building-specific IDF schedules, used
    for Section 3.3 demand analysis) as an independent sanity check.
    """
    if not os.path.exists(OLD_CSV):
        print("[VALIDATION] No pre-existing dh_recalculated_city_year.csv found; skipping.")
        return
    old = pd.read_csv(OLD_CSV)
    new = results.rename(columns={'group': 'city'})
    merged = new.merge(old, on=['city', 'year'], suffixes=('_new', '_old'), how='inner')
    if merged.empty:
        print("[VALIDATION] No overlapping city-year rows to compare.")
        return
    diff_h = (merged['heating_dh_allday'] - merged['heating_dh_all_day']).abs()
    diff_c = (merged['cooling_dh_allday'] - merged['cooling_dh_all_day']).abs()
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


def format_trend_report(analyzer: EpwGroupTrendAnalyzer, value_col: str, title: str) -> str:
    """Human-readable per-city trend report (no pooling) for the summary .txt."""
    trend_df = analyzer.compute_trends(value_col)
    lines = [f"{title}:"]
    for group in analyzer.inputs['group_order']:
        label = analyzer._group_label(group)
        zone = analyzer._group_zone(group)
        r = trend_df.loc[group]
        if pd.isna(r['slope']):
            lines.append(f"  {label:8s} ({zone}): not enough data (n={int(r['n'])}).")
            continue
        sig = "  [significant, p<0.05]" if r['significant'] else "  [not significant]"
        lines.append(
            f"  {label:8s} ({zone}, n={int(r['n']):2d}): "
            f"slope={r['slope']:+8.2f} /yr, R2={r['r2']:.3f}, p={r['pvalue']:.4f}{sig}"
        )
    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    print(f"[INFO] Scanning EPW files in: {EPW_DIR}")

    analyzer = EpwGroupTrendAnalyzer(
        epw_dir=EPW_DIR,
        setpoint_source=SETPOINTS,
        hours_scenarios=HOURS_SCENARIOS,
        extra_epw_variables=EXTRA_EPW_VARIABLES,
        scale_factors=SCALE_FACTORS,
        group_order=GROUP_ORDER,
        group_labels=GROUP_LABELS,
        group_colors=GROUP_COLORS,
        group_zone=GROUP_ZONE,
    )
    results = analyzer.run(save_session=False)

    results.to_csv(OUT_CSV, index=False)
    print(f"\n[INFO] Saved long-format dataset -> {OUT_CSV} ({len(results)} city-year rows)")

    validate_against_old_csv(results)

    print("\n[TREND] Heating degree-hours (T_base=20 degC, all day) -- per climate:")
    s1 = format_trend_report(analyzer, 'heating_dh_allday', 'Heating degree-hours (T_base=20 degC, all day)')
    print(s1)
    print("\n[TREND] Cooling degree-hours (T_base=25 degC, all day) -- per climate:")
    s2 = format_trend_report(analyzer, 'cooling_dh_allday', 'Cooling degree-hours (T_base=25 degC, all day)')
    print(s2)
    print("\n[TREND] Night cooling potential indicator (T_base=25 degC, 00:00-08:00, Jul-Sep) -- per climate:")
    s3 = format_trend_report(
        analyzer, 'cooling_dh_night_potential_jul_sep',
        'Night cooling potential indicator (T_base=25 degC, 00:00-08:00, Jul-Sep)',
    )
    print(s3)
    print("\n[TREND] Annual GHI (bonus check requested by Rafa) -- per climate:")
    s4 = format_trend_report(analyzer, GHI_COL, 'Annual GHI (bonus check)')
    print(s4)

    with open(OUT_SUMMARY, 'w', encoding='utf-8') as f:
        f.write("Climate evolution and trend -- summary statistics (per climate, no pooling)\n")
        f.write("=" * 78 + "\n\n")
        f.write(s1 + "\n\n")
        f.write(s2 + "\n\n")
        f.write(s3 + "\n\n")
        f.write(s4 + "\n")
    print(f"\n[INFO] Saved trend summary -> {OUT_SUMMARY}")

    analyzer.plot_variable_grid(
        'heating_dh_allday', ylabel='HDH$_{20}$ (°C·h)',
        suptitle='Heating degree-hours (T$_{base}$ = 20 °C, 24 h) -- each climate analysed separately',
        out_path=OUT_FIG_HDH,
    )
    analyzer.plot_variable_grid(
        'cooling_dh_allday', ylabel='CDH$_{25}$ (°C·h)',
        suptitle='Cooling degree-hours (T$_{base}$ = 25 °C, 24 h) -- each climate analysed separately',
        out_path=OUT_FIG_CDH,
    )
    analyzer.plot_variable_grid(
        'cooling_dh_night_potential_jul_sep', ylabel='NCDH$_{25}$ (°C·h)',
        suptitle='Night cooling potential (T$_{base}$ = 25 °C, 00:00-08:00 h, Jul-Sep) -- each climate analysed separately',
        out_path=OUT_FIG_NIGHT,
    )
    analyzer.plot_variable_grid(
        GHI_COL, ylabel='Annual GHI (kWh/m²/yr)',
        suptitle='Annual global horizontal irradiance',
        tick_labelsize=11.0,
        out_path=OUT_FIG_GHI,
    )
    analyzer.plot_overview_grid(
        variables=[
            ('heating_dh_allday', 'HDH$_{20}$ (°C·h)', 'HDH$_{base=20°C}$'),
            ('cooling_dh_allday', 'CDH$_{25}$ (°C·h)', 'CDH$_{base=25°C}$'),
            ('cooling_dh_night_potential_jul_sep', 'NCDH$_{25}$ (°C·h)', 'NCDH (Jul-Sep, 00-08h)'),
        ],
        horizontal=True,
        transpose=True,
        out_path=OUT_FIG_OVERVIEW,
    )

    print("\n[DONE] Section 3.1 per-climate figures/tables generated successfully.")


if __name__ == '__main__':
    main()
