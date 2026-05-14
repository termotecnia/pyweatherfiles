# AGENTS.md

## Big picture (what this repo is)
- `pyweatherfiles` is a weather-data toolkit centered on **TMY generation** (`pyweatherfiles/tmy.py`) plus EPW/MET conversion and degree-hours analysis.
- The package API exported in `pyweatherfiles/__init__.py` is minimal: `TMYGenerator` and `DegreeHoursCalculator`; many workflows still import module paths directly.
- Real project usage is script-driven from repo root (see `generating epws seville.py`, `tmy_seville_revision.py`, `analysis_scripts/*.py`) and depends on local data files in root.

## Main components and boundaries
- `pyweatherfiles/tmy.py`: monolithic `TMYGenerator` implementing Sandia-style 7-step pipeline (`sandia_step_1_*` ... `sandia_step_7_*`) plus deprecated wrappers (`step_1_*` ...).
- `pyweatherfiles/degree_hours.py`: `DegreeHoursCalculator` (single EPW) + `EpwBatchAnalyzer` (multi-EPW comparative tables, MultiIndex columns).
- `pyweatherfiles/hourly_epw_converter.py`: converts cleaned hourly CSV/XLSX to EPW (`HourlyEPWConverter`, `BatchHourlyEPWConverter`).
- `pyweatherfiles/met_epw_converter.py`: function-style MET<->EPW conversion (`convert_met_to_epw`, `convert_epw_to_met`).
- `pyweatherfiles/session_manager.py`: shared persistence helpers writing `.pkl` + `.json` session snapshots near inputs.

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
- Docs script exists (`dist_build_docs.bat`) but current repo has no `docs/` folder; treat as optional/stale unless docs are restored.
- Branch sync helper: `sync_branch.bat <branch>` runs `git clean -fd` (destructive for untracked files).
- There is no `tests/` directory or CI config in repo; validation is done via example/revision scripts and generated reports.

## Project-specific patterns (follow these)
- Keep backward compatibility in `tmy.py`: new `sandia_step_*` methods coexist with deprecated aliases and compatibility properties.
- Many public methods print rich diagnostics to console and store intermediate DataFrames in `validation_step*` attributes; do not remove these side effects lightly.
- Proximity step API is configurable: `sandia_step_3_proximity_ranking(normalization_method='std', normalization_weights=None)`.
- For `normalization_method='weighted'`, use exactly 4 keys in `normalization_weights`: `t_mean`, `t_median`, `ghi_mean`, `ghi_median`; all weights must be >= 0 and sum to 1.0.
- Backward compatibility: legacy `'sawaqed'` is accepted only as deprecated alias and internally mapped to `'weighted'` (warning emitted).
- Session persistence is expected behavior (`save_session=True` defaults in core classes/functions) and produces files like `TMYGenerator_*.pkl/.json`.
- Typical scripts are executed from repo root and use relative dataset paths (e.g., `Sevilla_Definitivo_para_convertir_a_epw.xlsx`, `SF_Detached_*.idf`).

## External integrations / dependency caveats
- Hard dependency in code: `ladybug-core` (EPW read/write) for converters/comparators/degree-hours.
- Optional-but-used paths: `pvlib` (`climate_processor.py`), `tabulate` (`epw_comparator.py`), `besos` and `eppy` for IDF parsing in degree-hours workflows.
- `pyproject.toml` currently lists only pandas/numpy/scipy/matplotlib/openpyxl; missing runtime deps are handled by runtime `ImportError` in several modules.

## Fast start for agents
- For TMY work, start from `examples/using_tmy_generator.py` and `generating epws seville.py` to replicate real parameters/mappings.
- For degree-hours work, start from `examples/degreehours simple.py` and `examples/degreehours batch.py`.
- For regression analysis, use `analysis_scripts/verify_new_tmy.py` and `tmy_seville_revision.py` outputs as baseline artifacts.
