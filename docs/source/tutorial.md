# Tutorial notebook

The original standalone tutorial notebook is no longer versioned in this
repository. The runnable notebook-based walkthrough is now the case-study
notebook documented in {doc}`tutorial_case_study`.

- **Rendered notebook**: {doc}`tutorial_case_study` (next page).
- **Location in the repository**: `docs/source/jupyter_notebooks/` for the
  case-study notebook and its data, which are committed together so they can
  be executed standalone from GitHub.

## What it covers

The notebook reproduces, end-to-end, the same pipeline used for the Seville
case study (see {doc}`article_context` and `generating epws seville.py` at the
repository root), using data files that are already bundled in this
repository so every cell can be executed without any external download:

1. **Setup & sample data** — locates the repository root and inspects the
   input hourly series.
2. **`TMYGenerator`** ({func}`sandia_step_1` … `sandia_step_7` internally via
   `generate_tmy()`) — generates a Typical Meteorological Year with the
   Sandia method, `cdf_method='daily'` + `hourly_file_path` for fast-but-full
   resolution, and sequential persistence filtering. Includes validation
   tables (`generate_full_summary()`) and diagnostic plots.
3. **`HourlyEPWConverter`** — exports the TMY to a final `.epw` file using an
   existing EPW as the geographic/time-zone template.
4. **`DegreeHoursCalculator`** — computes heating/cooling degree-hours for the
   generated TMY against a real EnergyPlus IDF model (`SF_Detached_D_min_South.idf`),
   with setpoint visualization and Excel export.
5. **`EpwBatchAnalyzer`** — compares the generated TMY against a real
   historical year (from `longterm_epw/`) side by side, with multiple
   hour-of-day scenarios.
6. **`EpwTrendAnalyzer`** (bonus) — fits per-city and global fixed-effects
   warming trends over the Seville subset of the `longterm_epw/` collection
   (2005-2025, illustrating how missing years are reported in the coverage
   table), plus the boxplot-per-year visual-QA figure via
   `build_boxplot_figure()`.
7. **`EpwGroupTrendAnalyzer`** (bonus) — batch heating/cooling degree-hour
   trend analysis over the *entire* `longterm_epw/` folder, automatically
   classified by filename into 5 independent Spanish climates (Granada,
   León, Madrid, Málaga, Seville), each analysed fully independently, never
   pooled together.

## Running it

```bash
pip install -e ".[docs]"
pip install jupyter
jupyter notebook examples/tutorial_pyweatherfiles.ipynb
```

```{note}
The notebook uses `save_session=False` in most calls to avoid littering the
repository with `.pkl`/`.json` session files on every run. In real projects
the default `save_session=True` is recommended for full reproducibility (see
{doc}`full_reference_en`, section 10, "session_manager").
```

