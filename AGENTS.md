# AGENTS.md

> A general code-review report (duplication, architecture, test coverage, etc.) is kept at
> [`INFORME_REVISION_GENERAL.md`](INFORME_REVISION_GENERAL.md) (Spanish) — check it before starting
> any non-trivial refactor, it likely already documents the tradeoffs involved.

## Big picture (what this repo is)
- `pyweatherfiles` is a weather-data toolkit centered on **TMY generation** (`pyweatherfiles/tmy.py`) plus EPW/MET conversion, degree-hours analysis, multi-year climate-trend analysis, EPW comparison and hourly-series gap-filling.
- The package API exported in `pyweatherfiles/__init__.py` is: `TMYGenerator`, `DegreeHoursCalculator`, `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig`. Everything else (`hourly_epw_converter`, `met_epw_converter`, `climate_processor`, `epw_comparator`, `epw_utils`, `EpwBatchAnalyzer`/`EpwGroupTrendAnalyzer` from `degree_hours`) is imported explicitly from its submodule, e.g. `from pyweatherfiles import hourly_epw_converter`.
- Real project usage is script-driven from repo root (see `generating epws seville.py`, `analysis_scripts/*.py`) and depends on local data files in root. `README.md`/`README_ES.md` are the authoritative, exhaustive technical reference (kept in sync with the code); prefer them over this file for API/formula details.

