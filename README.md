# pyweatherfiles

[![Documentation Status](https://readthedocs.org/projects/pyweatherfiles/badge/?version=latest)](https://pyweatherfiles.readthedocs.io/en/latest/?badge=latest)

**`pyweatherfiles`** is a Python package for comprehensive weather-file management aimed at building energy simulation: **Typical Meteorological Year (TMY)** generation, bidirectional format conversion (EPW, `.met`, hourly CSV/Excel series), **heating/cooling degree-hours** calculation, multi-year **climate trend analysis**, EPW file comparison, and gap-filling/cleaning of raw hourly series.

This document describes **the entire package in maximum technical detail**: all its modules, classes, functions, parameters and formulas — including those **not** used in the article's reference script (`generating epws seville.py`).

> 🇪🇸 Versión en español (misma documentación completa del paquete): [`README_ES.md`](README_ES.md).
> ℹ️ For the document focused **exclusively** on the real workflow used in the article (Seville case study: `HourlyEPWConverter` + `convert_met_to_epw` + `TMYGenerator`), see [`ARTICLE_CONTEXT_SEVILLA.md`](ARTICLE_CONTEXT_SEVILLA.md) (Spanish).

> Package author: Daniel Sánchez-García (University of Cádiz) — `daniel.sanchezgarcia@uca.es`

> 📘 **Full HTML documentation** (hosted on Read the Docs — API reference auto-generated from the source code, plus this same guide, browsable and searchable): **https://pyweatherfiles.readthedocs.io/**. Build it locally with `pip install -e ".[docs]"` and `dist_build_docs.bat` (see `docs/source/installation.md`).
> 📓 **Hands-on tutorial notebook** (runs end-to-end with data already bundled in this repo, no external downloads needed; also rendered directly in the online documentation): [`examples/tutorial_pyweatherfiles.ipynb`](examples/tutorial_pyweatherfiles.ipynb).

---

## Table of contents

1. [Overview and architecture](#1-overview-and-architecture)
2. [Installation and dependencies](#2-installation-and-dependencies)
3. [`tmy` — `TMYGenerator` (TMY generation, Sandia/TMY3 methodology)](#3-tmy--tmygenerator-tmy-generation-sandiatmy3-methodology)
4. [`hourly_epw_converter` — `HourlyEPWConverter` / `BatchHourlyEPWConverter`](#4-hourly_epw_converter--hourlyepwconverter--batchhourlyepwconverter)
5. [`met_epw_converter` — `convert_met_to_epw` / `convert_epw_to_met`](#5-met_epw_converter--convert_met_to_epw--convert_epw_to_met)
6. [`degree_hours` — `DegreeHoursCalculator` / `EpwBatchAnalyzer` / `EpwGroupTrendAnalyzer`](#6-degree_hours--degreehourscalculator--epwbatchanalyzer--epwgrouptrendanalyzer)
7. [`epw_trend_analyzer` — `EpwTrendAnalyzer`](#7-epw_trend_analyzer--epwtrendanalyzer)
8. [`epw_comparator` — EPW file comparison](#8-epw_comparator--epw-file-comparison)
9. [`climate_processor` — `ClimateProcessor` (hourly series cleaning/gap-filling)](#9-climate_processor--climateprocessor-hourly-series-cleaninggap-filling)
10. [`session_manager` — session persistence (cross-cutting)](#10-session_manager--session-persistence-cross-cutting)
11. [Complete dependencies by module](#11-complete-dependencies-by-module)
12. [Quick examples per module](#12-quick-examples-per-module)
13. [Design notes and general caveats](#13-design-notes-and-general-caveats)
14. [References](#14-references)
15. [License](#15-license)

---

## 1. Overview and architecture

### 1.1 What does each module solve?

| Module (`pyweatherfiles.*`) | Main classes / functions | Purpose |
|---|---|---|
| `tmy` | `TMYGenerator` | Generates a Typical Meteorological Year (TMY) from historical series, Sandia/TMY3 method in 7 steps |
| `hourly_epw_converter` | `HourlyEPWConverter`, `BatchHourlyEPWConverter` | Converts already-cleaned hourly series (CSV/Excel) into `.epw` files, one per year or in multi-city batch |
| `met_epw_converter` | `convert_met_to_epw`, `convert_epw_to_met` | Bidirectional conversion between the `.met` format (LIDER/CALENER-CTE) and `.epw` |
| `degree_hours` | `DegreeHoursCalculator`, `EpwBatchAnalyzer`, `EpwGroupTrendAnalyzer` | Heating/cooling degree-hours from an EPW + setpoints (IDF or dict); single-EPW, multi-EPW comparative, or whole-folder (classified by filename) degree-hour trend analysis |
| `epw_trend_analyzer` | `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig` | Multi-year climate trends (warming, heatwaves) over collections of annual EPWs |
| `epw_comparator` | `explore_epw_structure`, `compare_epw_files`, `create_comparison_dataframe`, `create_comparison_hourly_dataframe` | Structural/statistical/hourly comparison between two EPW files |
| `climate_processor` | `ClimateProcessor` | Cleaning, reindexing and gap-filling of raw hourly station series (pre-processing, upstream of `tmy`/`hourly_epw_converter`) |
| `session_manager` | `save_object_session`, `save_function_session`, `load_session` | Reproducible persistence (`.pkl` + `.json`) used across the rest of the modules |

### 1.2 Minimal public API (`pyweatherfiles/__init__.py`)

```python
from .tmy import TMYGenerator
from .degree_hours import DegreeHoursCalculator
from .epw_trend_analyzer import EpwTrendAnalyzer, TrendConfig, OutputConfig
```

The rest of the classes/functions (`hourly_epw_converter`, `met_epw_converter`, `epw_comparator`, `climate_processor`, `EpwBatchAnalyzer`, `session_manager`) are imported explicitly from their submodule, e.g. `from pyweatherfiles import hourly_epw_converter`.

### 1.3 Typical end-to-end data flow

```
Station / raw data source (gaps, noise)
        │
        ▼
 ClimateProcessor            (cleaning, gap-filling, QA)  ── optional, upstream
        │
        ▼
 Clean hourly series (CSV/XLSX) ──────────────┬───────────────────────────────┐
        │                                     │                               │
        ▼                                     ▼                               ▼
 HourlyEPWConverter                     TMYGenerator                   ClimateProcessor.export_*
 (→ 1 EPW per year, "long-term")   (→ TMY: 1 synthetic typical year)    (quality reports)
        │                                     │
        │                                     ▼
        │                            HourlyEPWConverter (TMY → EPW)
        │                                     │
        ▼                                     ▼
 Annual EPWs (city_year.epw)             TMY EPW
        │                                     │
        ├─────────────┬───────────────────────┤
        ▼             ▼                       ▼
  EpwTrendAnalyzer  DegreeHoursCalculator   epw_comparator
  (multi-year        / EpwBatchAnalyzer     (EPW vs EPW comparison)
   trends,            / EpwGroupTrendAnalyzer
   T warming/         (degree-hours: single EPW,
   heatwaves)          multi-EPW comparative, or
                       whole-folder trend, classified
                       by filename e.g. per city)

 convert_met_to_epw / convert_epw_to_met: independent .met ↔ .epw conversion
 (e.g., official CTE/LIDER-CALENER reference climate files)
```

---

## 2. Installation and dependencies

```bash
pip install pyweatherfiles
```

Mandatory dependencies (`pyproject.toml`): `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn`, `openpyxl`, `ladybug-core`, `pyyaml`.

**Optional** dependencies, required only by specific modules (see [§11](#11-complete-dependencies-by-module) for the exact detail): `pvlib` (`climate_processor`), `tabulate` (`epw_comparator`), `besos` + `eppy` (`degree_hours`, IDF setpoint extraction), `accim` (`degree_hours`, optional).

---

## 3. `tmy` — `TMYGenerator` (TMY generation, Sandia/TMY3 methodology)

This is the package's **core module**: it implements the **Sandia** TMY generation method (Hall et al., 1978), with additional support for NREL's **TMY3** weighting scheme (Wilcox & Marion, 2008), structured in **7 steps** (`sandia_step_1` … `sandia_step_7`) orchestrated by `generate_tmy()`.

```python
from pyweatherfiles import tmy

gen = tmy.TMYGenerator(
    file_path='weather_data.csv',
    cdf_method='daily',
    data_frequency='hourly',
    weighting_method='sandia',
)
gen.generate_tmy(use_persistence=True)
gen.export_tmy('tmy_output.csv')
```

### 3.1 Constructor (`TMYGenerator.__init__`)

| Parameter | Default | Description |
|---|---|---|
| `file_path` | — | Input CSV or Excel file (required) |
| `cdf_method` | `'daily'` | `'daily'` (aggregates, fast) or `'hourly'` (full resolution, expensive). Cannot be `'hourly'` if `data_frequency='daily'` |
| `years_to_include` | `None` | Subset of years to use; error if any requested year is missing |
| `weights` | `None` | Custom per-variable weights (overrides the default table in §3.2) |
| `column_mapping` | `None` | Additional column-mapping dict (combined with the `col_*` args) |
| `data_frequency` | `'hourly'` | `'hourly'` or `'daily'` |
| `weighting_method` | `'sandia'` | `'sandia'` or `'tmy3'` |
| `save_validation_dfs` | `True` | If `False`, skips generating the `validation_step*` tables (faster, less traceability) |
| `hourly_file_path` | `None` | Additional hourly file for assembly/smoothing when `cdf_method='daily'` (can be the same file) |
| `missing_data_threshold` | `0.9` | Data-completeness threshold (Step 2) |
| `plotting_position_method` | `'hazen'` | `'california'`, `'hazen'` or `'weibull'` |
| `datetime_col`, `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni` | `'time'`, `'T_air'`, `'T_dew'`, `'Wind_speed'`, `'GHI'`, `'DNI'` | Input column names to map |
| `save_session`, `session_dir` | `True`, `None` | Session persistence (see [§10](#10-session_manager--session-persistence-cross-cutting)) |

### 3.2 Step 1 — Loading and preparation (`sandia_step_1_load_and_prepare`)

- Applies the column mapping (`column_mapping` derived from the `col_*` arguments).
- Converts the index to `datetime` (UTC), filters by `years_to_include` if specified.
- If `data_frequency='hourly'`: resamples to hourly frequency (`resample('h').mean().interpolate('linear')`), clips negative `GHI`, `DNI` and `Wind_speed` values to 0, and creates a `GHI=0` column with a warning if it doesn't exist.
- Computes the daily aggregates required for `weighting_method` in `{'sandia','tmy3'}`: `T_air_mean/max/min`, `T_dew_mean/max/min`, `Wind_speed_mean/max`, `GHI_sum` (and `DNI_sum` only for TMY3).
- If `hourly_file_path` was provided, it is loaded and processed the same way, then **filtered to the months present in the daily file**.
- Requires a minimum of 5 years of data.

**Default weight table** (each scheme sums to 1.0):

| Variable | Sandia hourly | TMY3 hourly | Sandia daily | TMY3 daily |
|---|---|---|---|---|
| T_air (mean) | 4/24 | 4/20 | 2/24 | 2/20 |
| T_air (max) | — | — | 1/24 | 1/20 |
| T_air (min) | — | — | 1/24 | 1/20 |
| T_dew (mean) | 4/24 | 4/20 | 2/24 | 2/20 |
| T_dew (max) | — | — | 1/24 | 1/20 |
| T_dew (min) | — | — | 1/24 | 1/20 |
| Wind speed (mean) | 4/24 | 2/20 | 2/24 | 1/20 |
| Wind speed (max) | — | — | 2/24 | 1/20 |
| GHI (sum) | 12/24 | 5/20 | 12/24 | 5/20 |
| DNI (sum) | — (excluded) | 5/20 | — (excluded) | 5/20 |

### 3.3 Step 2 — Candidate selection via the Finkelstein-Schafer statistic (`sandia_step_2_select_candidates_fs`)

For each calendar month (1-12) and each available year, the **empirical cumulative distribution function (CDF)** of that candidate month/year is compared against the long-term CDF (all years) for the same calendar month.

**Plotting-position formulas for the empirical CDF** (`plotting_position_method`, default `'hazen'`):

```
hazen:      CDF(i) = (i − 0.5) / n
weibull:    CDF(i) = i / (n + 1)
california: CDF(i) = i / n
```
(`i` = ascending rank 1..n of the sorted values; `n` = sample size)

**Finkelstein-Schafer (FS) statistic** for a variable, month and candidate year (Finkelstein & Schafer, 1971):

```
FS = (1/N) · Σ_{d=1}^{N} | CDF_candidate(x_d) − CDF_long_term(x_d) |
```

where `N` is the number of points in the candidate (days if `cdf_method='daily'`, hours if `'hourly'`), and `CDF_long_term` is interpolated at each of the candidate's `x_d` values.

**Total weighted FS** for a candidate year-month:

```
Total_W_FS = Σ_i  weight_i · FS_i        (sum over all weighted variables, table in §3.2)
```

**Data-completeness filter** (`missing_data_threshold`, default 0.9): a candidate year-month is **excluded** if `valid_points / expected_points < 0.9` (where `expected_points = days_in_month × 24` for hourly, or `days_in_month` for daily). Excluded months are recorded (`excluded_months`) and reported to the console.

For each month, the **5 years with the lowest `Total_W_FS`** are retained as initial candidates (`candidate_months_pre_proximity`).

### 3.4 Step 3 — *Proximity Ranking* (`sandia_step_3_proximity_ranking`)

Re-orders the 5 FS candidates by their closeness to the long-term temperature and GHI statistics, following the **Sawaqed, Zurigat & Al-Hinai (2005)** criterion.

For each month, the mean, median, standard deviation and range of long-term daily mean temperature (`T_air`/`T_air_mean`) and GHI (`GHI`/`GHI_sum`) are computed.

**Absolute deviations of the candidate from the long-term statistic:**

```
err_t_mean    = |T_mean(candidate)   − T_mean(LT)|
err_t_median  = |T_median(candidate) − T_median(LT)|
err_ghi_mean  = |GHI_mean(candidate)  − GHI_mean(LT)|
err_ghi_median= |GHI_median(candidate)− GHI_median(LT)|
```

**Normalization** (`normalization_method`, default `'std'`; denominators `den_T`, `den_GHI`):

| Method | den_T | den_GHI |
|---|---|---|
| `std` (default) | σ_T (LT std. dev.) | σ_GHI (LT std. dev.) |
| `long_term_mean` | \|LT T mean\| | \|LT GHI mean\| |
| `range` | LT T range (max−min) | LT GHI range (max−min) |
| `weighted` | σ_T | σ_GHI |
| `no_normalization` | 1 | 1 |

(protected denominator: if 0/NaN, 1.0 is used)

**Proximity score:**

```
if method != 'weighted':
    Proximity_Score = max(err_t_mean/den_T, err_t_median/den_T,
                            err_ghi_mean/den_GHI, err_ghi_median/den_GHI)

if method == 'weighted':
    Proximity_Score = w_t_mean·(err_t_mean/den_T)   + w_t_median·(err_t_median/den_T)
                    + w_ghi_mean·(err_ghi_mean/den_GHI) + w_ghi_median·(err_ghi_median/den_GHI)

    default weights: t_mean=0.30, t_median=0.20, ghi_mean=0.30, ghi_median=0.20  (sum to 1.0)
```

> **Backward compatibility:** the historical alias `normalization_method='sawaqed'` is still accepted but is **deprecated**, and is internally mapped to `'weighted'` (emits a `DeprecationWarning`).

The 5 candidates are re-sorted in **ascending** order by `Proximity_Score` (best = lowest score).

### 3.5 Steps 4-5 — Persistence filtering and final month selection (`sandia_step_4_and_5_apply_persistence`)

Starting point: the 5 candidates already re-ordered by proximity. **Two methods** are offered (`persistence_method`):

#### (a) `'sequential'` — deterministic sequential exclusion (used by default in `generate_tmy()`)

For each candidate, the **runs** of consecutive days are computed:
- Daily mean temperature **above** the 67th percentile ("warm" runs) **or below** the 33rd percentile ("cold" runs) of the month's long-term distribution.
- Daily GHI **below** the 33rd percentile ("low-radiation" runs).
- Configurable thresholds via `thresholds=(0.33, 0.67)`; minimum run length configurable via `min_run_length` (default 1 day).

These are aggregated into `Total_Runs` (total number of runs) and `Max_Run_Len` (longest run), and **3 exclusion passes** are applied:

```
PASS 1 — Number of runs:
  a) if all have 0 runs                → select rank-1 directly (best proximity)
  b) if all have the same nº of runs:
        - unequal run length           → exclude the one with the longest run (tie → worst rank)
        - equal run length             → exclude the worst rank (last in the list)
  c) if the nº of runs differs         → exclude the one with the most runs (tie → worst rank)

PASS 2 — Run length (over Pass-1 survivors):
  a) unequal length                    → exclude the one with the longest run
                                          (tie → most total runs, then worst rank)
  b) equal length:
        - same nº of runs              → exclude the worst rank
        - different nº of runs         → exclude the one with the most runs (tie → worst rank)

PASS 3 — Zero-run candidates (over Pass-2 survivors), per `zero_run_method`:
  - 'eliminate_worst_ranked' (default) → exclude only the worst rank among the zero-run ones
  - 'eliminate_all'                    → exclude ALL zero-run candidates
  - 'eliminate_none'                   → exclude none
```

**Final selection (Step 5):** among the survivors, the one with the **best proximity rank** (lowest `Original_Rank`) is chosen.

Each decision is recorded with its textual reason (e.g. `"Excluded Pass 1 (Rule 1c: Max Runs)"`) in `validation_step4_persistence_sequential_details[month]`.

#### (b) `'score'` — weighted scoring (alternative)

```
Score = Total_W_FS
      + w_t_longest_run  · T_air_longest_run
      + w_t_total_runs   · T_air_num_runs
      + w_ghi_longest_run· GHI_longest_run
      + w_ghi_total_runs · GHI_num_runs

Default weights: w_t_longest_run=0.002, w_t_total_runs=0.001,
                  w_ghi_longest_run=0.001, w_ghi_total_runs=0.0005
```
The candidate with the **lowest Score** is chosen. Weights are customizable via `persistence_weights` (invalid keys are warned about and ignored).

`use_persistence=False` skips these steps and directly selects the candidate with the best FS/proximity rank (`_select_months_by_fs_rank`).

### 3.6 Step 6 — Raw TMY assembly (`sandia_step_6_assemble_tmy`)

For each of the 12 months, the full month (at hourly resolution if `df_hourly` is available, otherwise daily) of the **selected year** is extracted, re-labeled to the synthetic year 2000, February 29th removed if the source year was a leap year, and the 12 months are concatenated into `tmy_raw`.

### 3.7 Step 7 — Monthly-junction smoothing (`sandia_step_7_smooth_junctions`)

- **Requires hourly data** (`df_hourly` or `hourly_file_path`); if not available, smoothing is skipped (final TMY = raw TMY) with a warning.
- For each of the **11 junctions** between consecutive months:
  1. A **smoothing spline** is fit (`scipy.interpolate.UnivariateSpline`, `s_factor` parameter, default `0.0` → exact interpolation) using the **two full months** of hourly data from their respective source years.
  2. The spline is evaluated over a **configurable window** around the junction (`hours` before/after, default 6 h; independently configurable per junction and per side via the `smoothing_config` dict).
  3. Raw values in that window are replaced by the smoothed ones, **for all variables except `GHI` and `DNI`** (radiation is left untouched so as not to distort solar geometry).
- **Final safety clip:** residual negative (undershoot) values in `GHI`, `DNI` or `Wind_speed` are clipped to 0.
- Automatically generates the `validation_step6_tmy_composition` validation table and calls `generate_full_summary()`.
- **Automatically saves a reproducible session** (`.pkl` + `.json`) if `save_session=True` (default) — see [§10](#10-session_manager--session-persistence-cross-cutting).

### 3.8 `generate_tmy()` — orchestrator of the 7 steps

```python
gen.generate_tmy(
    use_persistence=True,                       # applies steps 4-5
    persistence_thresholds=(0.33, 0.67),
    min_run_length=1,
    persistence_weights=None,                   # only for persistence_method='score'
    persistence_method='sequential',             # 'sequential' (default) or 'score'
    zero_run_method='eliminate_worst_ranked',    # only for 'sequential'
    completeness_threshold=0.9,
    save_validation_dfs=True,
    proximity_normalization_method='std',        # 'std'|'long_term_mean'|'range'|'weighted'|'no_normalization'
    proximity_normalization_weights=None,        # only for 'weighted'
)
```

Internally runs, in order: `sandia_step_1_load_and_prepare` → `sandia_step_2_select_candidates_fs` → `sandia_step_3_proximity_ranking` → (`sandia_step_4_and_5_apply_persistence` if `use_persistence=True`, otherwise `_select_months_by_fs_rank`) → `sandia_step_6_assemble_tmy` → `sandia_step_7_smooth_junctions`.

### 3.9 Export (`export_tmy`)

```python
gen.export_tmy('tmy_output.csv')   # also supports .tmy / .xlsx
```

- Final safety clip of negatives in `GHI`/`DNI`/`Wind_speed`.
- **Adds auxiliary columns**: any variable present in `df_hourly` but absent from `tmy_final` is assembled the same way as the TMY (same selected months/years) and appended.
- **Restores the source file's original column names** (inverse of `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni`, `datetime_col`) before writing.

> **Units note:** `TMYGenerator` is **unit-agnostic** for every variable throughout the whole statistical process (it does not convert km/h or hPa); it simply preserves the values exactly as they arrived from the source file. Conversion to SI/EPW units (m/s, Pa) happens exclusively in `HourlyEPWConverter` ([§4](#4-hourly_epw_converter--hourlyepwconverter--batchhourlyepwconverter)). This separation of concerns (statistical engine ↔ EPW export layer) is an architectural decision relevant to the reproducibility of the method.

### 3.10 Validation, diagnostics and visualization

`TMYGenerator` keeps, after every step, a rich set of **validation attributes** (`validation_step2_fs_ranking_by_month`, `validation_step2_summary_fs_ranking`, `validation_step3_proximity_ranking`, `validation_step4_df_persistence_decision`, `validation_step4_persistence_sequential_details`, `validation_step4_persistence_score_details`, `validation_step5_selected_months_summary`, `validation_step6_tmy_composition`, `validation_full_summary`, `validation_selection_analysis`) which are automatically included in the persisted session ([§10](#10-session_manager--session-persistence-cross-cutting)).

**Console printing/validation methods:**

| Method | Description |
|---|---|
| `validate_step_1_data_loading()` | Descriptive statistics of `df_hourly`/`df_daily` |
| `validate_fs_calculation(variable, month, year)` | Step-by-step breakdown of the FS calculation for a specific case; returns a DataFrame with the interpolation |
| `validate_full_ranking_for_month(month)` | Full FS ranking (all years) for a month |
| `validate_persistence_selection()` | Prints the persistence decision tables (sequential or score) month by month |
| `validate_step_4_final_tmy()` | TMY composition table + descriptive statistics of the final TMY |
| `summarize_fs_results()` | Summary table of the FS ranking of the 5 candidates for each month |
| `check_input_expectations(file_path, weighting_method, data_frequency, column_mapping)` *(static)* | Analyzes an input file and suggests the required `column_mapping`, also validating the time-column format |

**Visualization methods (matplotlib):**

| Method | Description |
|---|---|
| `plot_cdfs(month_to_plot, years_to_plot)` | CDFs of specific years vs. the long-term CDF, for a given month |
| `plot_fs_details(var_to_plot, month_to_plot, year_to_plot)` | Step-by-step visualization of the FS statistic calculation (before/after interpolation) |
| `plot_junctions(junctions_to_plot, hours_around)` | Raw (unsmoothed) data around the monthly junctions |
| `plot_smoothing_comparison(junctions_to_plot, hours_around)` | Before/after smoothing comparison, with the parameters used shown in the title |
| `plot_persistence_runs(month, years)` | Temperature and GHI runs, with the run bands highlighted |
| `plot_annual_cdfs()` | Annual CDF of the final TMY vs. long-term, 4 main variables |
| `plot_monthly_means()` | Monthly means (and total GHI) of the final TMY vs. long-term |
| `plot_monthly_cdfs(sharex)` | Grid of 12 subplots (one per month) comparing the TMY CDF vs. long-term |

**Analysis and correction methods (v4.09+):**

| Method | Description |
|---|---|
| `get_candidate_stats(month)` | DataFrame with T/GHI (mean, difference vs. long-term, percentile) of the 5 candidates after *Proximity Ranking* |
| `generate_full_summary()` | Consolidated table with **one row per month** containing the key metrics of every step (FS, proximity, persistence, selected year, T/GHI differences vs. long-term) → `validation_full_summary` |
| `analyze_selection(months, temp_diff_threshold=1.0, ghi_diff_threshold=None)` | Audits the month selection, flagging (`Flagged`) those whose T/GHI deviates more than the threshold from the long-term value |
| `correct_selection_by_temperature(months, temp_diff_threshold=1.0, regenerate=True)` | Automatically replaces anomalous selections with the top-5 candidate that minimizes \|T_mean − T_mean_LT\|, and optionally regenerates the TMY (raw + smoothed) in-place |
| `plot_monthly_trend(months, variable, show_candidates=False)` | Year-over-year trend of the monthly mean, TMY year marked with a ★, global linear trend line; with `show_candidates=True` the other top-5 candidates are also shown |
| `plot_monthly_series(months, variable)` | Daily series of all years overlaid (TMY year in thick red, the rest in light blue) + long-term mean |
| `compare_tmy_versions(other_tmy_df, months, variable)` | Side-by-side comparison of two TMY versions (e.g., before/after `correct_selection_by_temperature`) |

### 3.11 Backward compatibility

`tmy.py` keeps, alongside the current `sandia_step_*` methods, **deprecated aliases** that wrap the new ones and emit a `DeprecationWarning`: `step_1_load_and_prepare_data()`, `step_2_select_candidate_months()`, `step_3_apply_persistence()`, `step_4_create_and_smooth_tmy()`. Compatibility *properties* also exist for the old validation-attribute names (`validation_st2_df_fs_ranking_by_month`, `validation_st2_summary_fs_ranking`, `validation_st3_df_persistence_decision`, `validation_st3_persistence_sequential_details`, `validation_st3_persistence_score_details`, `validation_st4_df_tmy_composition`), which transparently redirect to the current `validation_step*` attributes.

---

## 4. `hourly_epw_converter` — `HourlyEPWConverter` / `BatchHourlyEPWConverter`

```python
from pyweatherfiles import hourly_epw_converter

converter = hourly_epw_converter.HourlyEPWConverter(
    file_path='weather_data.csv',      # already clean, no gaps
    base_epw_path='template.epw',      # EPW template (provides lat/lon/elev/tz)
)
converter.process(output_pattern='city_{year}.epw')   # 1 EPW per available year
```

Converts already-cleaned hourly series (CSV/Excel) into **EPW** format, suitable both for generating the "long-term" series (one EPW per year) and for converting the CSV/Excel output of `TMYGenerator.export_tmy()` into the final EPW of the typical year.

### 4.1 Constructor

- `file_path`, `base_epw_path` (required).
- `lat, lon, elev, tz_hour` (optional): if not provided, they are **automatically extracted** from the EPW template via `ladybug.epw.EPW(base_epw_path).location`.
- Configurable column mapping: `datetime_col='time'`, `col_temp='Dry-bulb temperature'`, `col_dew='Dew Point temperature'`, `col_wind='Wind Speed'`, `col_ghi='Global Horizontal Irradiance '`, `col_dni='Beam Normal Irradiance '`, `col_rh='Relative Humidity'`, `col_pres='Pressure'`, `col_wind_dir='Wind Direction'`, `col_dhi='Diffuse Horizontal Irradiance'`, `col_cloud_cover='Total Cloud Cover'`, `col_irh='IRh'` — or a global `column_mapping` dict.
- `preserve_extra` (bool): if `True`, does not overwrite the `total_sky_cover` field when a cloud-cover column is available.
- `remove_leap_day` (bool, default `True`): removes February 29th to keep the EnergyPlus 8760-h/year standard.

### 4.2 Data loading (`_load_file`)

- Reads `.xlsx` or `.csv`, parses the time index, **sorts chronologically**.
- **Automatic unit conversion (fixed package convention):**
  - Wind speed: `Wind_speed = Wind_speed_input / 3.6` → **input is assumed to be in km/h** and converted to m/s.
  - Pressure: `Pressure = Pressure_input * 100.0` → **input is assumed to be in hPa** and converted to Pa.
- Records the available years (`available_years`); `get_year_data(year)` isolates the DataFrame for a specific year.

### 4.3 Auxiliary formulas

**Relative humidity** (if not present in the file), from dry-bulb temperature `T_db` and dew-point `T_dp` (Magnus/August-Roche-Magnus-type formula):

```
e_s(T) = 6.112 · exp( 17.67·T / (T + 243.5) )      [saturation vapor pressure]
RH = 100 · e_s(T_dp) / e_s(T_db)                    [clipped to [0, 100] %]
```

**Standard atmospheric pressure by elevation** (international barometric formula, if not present in the file):

```
P(h) = P0 · (1 − L·h / T0) ^ (g·M / (R·L))

P0 = 101,325 Pa      L  = 0.0065 K/m
T0 = 288.15 K        g  = 9.80665 m/s²
M  = 0.0289644 kg/mol   R  = 8.31447 J/(mol·K)
```

**Diffuse horizontal irradiance (DHI)**, if not present in the file, reconstructed from GHI and DNI using the exact solar position (`ladybug.sunpath.Sunpath`, evaluated at the mid-point of each hour, `hour + 0.5`):

```
zenith = 90° − solar_altitude
cos_zenith = cos(zenith)

if cos_zenith ≤ 0.01:   DHI = GHI                (sun very low / below the horizon)
otherwise:               DHI = max(0, GHI − DNI·cos_zenith)
```

### 4.4 Transformation to EPW (`transform_to_epw`)

1. Filters/adjusts the year to 8760 or 8784 hours depending on `remove_leap_day` and whether the year is a leap year.
2. Loads the EPW template with `ladybug.epw.EPW`, updates the header (lat, lon, elevation, time zone, comments) and the `AnalysisPeriod`.
3. Extracts and injects (via `_set_epw_values`, see below): `dry_bulb_temperature`, `dew_point_temperature`, `relative_humidity`, `wind_speed`, `wind_direction` (0 if absent), `global_horizontal_radiation`, `direct_normal_radiation`, `diffuse_horizontal_radiation`, `atmospheric_station_pressure`. Optionally `total_sky_cover` and `horizontal_infrared_radiation_intensity` if those columns exist.
4. **Ladybug offset correction (`_set_epw_values`)**: EPW fields marked as *point-in-time* suffer from an internal index offset in `ladybug-core`; the converter compensates by shifting the series one position (`[last] + rest[:-1]`) before assigning it.
5. **Neutralization of EPW variables not used by EnergyPlus**: 15 fields (extraterrestrial radiation/illuminance, illuminances, cloud cover, visibility, ceiling height, precipitable water, aerosol optical depth, days since last snowfall, albedo, liquid precipitation) are filled with the **official EPW "missing value" codes** (e.g. `9999`, `999999`, `99`, `0.999`), instead of leaving them at 0, preventing EnergyPlus from misreading them as valid data.
6. Saves the resulting EPW with `epw_data.save(...)`.

### 4.5 Batch processing (`process`)

- Generates **one EPW per available year** (or for a specific list of years via `years=[...]`), naming each file according to `output_pattern` (e.g. `'city_{year}.epw'`) or, by default, `'{basename}_{year}.epw'`.
- On completion, if `save_session=True` (default), automatically saves a **reproducible session** (`.pkl` + `.json`) — see [§10](#10-session_manager--session-persistence-cross-cutting).

### 4.6 `BatchHourlyEPWConverter` — multi-city orchestration

```python
from pyweatherfiles import hourly_epw_converter

config = hourly_epw_converter.BatchHourlyEPWConverter.suggest_config(
    identifiers=['MADRID', 'SEVILLE'],
    data_files='path/to/data/',       # folder or list of files
    base_epw_files='path/to/epws/',   # folder or list of EPW templates
)
batch = hourly_epw_converter.BatchHourlyEPWConverter(config, output_dir='output/')
batch.process_all(output_pattern='{identifier}_{year}.epw')
```

- `cities_config`: list of dicts (or `DataFrame`) with, at minimum, `file_path` and `base_epw_path` per city; optional keys `lat/lon/elev/tz_hour`, `years`, and any free-form variable used to format `output_pattern`.
- `get_mandatory_config_keys()` *(classmethod)*: prints/returns the mandatory keys.
- `suggest_config(identifiers, data_files, base_epw_files)` *(classmethod)*: automatically matches, by name (substring, case-insensitive), each identifier with its data file and its EPW template, extracting lat/lon/elev/tz_hour from the latter via Ladybug.
- `process_all(output_pattern, remove_leap_day=True, **global_kwargs)`: iterates over each city, instantiates a `HourlyEPWConverter` and calls `process()`, combining `global_kwargs` with each city's own variables to fill in `output_pattern`; prints a final summary and saves a batch session.

---

## 5. `met_epw_converter` — `convert_met_to_epw` / `convert_epw_to_met`

```python
from pyweatherfiles import met_epw_converter

met_epw_converter.convert_met_to_epw(
    met_path='reference_climate.met',
    base_epw_path='template.epw',
    epw_path='reference_climate.epw',
    replace_unused_with_missing=True
)
```

### 5.1 The `.met` format

Plain-text file with:
- A **metadata line** with latitude, longitude and elevation (automatically located if not in the expected position, by scanning the first 10 lines for a plausible latitude value `[-90, 90]`).
- A **13-column data block** (`Month, Day, Hour, DryBulb, SkyTemp, RadDirectaHoriz, RadDifusaHoriz, AbsHum, RelHum, WindSpeed, WindDir, Azimuth, Zenith`) or a 15-column variant (no `WindDir`, with 2 unused auxiliary columns).
- The time zone is approximated as `tz_hour = round(longitude / 15.0)` (nominal solar time zone, not necessarily the real civil/political time zone).
- This is the format of the reference climate files used in the **Spanish Building Technical Code** (CTE DB-HE), LIDER/CALENER type.

### 5.2 Conversion formulas (MET → EPW)

**Dew-point temperature** (inversion of the Magnus formula, from `T_db` and `RH`):

```
b = 17.62,  c = 243.12
γ = b·T_db/(c+T_db) + ln(RH/100)
T_dp = c·γ / (b − γ)
```

**Atmospheric pressure** reconstructed by reverse engineering from the absolute humidity (`AbsHum`, W) provided by the `.met` file:

```
e_s(T) = 610.78 · 10^(7.5·T/(237.3+T))     [saturation vapor pressure, Pa]
e = e_s(T_db) · RH/100                      [actual vapor pressure]
P_atm = e · (1 + 0.62198 / W)

→ if P_atm ∉ [50,000, 110,000] Pa (non-physical value), the standard
  barometric formula by elevation (identical to §4.3) is used as a fallback.
```

**Sky temperature → horizontal infrared radiation** (Stefan-Boltzmann law):

```
IR = σ · (T_sky + 273.15)⁴          σ = 5.6697 × 10⁻⁸ W/(m²·K⁴)
```

**Astronomical reconstruction of GHI/DNI** (with quality control):

```
GHI = RadDirectaHoriz + RadDifusaHoriz     (negative inputs clipped to 0, counted)

For each hour, with exact solar position evaluated at (hour − 0.5):
  zenith = 90° − solar_altitude ;  cos_zenith = cos(zenith)

  if cos_zenith ≤ 0.01  or  RadDirectaHoriz ≤ 0:   DNI = 0
  otherwise:
      DNI = RadDirectaHoriz / cos_zenith
      DNI = min(DNI, 1367 W/m²)      ← clipped to the solar constant (number of clips logged)
```

After the calculation, the converter prints a **quality-control report**:
- DNI statistics (minimum, 95th percentile, maximum; number of "low sun" hours and number of clips due to DNI > 1367 W/m²; number of negative direct-horizontal-radiation values detected in the input).
- **Radiation balance closure**: `residual = GHI − (DHI + DNI·cos_zenith)`, reporting the mean and 95th percentile of the absolute value.

### 5.3 Rest of the process (MET → EPW)

- Forces a standard non-leap 8760-h `AnalysisPeriod`.
- Applies the same *point-in-time* offset correction as in `HourlyEPWConverter` (§4.4, item 4).
- If `replace_unused_with_missing=True`, neutralizes the same 15 unused EPW fields with their official missing-value codes (identical to §4.4, item 5).
- Saves a reproducible session via `save_function_session` (function-style API, not class-based) if `save_session=True` (default).

### 5.4 Reverse conversion: `convert_epw_to_met(epw_path, met_path)`

Reconstructs a `.met` file (13-column format) from an existing EPW:
- `RadDirectaHoriz = GHI − DHI` (clipped ≥ 0); `RadDifusaHoriz = DHI` directly.
- Sky temperature: Stefan-Boltzmann inversion from `horizontal_infrared_radiation_intensity`.
- Absolute humidity: standard psychrometric formula from T, RH and pressure (computed by elevation).
- Fixed timestamp in the year 2005 (`Mes_Num`, `Dia`, `Hora`); `Azimuth`/`Zenith` are left as `0` (not reconstructed); DNI is not stored (the `.met` format only stores horizontal components).

---

## 6. `degree_hours` — `DegreeHoursCalculator` / `EpwBatchAnalyzer` / `EpwGroupTrendAnalyzer`

```python
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('city_tmy.epw')
results = calc.calculate('building_model.idf', frequency=['hourly', 'daily', 'monthly'], mode='both')
print(results['monthly'])
calc.export_results('degree_hours.xlsx')
```

Computes **heating (HDH) and cooling (CDH) degree-hours** from an EPW and a set of temperature setpoints, extracted from an **IDF** file (EnergyPlus) or defined through a **custom dictionary**.

### 6.1 Constructor (`DegreeHoursCalculator(epw_path, year=None)`)

- Loads the EPW via `ladybug.epw.EPW`; builds `self.temperatures` (hourly dry-bulb temperature series indexed by a synthetic year).
- Builds `self.epw_data`: a DataFrame with **all** available EPW hourly variables (22 possible: temperature, dew point, relative humidity, pressure, global/direct/diffuse radiation-illuminance, zenith luminance, wind, sky cover, visibility, ceiling height, horizontal IR, precipitable water, aerosol optical depth, snow, precipitation) — also useful for `EpwBatchAnalyzer` (§6.4) and for `EpwTrendAnalyzer` (§7).

### 6.2 Setpoint source: IDF or custom dictionary

**(a) From an IDF** — `extract_setpoints_from_idf(idf_path, zone_name=None)`:
- Loads the building via `besos.eppy_funcs.get_building` (with `eppy` as a *fallback*).
- For each `ZONECONTROL:THERMOSTAT`, locates its associated `THERMOSTATSETPOINT:DUALSETPOINT` object and extracts the heating/cooling setpoint *schedules*.
- **Resolves EnergyPlus *schedules***, supporting two types:
  - `SCHEDULE:COMPACT`: a full parser for `Through: MM/DD` blocks (date ranges), `For: <day-types>` blocks (`Weekdays`, `Weekends`, `AllDays`, `AllOtherDays`, individual days), and `Until: HH:MM`/value pairs, building a 24-h hourly profile per day-type and date range.
  - `SCHEDULE:YEAR` → `SCHEDULE:WEEK:DAILY` → `SCHEDULE:DAY:HOURLY`/`SCHEDULE:DAY:INTERVAL`: resolves the full chain of references.
- Also extracts the **HVAC availability *schedules*** (`ZoneHVAC:IdealLoadsAirSystem`, via the chain `ZoneHVAC:EquipmentConnections` → `ZoneHVAC:EquipmentList` → `ZoneHVAC:IdealLoadsAirSystem`): when the system is scheduled off, the degree-hours for that period are zeroed out (not counted). Zones without an `IdealLoads` system are assumed available 100% of the time.

**(b) From a custom dictionary** — 4 types supported in `config['type']`:

| `type` | Structure | Use |
|---|---|---|
| `'constant'` | `{'heating': 21.0, 'cooling': 26.0}` | Fixed setpoint all year |
| `'daily'` | `{'heating': [...365/366 values...], 'cooling': [...]}` | One value per day of the year |
| `'weekly'` | `{'periods': {name: ('MM-DD','MM-DD')}, 'patterns': {period: {day_type: {'heating':val,'cooling':val}}}}` | One value per day-type (`monday`…`sunday`, `weekday`, `weekend`, `alldays`) and period |
| `'hourly_weekly'` | Like `'weekly'` but each pattern is a list of 24 hourly values | Maximum granularity without an IDF |

### 6.3 Calculation (`calculate`)

```
HDH_h = max(0, SP_heating_h − T_h)     (only hours in `hours`, otherwise 0)
CDH_h = max(0, T_h − SP_cooling_h)     (only hours in `hours`, otherwise 0)
```

- Setpoints are **masked by HVAC availability** (when sourced from an IDF): if the system is off, HDH/CDH = 0 for that hour.
- Optional period filter (`start_date`/`end_date`, `'DD/MM'` format, supports ranges that cross New Year's Eve, e.g. December→February) and hours-of-day filter (`hours=[0..23]`).
- Configurable aggregation (`frequency`): `'hourly'`, `'daily'` (`.resample('D').sum()`), `'monthly'` (`.resample('ME').sum()`), `'yearly'` (`.resample('YE').sum()`).
- `mode`: `'heating'`, `'cooling'` or `'both'`.
- `zone_name`: if `None`, averages setpoints and availability across **all** zones with a thermostat in the IDF.
- Results stored in `self.result_hourly/daily/monthly/yearly`; a reproducible session is saved automatically.

### 6.4 Visualization and export

- `plot(setpoint_source, period='year'|'month'|'week'|'day', period_value=..., show_air_temp=False)`: graphically compares the setpoints (and optionally the EPW temperature). Yearly view = daily mean + min/max band; month/week/day views = hourly resolution. Where the HVAC is off, the setpoint is masked to `NaN` (visual gap) for quick QA before computing.
- `export_results(output_path='degree_hours_results.xlsx')`: exports each computed frequency table to a separate Excel sheet.

### 6.5 `EpwBatchAnalyzer` — multi-EPW comparative analysis

```python
from pyweatherfiles.degree_hours import EpwBatchAnalyzer

batch = EpwBatchAnalyzer(
    epw_paths=['city_tmy.epw', 'city_met.epw', 'city_2020.epw'],
    setpoint_source='building_model.idf',
    epw_variables={'global_horizontal_radiation': ['sum', 'mean']},
    hours={'morning': list(range(9)), 'all_day': list(range(24))},
    frequencies=['hourly', 'daily', 'monthly'],
    start_date='01/06', end_date='30/09',
)
results = batch.run()          # dict {freq: DataFrame with MultiIndex columns (epw, variable)}
batch.export('batch_degree_hours.xlsx')
```

- Runs `DegreeHoursCalculator` over **multiple EPWs** and **multiple hour scenarios** (`hours` can be a flat list, a list of lists, or a dict of named scenarios — each generating columns with its own suffix, e.g. `heating_dh_morning`).
- `epw_variables` accepts either a plain list (automatic aggregation: `sum` for radiation/illuminance/precipitation variables, `mean` for the rest) or a dict `{variable: agg_func | [agg_func, ...]}` (`'sum'/'mean'/'max'/'min'/'std'`).
- Result: DataFrame(s) with **MultiIndex** columns `(epw, variable)`, one per requested frequency — ideal for comparative tables in an article (TMY vs. actual years vs. official reference file).
- `export()` writes a combined `all_epws_<freq>` sheet per frequency (and, if only one frequency was requested, also one sheet per EPW).

### 6.6 `EpwGroupTrendAnalyzer` — batch degree-hours + trend analysis over a whole classified EPW set

```python
from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer

analyzer = EpwGroupTrendAnalyzer(
    epw_dir='longterm_epw/',                                   # scans '*.epw', classified by filename
    setpoint_source={'type': 'constant', 'heating': 20.0, 'cooling': 25.0},
    hours_scenarios={
        'allday': {'hours': None, 'mode': 'both'},
        'night_0_8h': {'hours': list(range(8)), 'mode': 'cooling'},
    },
    extra_epw_variables={'global_horizontal_radiation': ['sum']},
    scale_factors={'global_horizontal_radiation_sum': 0.001},   # Wh/m2 -> kWh/m2
)
results = analyzer.run()                        # long-format DataFrame, one row per group-year
trends = analyzer.compute_trends('heating_dh_allday')
analyzer.plot_overview_grid(out_path='fig_overview.png')
```

Unlike `EpwBatchAnalyzer` (§6.5) — designed to compare a *handful* of individually-named EPWs (e.g. "TMY vs. official file vs. one real year") in a single MultiIndex table — `EpwGroupTrendAnalyzer` targets the opposite situation: **an entire set of EPW files covering several independent climates over many years each** (e.g. `longterm_epw/granada_2005.epw` … `longterm_epw/seville_2025.epw`), where each climate must be analysed **fully independently** — never pooled/averaged with another — to expose a genuine year-over-year trend of any degree-hour indicator.

**Filename classification** (`pyweatherfiles.epw_utils.classify_epw_files`, a small shared helper): every EPW under `epw_dir` (or in the explicit `epw_paths` list) is matched against a regex with named groups `group` (the classification key, e.g. city) and `year` (4-digit); default pattern `r'^(?P<group>[a-zA-Z]+)_(?P<year>\d{4})\.epw$'` (matches e.g. `'granada_2005.epw'`). Files that do not match are skipped with a warning. Result stored in `file_groups: {group: {year: path}}`.

**Constructor parameters:**

| Parameter | Default | Description |
|---|---|---|
| `epw_dir` / `epw_paths` | — | Folder to scan for `*.epw`, or an explicit path list (one of the two is required) |
| `filename_pattern` | `'<group>_<year>.epw'` regex | Named-group regex used for classification |
| `setpoint_source` | `{'type':'constant','heating':20.0,'cooling':25.0}` | Forwarded to every `DegreeHoursCalculator.calculate()` call (IDF path or dict, §6.2) |
| `hours_scenarios` | `{'allday': {'hours': None, 'mode': 'both'}}` | `{label: {'hours': [...]\|None, 'mode': 'heating'\|'cooling'\|'both'}}` — one degree-hour calculation per scenario, producing `heating_dh_<label>`/`cooling_dh_<label>` columns |
| `extra_epw_variables` | `{}` | `{epw_variable: [aggfunc,...]}` — additional annual climate variables (e.g. GHI) alongside degree-hours; aggfuncs: `sum`/`mean`/`max`/`min`/`std` |
| `scale_factors` | `{}` | `{result_column: factor}` multiplicative unit conversion applied after computation (e.g. Wh/m² → kWh/m²) |
| `group_order`, `group_labels`, `group_colors`, `group_zone` | `None` / `{}` | Optional display customisation used only by the plotting methods (e.g. coldest→warmest ordering, accented city names, CTE climate-zone tags) |
| `year_override` | `None` | Overrides the year assigned to every EPW's hourly index instead of the year parsed from the filename |

**Attributes** (inputs and results stored explicitly, per the class's reproducibility design): `inputs` (dict, every constructor argument verbatim), `file_groups` (dict), `results` (long-format `pandas.DataFrame`, one row per group-year, populated by `run()`), `trend_stats_` (dict of `pandas.DataFrame`, cached per value column by `compute_trends()`), `calculators` (dict of `DegreeHoursCalculator`, one per processed file, giving access to the full hourly data if needed).

**Methods:**

| Method | Description |
|---|---|
| `run(save_session=True)` | Computes every `hours_scenarios` degree-hour scenario + `extra_epw_variables` for every classified file → `results` |
| `compute_trends(value_col)` | Independent per-group linear regression (`scipy.stats.linregress`) of `value_col` against year → DataFrame indexed by group (`n, slope, intercept, r2, pvalue, significant`) |
| `plot_variable_grid(value_col, ncols=3, harmonize_ylim=True, out_path=None)` | Small-multiples grid, one subplot per group: bars for every year + its own OLS trend line |
| `plot_overview_grid(variables=None, harmonize_ylim=True, out_path=None)` | Rows = variables, columns = groups — every cell its own bars + trend line, y-axis harmonised within each row (a trend line dipping below zero in one group propagates its range to the rest of that row) |
| `export_results(output_path)` | `results` (+ cached `trend_stats_`) to CSV or XLSX |

---

## 7. `epw_trend_analyzer` — `EpwTrendAnalyzer`

```python
from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig

analyzer = EpwTrendAnalyzer(
    trend_config=TrendConfig(root_dir='longterm_epw/'),   # looks for *_????.epw, e.g. seville_2005.epw
    output_config=OutputConfig(output_dir='trend_results/'),
)
outputs = analyzer.run()   # discover_files → compute_metrics → fit_city_trends → fit_global_models → export_outputs
```

Analyzes **multi-year climate trends** (warming, heatwaves) over a collection of annual EPWs named `city_year.epw` — **exactly the output pattern produced by `HourlyEPWConverter.process()`** (§4), which naturally connects the "long-term" series generated by the pipeline to this analyzer.

### 7.1 Configuration (`TrendConfig` / `OutputConfig`, *dataclasses*)

`TrendConfig`: `root_dir`, `file_glob="*_????.epw"`, `filename_regex=r"^(?P<city>[A-Za-z]+)_(?P<year>\d{4})\.epw$"`, `abs_hot_threshold_c=35.0`, `local_hot_percentile=90.0`, `min_heatwave_length_days=3`, `city_trend_targets=("t_mean_annual","t_p95_annual")`, `primary_target="t_mean_annual"`, `secondary_target="t_p95_annual"`, `min_slope_for_practical_significance=0.02`.

`OutputConfig`: `output_dir` + flags for which artifacts to generate (`save_csv`, `save_xlsx`, `save_plots`, `save_boxplot_plot`, `save_report`, `save_markdown_report`, `write_config_snapshot`) + configurable filenames for each output, including the boxplot-per-year figures (`city_boxplot_grid_filename`, `city_boxplot_row_filename`).

Alternative constructors: `EpwTrendAnalyzer.from_dict(config)`, `.from_json(path)`, `.from_yaml(path)` (YAML requires `pyyaml`).

### 7.2 Pipeline (`run()` = 5 chainable steps)

1. **`discover_files()`**: searches `root_dir` for files matching `file_glob`, parses `city`/`year` with `filename_regex`; builds `files_df` and `coverage_df` (per city: number of years, range, years missing within the range).
2. **`compute_metrics()`**: for each EPW, computes (reusing `DegreeHoursCalculator` internally for the hourly temperature): `t_mean_annual`, `t_median_annual`, `t_p95_annual` (95th percentile), `hot_hours_abs`/`hot_days_abs` (count above `abs_hot_threshold_c`). Adds **heatwave metrics**:
   - Local climatological threshold per day of year (`month-day`): the `local_hot_percentile`-th percentile of Tmax for that specific day across all of that city's years (with a *fallback* to the whole-city percentile if data are missing for that exact day-month).
   - A day is "hot" if it exceeds either that local threshold (`hot_local`) or the fixed absolute threshold (`hot_abs`).
   - Runs of consecutive hot days of length ≥ `min_heatwave_length_days` count as heatwave events (`heatwave_events_local/abs`, `heatwave_days_local/abs`).
   As a side effect, the raw hourly dry-bulb temperature series of every file is cached in `hourly_by_city` (`{city: {year: pandas.Series}}`), used by `build_boxplot_figure()` (§7.3) to draw the boxplot-per-year figures.
3. **`fit_city_trends()`**: per-city OLS linear regression (`scipy.stats.linregress`) of each `city_trend_targets` metric against year → slope (°C/year), intercept, R², p-value, standard error.
4. **`fit_global_models()` / `fit_global_model(target)`**: fits a **global fixed-effects model** `target ~ year + C(city)` by ordinary least squares (design matrix with `pd.get_dummies(city, drop_first=True)` + intercept + year; solved via `(XᵀX)⁻¹XᵀY`, with a pseudo-inverse fallback if the matrix is singular). Reports the **slope common to all cities after controlling for each city's own climate level** (°C/year), its standard error, t-statistic, two-sided p-value (Student's t with `n_obs − n_params` degrees of freedom), 95% confidence interval, R² and sample sizes — a **panel-data** estimator with city fixed effects, a statistically rigorous technique that is citable in the methods section if trend analysis is used in the article.
5. **`export_outputs()`**: writes `annual_metrics.csv`, `city_trends.csv`, `global_trend.csv`, `coverage_summary.csv`, a combined `trend_outputs.xlsx`, 3 PNG figures (per-city trend panel for the annual mean and for the P95, plus a "globally adjusted" plot after removing city fixed effects), **plus, if `save_boxplot_plot=True` (default), 2 additional boxplot-per-year small-multiples figures** — one subplot per city, every year's raw hourly dry-bulb temperature readings as a box, with the fitted annual-mean trend line overlaid (`city_boxplot_grid_filename`: multi-column grid; `city_boxplot_row_filename`: single row, one column per city) — a plain-text `conclusion_report.txt` with an automatic verdict (positive/significant/practically relevant according to the configured thresholds), a more detailed Markdown report `conclusion_report.md`, and a `used_config.json` snapshot of the exact configuration used (reproducibility).

### 7.3 Other public methods

`plot()` (generates only the figures), `get_results()` (returns everything in memory), `to_json()` (serializes the effective configuration), `build_city_figure()` / `build_global_adjusted_figure()` / `build_boxplot_figure(target_col='t_mean_annual', ncols=3)` (to customize figures before saving them — the latter draws, from the cached `hourly_by_city`, the boxplot-per-year panel described above), `export_markdown_report()`. Module-level convenience function: `run_analysis(root_dir, output_dir)` (full pipeline with default configuration).

---

## 8. `epw_comparator` — EPW file comparison

```python
from pyweatherfiles import epw_comparator

epw_comparator.compare_epw_files('base.epw', 'generated.epw')          # console report (tabulate)
df = epw_comparator.create_comparison_hourly_dataframe('base.epw', 'generated.epw')  # hourly DataFrame
```

| Function | Description |
|---|---|
| `explore_epw_structure(epw_path)` | Diagnostic: dumps the structure of `EPW.to_dict()` (keys, types, preview) — useful for locating the hourly data collections |
| `compare_epw_files(base_epw_path, generated_epw_path)` | Console report (via `tabulate`) comparing header metadata (city, lat, lon, time zone, elevation, comments) and descriptive statistics of the difference (generated − base) for 9 key climate variables |
| `create_comparison_dataframe(base_epw_path, generated_epw_path)` | Side-by-side DataFrame built from Ladybug's `EPW.to_dict()['data_collections']`, with Spanish-named columns (`TempBulboSeco`, `HumedadRelativa`, etc.) suffixed `_Base`/`_Generado` |
| `create_comparison_hourly_dataframe(base_epw_path, generated_epw_path)` | **The function used in the article's case study** — reads both EPWs directly as CSV (skipping the 8 header lines), assigns the 35 official EPW data-dictionary field names, and returns a single DataFrame with `Base_*`/`Generated_*` columns aligned hour by hour. Uses `encoding='latin-1'` to tolerate accented characters in Spanish-origin EPWs. Saves a reproducible session by default |

---

## 9. `climate_processor` — `ClimateProcessor` (hourly series cleaning/gap-filling)

```python
from pyweatherfiles.climate_processor import ClimateProcessor

proc = ClimateProcessor('raw_station_data.xlsx', lat=37.38, lon=-5.98, alt=15)
proc.export_complete_report('quality_report.xlsx')  # filled data + summary + gaps + annual/monthly statistics
```

A **pre-processing** module (not exported in `__init__.py`, requires `pvlib`), intended to clean and gap-fill raw hourly station series **before** they serve as input to `TMYGenerator`/`HourlyEPWConverter` (upstream of the rest of the pipeline).

### 9.1 Automatic pipeline (runs in full when the class is instantiated)

1. **`_load_data`**: reads CSV/Excel (for Excel, assumes a units row below the header, `skiprows=[1]`), parses the first column as a date (`dayfirst=True`), sorts it and sets it as the index; keeps an unmodified `df_before` copy to compare before/after.
2. **`_map_variables`**: automatic column detection by keyword match (case-insensitive) for 10 canonical variables: `Dry-bulb` ('dry'), `Dew Point` ('dew'), `RH` ('humidity'), `WindDir` ('direction'), `WindSpeed` ('speed'), `Pressure` ('pressure'), `GHI` ('global'), `BHI` ('beam'+'horiz'), `DHI` ('diffuse'), `BNI` ('normal').
3. **`_reindex`**: reindexes to a continuous hourly `DatetimeIndex` between the minimum and maximum timestamp (exposes real gaps as `NaN` rows).
4. **`_fill_data`** — the gap-filling engine, with a variable-specific strategy and maximum gap limit (beyond the limit, the gap is deliberately left unfilled):

   | Variable | Method | Max. gap limit |
   |---|---|---|
   | Pressure | Linear interpolation | 72 h |
   | Dry-bulb / dew-point temperature | Cubic spline (order 3) | 24 h |
   | Relative humidity | Magnus formula (below) + residual linear interpolation | 24 h |
   | Wind speed | Linear interpolation | 3 h |
   | Wind direction | Linear interpolation | 2 h |
   | GHI / DHI / BNI | Linear interpolation (gaps ≤3h) + clear-sky index method (gaps 3-24h, daytime) | 24 h (nighttime gaps → 0) |

   **Reconstructed relative humidity** (Magnus/August-Roche-Magnus), when RH is missing but both temperatures are present:
   ```
   RH = 100 · exp(17.625·Td/(243.04+Td)) / exp(17.625·T/(243.04+T))     [clipped to [0,100]]
   ```

   **Solar-radiation gap-filling via the clear-sky index method** — the most sophisticated component: uses `pvlib.location.Location.get_clearsky()` to obtain the theoretical clear-sky reference (GHI/DHI/DNI) for the site and the exact timestamps. Short gaps (≤3h) are interpolated linearly. Medium gaps (3-24h, daytime only, `clear-sky GHI > 5 W/m²`) are filled by reconstructing a **clearness index** `kt = min(1.2, observed/clear-sky)`, smoothed with a 24h centered rolling median, and applied as `value = clear-sky_reference × smoothed_kt` — preserving realistic cloudiness patterns instead of naive interpolation. Nighttime gaps are filled with 0. Finally, if both GHI and DHI are present, **`BHI = GHI − DHI`** (clipped ≥ 0) is recomputed to ensure the internal consistency of the three radiation components.

5. **`_calculate_availability_after`**: recomputes the % completeness and builds a `summary` table (`Before_%`, `After_%`, `Gain_%` per variable).
6. **`_generate_statistics_tables`**: builds 3 quality-control tables:
   - `gaps_df`: every gap that **was** successfully interpolated (variable, start, end, hours interpolated).
   - `annual_stats`: per year × variable — total number of gaps, 100%-filled / partially filled / not filled at all, hours originally missing/filled/still empty, and an average filled-hours-per-day metric.
   - `max_gaps_df`: per year and per month, the single largest gap (in hours) for each variable, flagged `FILLED`/`NOT FILLED (>Xh)` against that variable's specific limit.

### 9.2 Export

`export_filled_data(output_name)` (filled data only), `export_annual_statistics(output_name)` (quality report `annual_stats` + `max_gaps`), `export_complete_report(output_name)` (Excel with 5 sheets: filled data, summary, gaps, annual statistics, max gaps) — all via `openpyxl`.

---

## 10. `session_manager` — session persistence (cross-cutting)

A module used **across** almost all the others (`tmy`, `hourly_epw_converter`, `met_epw_converter`, `degree_hours`, `epw_comparator`) to automatically save (`save_session=True` by default in all the main classes/functions) a **reproducible session**:

- **`.pkl`** (`save_object_session` / `save_function_session`): the complete serialized object (with a partial *fallback* — if some attribute is not serializable, it is replaced with a text placeholder and the rest is kept).
- **`.json`**: a human-readable snapshot — timestamp, package version, and all public attributes converted to a JSON-safe form (`DataFrame`/`Series`/`ndarray` are summarized by shape, columns and types; long lists are truncated to the first 10 elements).

**File naming convention** (deterministic, avoids collisions and eases traceability):

```
{Prefix}_{slug_input_1}_{slug_input_2}_{slug_input_3}_{md5_hash_8_chars}.pkl / .json
```

Retrieval: `pyweatherfiles.session_manager.load_session(pkl_path)`.

This enables **auditing and exactly reproducing** every run (input parameters + full result) — valuable for the methodology/reproducibility section of a scientific article.

---

## 11. Complete dependencies by module

| Module | Dependency | Type | Behavior if missing |
|---|---|---|---|
| `tmy` | `pandas`, `numpy`, `scipy`, `matplotlib` | Mandatory | — |
| `hourly_epw_converter` | `ladybug-core` | Mandatory (guarded) | `ImportError` with an explanatory message |
| `met_epw_converter` | `ladybug-core` | Mandatory (guarded) | `ImportError` with an explanatory message |
| `degree_hours` | `ladybug-core` | Mandatory (guarded) | `ImportError` with an explanatory message |
| `degree_hours` | `besos` (+ `eppy` as *fallback*) | Optional (guarded) | `extract_setpoints_from_idf()` will not work without `besos` |
| `degree_hours` | `accim` | Optional (guarded) | Accent-sanitization of IDF paths is skipped |
| `epw_trend_analyzer` | `scipy.stats`, `matplotlib` | Mandatory | — |
| `epw_trend_analyzer` | `pyyaml` | Optional (only `from_yaml()`) | `ImportError` with an explanatory message |
| `epw_comparator` | `ladybug-core` | Mandatory (guarded) | `ImportError` with an explanatory message |
| `epw_comparator` | `tabulate` | Module-mandatory (**unguarded**) | Standard `ImportError` when importing the module |
| `climate_processor` | `pvlib` | Module-mandatory (**unguarded**) | Standard `ImportError` when importing the module |
| `session_manager` | `numpy`, `pandas` | Mandatory | — |

> Note: `pvlib` (`climate_processor`) and `tabulate` (`epw_comparator`) are imported without a `try/except` block, unlike `ladybug-core` (which does have a custom error message in every module that uses it). This only matters if that submodule is explicitly imported (`climate_processor`/`epw_comparator` are not part of the minimal `__init__.py` API).

---

## 12. Quick examples per module

**TMY with custom weights and columns, daily data, TMY3 method** (`examples/using_tmy_generator.py`):

```python
from pyweatherfiles import tmy

column_mapping = {
    'fecha': 'time',
    'Dry-bulb temperature_max': 'T_air_max', 'Dry-bulb temperature_min': 'T_air_min',
    'Dry-bulb temperature_mean': 'T_air_mean',
    'Dew Point temperature_max': 'T_dew_max', 'Dew Point temperature_min': 'T_dew_min',
    'Dew Point temperature_mean': 'T_dew_mean',
    'Wind speed_max': 'Wind_speed_max', 'Wind speed_mean': 'Wind_speed_mean',
    'GHI_sum': 'GHI_sum', 'DNI_sum': 'DNI_sum',
}
gen = tmy.TMYGenerator(
    file_path='MADRID.xlsx', cdf_method='daily', data_frequency='daily',
    column_mapping=column_mapping, weighting_method='tmy3', save_validation_dfs=True,
)
gen.generate_tmy(use_persistence=True)
gen.export_tmy('MADRID_TMY_persistence_tmy3.csv')
```

**Individual degree-hours with preview visualization** (`examples/degreehours simple.py`):

```python
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('city_tmy.epw')
calc.plot('building.idf', period='day', period_value=['06-10', '06-11'], show_air_temp=True)
results = calc.calculate('building.idf', frequency=['hourly', 'daily', 'monthly'], mode='both')
calc.export_results('degree_hours.xlsx')
```

**Multi-EPW comparative degree-hours, multi hour-scenario** (`examples/degreehours batch.py`):

```python
from pyweatherfiles.degree_hours import EpwBatchAnalyzer

batch = EpwBatchAnalyzer(
    epw_paths=['city_tmy.epw', 'city_met.epw', 'city_2005.epw'],
    setpoint_source='building.idf',
    epw_variables={'global_horizontal_radiation': ['sum', 'mean']},
    hours={'morning': list(range(9)), 'all_day': list(range(24))},
    mode='both', frequencies=['hourly', 'daily', 'monthly'],
    start_date='01/06', end_date='30/07',
)
results = batch.run()
batch.export('summer_results.xlsx')
```

**Trend analysis over annual EPWs**:

```python
from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig

analyzer = EpwTrendAnalyzer(TrendConfig(root_dir='longterm_epw/'), OutputConfig(output_dir='trends/'))
analyzer.run()
```

**Batch degree-hours + independent per-climate trend over a whole folder of EPWs** (`analysis_scripts/climate_evolution_trend_separate_climates.py`):

```python
from pyweatherfiles.degree_hours import EpwGroupTrendAnalyzer

analyzer = EpwGroupTrendAnalyzer(epw_dir='longterm_epw/')
results = analyzer.run()
analyzer.compute_trends('heating_dh_allday')
analyzer.plot_overview_grid(out_path='fig_overview.png')
```

---

## 13. Design notes and general caveats

- **Unit convention in `HourlyEPWConverter`**: the input wind speed is assumed to be in **km/h** (divided by 3.6) and the pressure in **hPa** (multiplied by 100). If the source file is already in m/s or Pa, it must be pre-converted before using the converter, or the result will be silently incorrect.
- **`TMYGenerator` does not convert units**: it preserves the source-file values as-is throughout the whole statistical process; conversion to EPW units happens only in `HourlyEPWConverter`, which allows chaining `TMYGenerator.export_tmy()` → `HourlyEPWConverter` without loss or double conversion.
- **Column-name compatibility**: if the `col_*` values used in `TMYGenerator` match `HourlyEPWConverter`'s defaults, `export_tmy()` automatically restores those names and the resulting CSV is directly compatible with `HourlyEPWConverter` without any additional `column_mapping`.
- **`cdf_method='hourly'` is computationally expensive** compared to `'daily'`; for long datasets (>10 hourly years) `cdf_method='daily'` combined with `hourly_file_path` is recommended, so as not to lose hourly resolution in the final assembly/smoothing.
- **`data_frequency='daily'` is incompatible with `cdf_method='hourly'`** (there is no hourly data to analyze).
- **Session persistence is enabled by default** (`save_session=True`) across almost the entire public API: it automatically generates `.pkl`/`.json` files next to the input data — keep this in mind in CI/test workflows to avoid cluttering working directories (it can be disabled with `save_session=False`).
- **`besos`/`eppy` are needed only for `degree_hours.extract_setpoints_from_idf()`** (reading setpoints from an IDF) — the rest of the package works without them.
- The time zone in `convert_met_to_epw` is approximated as `round(longitude/15)` (nominal solar time zone), which may differ from the real civil time zone of some countries (e.g., Spain uses CET/CEST despite being geographically closer to UTC+0).

---

## 14. References

- Hall, I.J., Prairie, R.R., Anderson, H.E., Boes, E.C. (1978). *Generation of Typical Meteorological Years for 26 SOLMET Stations*. Sandia Laboratories, SAND78-1601.
- Wilcox, S., Marion, W. (2008). *Users Manual for TMY3 Data Sets*. NREL/TP-581-43156, National Renewable Energy Laboratory.
- Finkelstein, J.M., Schafer, R.E. (1971). "Improved goodness-of-fit tests." *Biometrika*, 58(3), 641–645.
- Sawaqed, N.M., Zurigat, Y.H., Al-Hinai, H. (2005). "A step-by-step application of the Sandia method in developing a typical meteorological year for different climatic zones of Oman." *Energy Conversion and Management*, 46(4), 633–646.
- Roudsari, M.S., Pak, M. (2013). "Ladybug: a parametric environmental plugin for Grasshopper to help designers create an environmentally-conscious design." *Proceedings of BS2013*.
- Official **EPW** (EnergyPlus Weather File) format documentation — *Auxiliary Programs / Weather Converter Program*, U.S. Department of Energy.
- Spanish Building Technical Code (CTE), Basic Document HE — `.met` reference climate files (LIDER/CALENER), Ministry of Transport, Mobility and Urban Agenda (Spain).
- Ineichen, P., Perez, R. (2002). "A new airmass independent formulation for the Linke turbidity coefficient." *Solar Energy*, 73(3), 151–157. *(clear-sky model underlying `pvlib.location.Location.get_clearsky`, used by `ClimateProcessor`)*
- Perkins, S.E., Alexander, L.V. (2013). "On the measurement of heat waves." *Journal of Climate*, 26(13), 4500–4517. *(conceptual basis for the local-percentile heatwave detection implemented in `EpwTrendAnalyzer`)*

---

## 15. License

MIT
