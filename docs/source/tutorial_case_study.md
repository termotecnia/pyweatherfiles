# Case study: Seville and Madrid (real data)

A second, more extensive tutorial notebook reproduces, end to end and using
**real, non-synthetic data** for two Spanish provincial capitals (Seville and
Madrid), the complete case-study workflow described in the accompanying
manuscript (`Manuscript_TMY_v02.md`, repository root):

```{eval-rst}
:download:`Download tutorial_pyweatherfiles_case_study.ipynb <jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb>`
```

- **Rendered notebook**: {doc}`jupyter_notebooks/tutorial_pyweatherfiles_case_study` (next page).
- **Location in the repository**: `docs/source/jupyter_notebooks/`. Unlike
  the other tutorial notebook (whose copy under `docs/source/` is generated
  at build time, see {doc}`tutorial`), this notebook **and its input data**
  (`data/`: the Seville/Madrid multi-year hourly series, the official `.met`
  regulatory files, and the EPW templates used for header metadata, ~66 MB
  in total) are committed together, version-controlled, in this single,
  self-contained folder — so the whole case study can be cloned from GitHub
  and executed standalone, without depending on any of the repository's
  other (git-ignored) datasets.

## What it covers

1. **Part 0 — Setup and input data.** Locates the notebook's own directory,
   defines the input files of the two case-study cities, and runs a
   pre-flight check of their column names
   (`TMYGenerator.check_input_expectations`).
2. **Part 1 — Typical Meteorological Year generation** (`TMYGenerator`):
   Seville generated **step by step** (all seven `sandia_step_*` methods,
   with the full `validate_*`/`plot_*` diagnostic API) and then **single-call**
   (`generate_tmy()`), cross-checked against the step-by-step result via
   `compare_tmy_versions`; Madrid generated with the single-call method only.
3. **Part 2 — Conversion to EPW format**: the three climate scenarios of the
   manuscript's simulation battery — *historical* (`HourlyEPWConverter`, one
   EPW per available year), *typical-year* (same converter, applied to the
   generated TMY), and *regulatory* (`met_epw_converter.convert_met_to_epw`
   on the official Spanish `.met` reference file) — for both cities.
4. **Part 3 — Degree-hours and climate-trend analysis**
   (`pyweatherfiles.degree_hours`): a single-file warm-up with
   `DegreeHoursCalculator`, then a full multi-year batch analysis across both
   cities with `EpwGroupTrendAnalyzer` (per-city and global fixed-effects
   linear trends, the library's native overview grid, and a manuscript-style
   pooled boxplot figure).
5. **Part 4 — Conclusions and further reading.**

## Running it

```bash
pip install -e ".[docs]"
pip install jupyter
jupyter notebook docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb
```

```{note}
During execution, generated exports and EPW files are written only to
`case_study_output/`, next to the notebook. Session snapshots are disabled so
the six tracked files under `data/` are never modified. The final notebook
cell removes `case_study_output/` after a successful run, leaving the
repository with only the notebook and its required input data.
```

```{tip}
For the five-city, whole-`longterm_epw/`-folder version of the Part 3
analysis (Granada, León, Madrid, Málaga, Seville, 2005-2025), see
`analysis_scripts/climate_evolution_trend.py` at the repository root.
```