## Main components and boundaries
- `pyweatherfiles/tmy.py` (~4.1k lines): monolithic `TMYGenerator` implementing Sandia-style 7-step pipeline (`sandia_step_1_*` ... `sandia_step_7_*`) plus deprecated wrappers (`step_1_*` ...).
- `pyweatherfiles/degree_hours.py` (~2.6k lines): `DegreeHoursCalculator` (single EPW) + `EpwBatchAnalyzer` (multi-EPW comparative tables, MultiIndex columns) + `EpwGroupTrendAnalyzer` (whole-folder degree-hours trend analysis, classified by filename via `epw_utils.classify_epw_files`).
- `pyweatherfiles/epw_trend_analyzer.py` (~1.8k lines): `EpwTrendAnalyzer`/`TrendConfig`/`OutputConfig` — multi-year temperature-trend analysis (warming, heatwaves) with a global fixed-effects model across cities. Conceptually overlaps with `EpwGroupTrendAnalyzer` (both classify/trend EPW collections by city+year) — see `INFORME_REVISION_GENERAL.md` §3.3 before adding features to either.
- `pyweatherfiles/hourly_epw_converter.py`: converts cleaned hourly CSV/XLSX to EPW (`HourlyEPWConverter`, `BatchHourlyEPWConverter`).
- `pyweatherfiles/met_epw_converter.py`: function-style MET<->EPW conversion (`convert_met_to_epw`, `convert_epw_to_met`).
- `pyweatherfiles/epw_field_utils.py`: low-level EPW helpers shared by the two converters above (`calculate_atmos_pressure`, `set_epw_values`/`get_epw_values` for Ladybug's point-in-time offset, `UNUSED_EPW_FIELDS`/`neutralize_unused_epw_fields` for the 15 EnergyPlus-unused fields). Extracted from what used to be near-identical duplicated code in both converters — see `INFORME_REVISION_GENERAL.md` §3.1/Fase 1 (now done). `hourly_epw_converter.py`/`met_epw_converter.py` keep thin backward-compatible method/function wrappers delegating to it.
- `pyweatherfiles/climate_processor.py`: `ClimateProcessor` — pre-processing (cleaning/reindexing/gap-filling) of raw hourly station series, upstream of `tmy`/`hourly_epw_converter`. Not exported in `__init__.py`; requires optional `pvlib`.
- `pyweatherfiles/epw_comparator.py`: free functions to compare two EPW files (`compare_epw_files`, `create_comparison_hourly_dataframe`, ...). Not exported in `__init__.py`; requires optional `tabulate`.
- `pyweatherfiles/epw_utils.py`: small shared helper (`classify_epw_files`) used by `EpwGroupTrendAnalyzer` to classify EPWs into `{group: {year: path}}` from filenames.
- `pyweatherfiles/session_manager.py`: shared persistence helpers writing `.pkl` + `.json` session snapshots near inputs; reused by `tmy`, `degree_hours`, `hourly_epw_converter`, `met_epw_converter`, `epw_comparator`.

## Data flow conventions that matter
- TMY flow is: load/mapping -> FS ranking -> proximity reranking -> persistence filtering -> assemble TMY -> smoothing -> export.
- `TMYGenerator.generate_tmy()` defaults to `persistence_method='sequential'`; alternative score-based persistence exists.
- `TMYGenerator.generate_tmy()` now exposes proximity controls: `proximity_normalization_method='std'` and `proximity_normalization_weights=None`.
- Supported proximity normalization methods are: `std`, `long_term_mean`, `range`, `weighted`.
- Daily vs hourly is a first-class switch: `data_frequency` and `cdf_method` must be consistent (`daily` data cannot use hourly CDF).
- Input column names are frequently non-standard; pass explicit mapping (`datetime_col`, `col_temp`, etc.) and preserve exact names/spaces from source files.
- Hourly smoothing in Step 7 only runs when hourly data is available (`df_hourly` or `hourly_file_path`); otherwise it is skipped.

## Developer workflows (discoverable, current repo)
- Build package: `dist_build_package.bat` (cleans `dist/`, `build/`, `*.egg-info`, then runs `python -m build`).
- Upload to TestPyPI/PyPI: `dist_upload_test.bat`, `dist_upload.bat` (expect `.pypirc` + `dist/*`).
- Docs: `docs/` exists (Sphinx + myst-nb + Furo, config at `docs/source/conf.py`). Build locally with `pip install -e ".[docs]"` then `dist_build_docs.bat`; published on Read the Docs via `.readthedocs.yaml`. Tutorial notebook lives at `examples/tutorial_pyweatherfiles.ipynb` (single source of truth, copied into `docs/source/` at build time).
- Branch sync helper: `sync_branch.bat <branch>` runs `git clean -fd` (destructive for untracked files).
- **Tests**: `tests/` now exists (pytest, extra `test` in `pyproject.toml`: `pip install -e ".[test]"` then `python -m pytest tests/`). Coverage is still partial — only the pure physical/EPW-plumbing functions and the two EPW-writing pipelines have regression tests so far (see `INFORME_REVISION_GENERAL.md` §6 Fase 2, "Nivel 1"/"Nivel 2"); `tmy.py`/`degree_hours.py`/`epw_trend_analyzer.py` core logic is still untested. No CI config yet (Fase 3, still pending).
- **CI**: `.github/workflows/ci.yml` runs on push to `main` and on every pull request — `pytest` across Python 3.10-3.13 on Ubuntu plus one Windows job (3.12), then a package-build sanity job (`python -m build`). `requires-python` was bumped from the stale `>=3.7` (EOL, incompatible with current pandas/numpy) to `>=3.10`.

## Project-specific patterns (follow these)
- Keep backward compatibility in `tmy.py`: new `sandia_step_*` methods coexist with deprecated aliases and compatibility properties.
- Many public methods print rich diagnostics to console and store intermediate DataFrames in `validation_step*` attributes; do not remove these side effects lightly.
- Proximity step API is configurable: `sandia_step_3_proximity_ranking(normalization_method='std', normalization_weights=None)`.
- For `normalization_method='weighted'`, use exactly 4 keys in `normalization_weights`: `t_mean`, `t_median`, `ghi_mean`, `ghi_median`; all weights must be >= 0 and sum to 1.0.
- Backward compatibility: legacy `'sawaqed'` is accepted only as deprecated alias and internally mapped to `'weighted'` (warning emitted).
- Session persistence is expected behavior (`save_session=True` defaults in core classes/functions) and produces files like `TMYGenerator_*.pkl/.json`.
- Typical scripts are executed from repo root and use relative dataset paths (e.g., `Sevilla_Definitivo_para_convertir_a_epw.xlsx`, `SF_Detached_*.idf`).

## External integrations / dependency caveats
- Hard dependency in code: `ladybug-core` (EPW read/write) for converters/comparators/degree-hours. Import is guarded with a custom `ImportError` message in every module that needs it.
- Optional-but-used paths, each guarded with `try/except ImportError`: `pvlib` (`climate_processor.py`, extra `climate`), `tabulate` (`epw_comparator.py`, extra `comparator`), `besos`+`eppy` (IDF setpoint parsing in `degree_hours.py`, extra `energyplus`), `accim` (accent-sanitization of IDF paths, optional extra `accents`).
- `pyproject.toml` mandatory deps: `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn`, `openpyxl`, `ladybug-core`, `pyyaml`. Optional extras: `docs`, plus `climate`/`comparator`/`energyplus`/`accents` (and a combined `full`) for the modules above.

## Fast start for agents
- For TMY work, start from `examples/using_tmy_generator.py` and `generating epws seville.py` to replicate real parameters/mappings.
- For degree-hours work, start from `examples/degreehours simple.py` and `examples/degreehours batch.py`.
- For regression analysis, use `analysis_scripts/verify_new_tmy.py` outputs as baseline artifacts (note: `tmy_seville_revision.py`, previously referenced here, no longer exists in the repo).
