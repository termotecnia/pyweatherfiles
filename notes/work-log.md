---
aliases:
  - Work log
tags:
  - pyweatherfiles
  - work-log
---
# Work log
Record concise work sessions here. Add each entry at the top using [[notes/templates/daily-note|the daily note template]]. Keep durable technical details in [[decisions|Decisions]], [[questions|Open questions]], or the canonical documentation.
---
# 2026-09-21 — Documentation cleanup: single tutorial, no article references, Read the Docs theme

- Objective: leave `docs/source/` with exactly one tutorial (the case-study notebook), remove every article/manuscript reference from the repository except that notebook, drop the local docs-build instructions from the user-facing documentation, and switch the HTML theme to Read the Docs.
- Decision: [[decisions#D-006 — One tutorial only, no article references in the repository, Read the Docs theme|D-006]].
- Files:
  - Deleted: `docs/source/tutorial.md`, `docs/source/tutorial_case_study.md`, `docs/source/article_context.md`, `ARTICLE_CONTEXT_SEVILLA.md`.
  - `docs/source/index.md` — toctree reduced to `installation`/`quickstart`/`jupyter_notebooks/tutorial_pyweatherfiles_case_study` + `full_reference_en`/`full_reference_es` + `api/modules`; intro and tip rewritten around the single notebook.
  - `docs/source/quickstart.md` — `{doc}`article_context`` and `{doc}`tutorial`` replaced by a link to the notebook.
  - `docs/source/installation.md` — "Building this documentation locally" section removed; replaced by the `[full]` extra, a short verification snippet and next-step links.
  - `docs/source/conf.py` — docstring rewritten (no build instructions, no article wording), `_copy_tutorial_notebook()` and the `shutil` import removed (`examples/` no longer exists), `html_theme = "sphinx_rtd_theme"` with RTD-specific `html_theme_options` + `html_context` (Edit on GitHub) replacing Furo's `source_repository` options, `sphinx_rtd_theme` added to `extensions`.
  - `pyproject.toml` — `docs` extra: `furo` → `sphinx-rtd-theme>=3.1` (floor chosen because 3.0.x and earlier declare `sphinx<9`, which would silently downgrade Sphinx on a clean environment). `.readthedocs.yaml` comment updated. `dist_build_docs.bat` — dependency check now includes `sphinx_rtd_theme`.
  - `.gitignore` — dropped `examples/tutorial_output/` and the stale NOTE about `examples/tutorial_pyweatherfiles.ipynb` being the single source of truth.
  - `README.md`/`README_ES.md` — banner now links the case-study notebook (the `examples/` path was broken) and no longer points to `docs/source/installation.md` for the local build; all "article"/"artículo" wording (§6.5, §7.4, §8, §10) reworded to "report"/"methods section"/"Seville-Madrid case study".
  - `AGENTS.md` (docs bullet), `Home.md` (start-here links, Context and results, MyST-wrapper warning), `notes/references.md`, `notes/obsidian-tutorial.md`, `TODO.md`/`TODO_ES.md` (task 3/4) — stale tutorial paths and article links removed.
  - Package docstrings: `epw_comparator.py` (L353), `session_manager.py` (L16), `degree_hours/group_trend_analyzer.py` (×3), `epw_trend_analyzer/__init__.py`, `epw_trend_analyzer/_plotting.py` — "manuscript"/"article" wording neutralized.
- Finding: `examples/` does not exist in the repository, so `examples/tutorial_pyweatherfiles.ipynb` was a broken reference in ~10 places (both READMEs, `AGENTS.md`, `conf.py`, `TODO*.md`, `.gitignore`); `Manuscript_TMY_v02.md` was likewise referenced but absent. `sphinx-rtd-theme` 3.1.0 is required for Sphinx 9.x (earlier 3.0.x pins `sphinx<9`).
- Validation:
  - `python -m sphinx.ext.apidoc --force -o docs/source/api pyweatherfiles` then a clean `sphinx -b html -q` → **0 warnings**, build succeeded; generated pages are exactly `index`, `installation`, `quickstart`, `full_reference_en`, `full_reference_es`, `genindex`, `py-modindex`, `search` + `jupyter_notebooks/tutorial_pyweatherfiles_case_study.html`. RTD theme confirmed in the output (`wy-nav-side`, `_static/css/theme.css`).
  - Repo-wide grep for `article_context|ARTICLE_CONTEXT|Manuscript_TMY|tutorial_case_study|examples/tutorial_pyweatherfiles|furo` → only historical work-log entries remain (deliberately not rewritten) and the notebook's own base64 image payload (false positive).
  - `python -m pytest tests/test_epw_comparator.py tests/test_session_manager.py tests/test_degree_hours_helpers.py tests/test_epw_utils.py -q` → 80 passed (docstring-only code edits; all touched modules import cleanly).
  - Follow-up after the first push (commit `ce8560e`): the `docs` extra pin was raised from `>=2.0` to `>=3.1`; `pip install -e ".[docs]" --dry-run` resolves to `sphinx-rtd-theme` 3.1.0 with `sphinx` 9.1.0 and `pip check` reports no broken requirements.
- Next step: once on Read the Docs, confirm the RTD-themed site renders the notebook and that the old `tutorial*`/`article_context` URLs are gone.

---
# 2026-09-20 — Docs build script now bootstraps missing Sphinx/MyST dependencies

- Objective: make `dist_build_docs.bat` resilient when the active Python environment does not yet have the documentation toolchain installed.
- Files:
  - `dist_build_docs.bat` — now checks for `sphinx` and `myst_nb` before building; if either is missing, it installs the `docs` extra from `pyproject.toml` and re-checks before continuing.
  - `docs/source/installation.md` — notes that the helper can auto-install the `docs` extra when needed.
- Finding: the reported failure was caused by running the build in an environment without `myst_nb`, even though `myst_nb` is declared in the `docs` extra.
- Validation: build-script logic updated; documentation guidance kept consistent with the new behavior.
- Next step: rerun `dist_build_docs.bat` in the target environment; if installation still fails, inspect the `pip` output for the underlying dependency issue.

---
## 2026-09-20 — Final case-study notebook consolidated for repository release

- Objective: keep one standalone, GitHub-runnable case-study notebook before PyPI release preparation, retain only its six required inputs, and leave no generated files after its normal execution.
- Files:
  - `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb` — renamed from `_v03`; now discovers its own data directory from either the repository root or notebook directory, validates the exact six inputs, disables every session-capable call with `save_session=False`, and ends with a guarded cleanup cell that deletes only its sibling `case_study_output/` directory.
  - `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v00.ipynb`, `_v01.ipynb`, `_v02.ipynb`, and the tracked notebook checkpoint — removed; the obsolete data checkpoint and pre-existing generated `case_study_output/` were also removed.
  - `AGENTS.md` and `docs/source/tutorial_case_study.md` — updated for the final filename and ephemeral-output behaviour.
- Finding: the six version-controlled inputs are exactly `ESP_Madrid.082210_IWEC.epw`, `ESP_Sevilla.083910_SWEC.epw`, `madrid.met`, `Madrid_hourly_data.xlsx`, `seville.met`, and `Seville_hourly_data.xlsx`; no additional notebook-local file is required.
- Validation: structural checks compiled every code cell, verified both supported launch directories, exact input inventory, all eleven explicit `save_session=False` runtime calls, and the cleanup path guard. Full `jupyter nbconvert --execute --inplace` run completed successfully: 115 cells / 72 code cells, 0 stored errors, and the stored final-cell output confirms removal of `case_study_output/`; the directory is absent afterward.
- Next step: stage the notebook rename/deletions and the six existing tracked inputs, then continue the PyPI-release readiness review.

---
## 2026-09-20 — Diagnostics return DataFrames; case-study notebook v03 cleaned up and re-run

- Objective: make the case-study notebook readable — stop printing wide DataFrames as fixed-width text, clarify what `validate_step_1_data_loading()` is for, drop references to code outside the package, bring the NCDH narrative up to date with [[decisions#D-003 — NCDH is a cooling-potential (deficit) indicator, not a classic CDH restricted to night hours|D-003]], and get rid of the matplotlib "Font 'rm' does not have a glyph for '\ufdff'" warnings in the degree-hours figure.
- Decision: [[decisions#D-005 — `validate_*`/`summarize_*` return DataFrames instead of printing them|D-005]]. Every `tmy` diagnostic returns its table (and stores it in a `validation_*` attribute) and prints only a short summary; `validate_persistence_selection()` is the deliberate exception (narrow per-month tables, read as a sequential report).
- Files:
  - `pyweatherfiles/tmy/_validation.py` — `validate_step_1_data_loading(verbose=True)` rewritten around the three guarantees of Step 1 and now returns a **coverage table** (`Records`/`Expected_Records`/`Missing_Records`/`NaN_Values`/`Years`/`Missing_Years`/`Interpolated_Years`/`Negative_GHI_DNI_Wind`), storing the `describe()` tables transposed in `validation_step1_hourly_stats`/`validation_step1_daily_stats`; `validate_fs_calculation` and `validate_full_ranking_for_month` no longer dump `head().to_string()`; `summarize_fs_results(verbose=True)` returns `validation_step3_proximity_ranking`; `validate_step_4_final_tmy(verbose=True)` returns `validation_step6_tmy_composition` and stores `validation_step6_tmy_final_stats` (its docstring now points to `generate_full_summary()` as the preferred consolidated audit).
  - `pyweatherfiles/tmy/_data_loading.py` — Step 1 records `self.source_years` (the calendar years present in the *source* file) before the resampling rebuilds the grid.
  - `pyweatherfiles/tmy/_core.py` — new attributes initialised and documented (`source_years`, `validation_step1_*`, `validation_step6_tmy_final_stats`).
  - `tests/test_tmy_validation.py` — `TestValidateStep1DataLoading`/`TestValidateStep4FinalTmy`/`TestSummarizeFsResults` rewritten against the returned DataFrames instead of the old console text, plus a new test for the interpolated-year detection (40 tests in the file, +3).
  - `README.md`/`README_ES.md` §3.2 and §3.10 (bilingual), `AGENTS.md` (project-specific patterns + the stale `tutorial_pyweatherfiles_case_study.ipynb` path corrected to `_v03`), `notes/decisions.md` (D-005), `notes/questions.md` (open question about Step 1's unbounded interpolation).
  - `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v03.ipynb` — 16 cells rewritten, 1 deleted (`validate_step_4_final_tmy()`, superseded by `validation_full_summary`), 2 display cells inserted (`full_ranking_jan.head(10)`, `fs_breakdown_example.head()`); `analyze_selection(..., verbose=False)` so the audit renders as a table; every reference to non-package code removed (`analysis_scripts/climate_evolution_trend.py`, `generating epws seville.py`, `INFORME_REVISION_GENERAL.md`) together with the stale "`# TODO(dev)` placeholders" note; Part 3 rewritten for the corrected NCDH (potential `max(0, 25 - T)`, 00:00-08:00 inclusive, Jul-Sep, `invert_cooling=True`, and the fact that a *decreasing* trend means *less* night-cooling potential); the 48 U+FDFF characters that had replaced `°`/`·` in the `plot_overview_grid` labels restored.
- Finding: the Seville series has **no 2020**, but Step 1's `resample('h').mean().interpolate('linear')` silently rebuilds it as a linear ramp; the reconstructed year then has 100% completeness, so Step 2's `completeness_threshold` cannot drop it and it is counted among the 21 candidate years (the FS ranking never selects it, but by luck rather than by design). This is exactly what makes the new `Interpolated_Years` column worth having — the notebook, the README §3.2 caveat and `notes/questions.md` now document it.
- Validation:
  - `python -m pytest tests/` → **435 passed** in 404 s (432 before + 3 new in `tests/test_tmy_validation.py`, which now has 40).
  - Notebook re-executed in place (`jupyter nbconvert --execute --inplace`, ~50 min): 113 cells, 71 code cells, 19 figures, **0 errors**, 0 unexecuted cells, 0 remaining U+FDFF characters and **no "does not have a glyph" warning** in any stored output.
  - Trend results unchanged and consistent with the new text: HDH20 slope negative (Madrid -328 °C·h/yr, p=0.013), CDH25 positive (Madrid +105, p=0.018), NCDH25 negative (Madrid -46.4, p=0.009; global fixed-effects -27.0 °C·h/yr, p=0.026).
- Incident note: the IDE's foreground terminal stopped returning output mid-session (it kept echoing an old command); every check had to be run through background terminals writing to a file. Also re-confirmed the 2026-09-19 note: never pass non-ASCII (`°`, `·`, backticks) through inline PowerShell — it silently strips them; all notebook edits were applied with UTF-8 Python patch scripts.
- Next step: none pending. If the notebook is ever re-run, remember it takes ~50 min end to end and rewrites `case_study_output/`.
---
## 2026-09-19 — Step 7 now smooths by default (`s_factor='auto'`)

- Objective: implement option (b) of the previous session's open question — make Step 7's default an *effective* smoothing instead of the no-op `s_factor=0.0` — without regressing any existing behaviour.
- Decision: [[decisions#D-004 — Step 7 smooths by default, with a variance-normalized `s_factor='auto'`|D-004]]. New default `s_factor='auto'` → `s = auto_s_strength * n * var(y)` per variable (`auto_s_strength = 0.02`, exposed as `TMYGenerator.AUTO_S_STRENGTH`). SciPy's `s=None` was explicitly rejected: it is unit-dependent and, on real Seville data, flattened the wind-speed series (12 h window swing 3.61 → 0.85 m/s) while barely smoothing temperature.
- Files:
  - `pyweatherfiles/tmy/_assembly_smoothing.py` — new `AUTO_S_STRENGTH` class attribute and `_resolve_s_factor()` helper; `_apply_smoothing()` gained `auto_s_strength`, validates its arguments fail-fast, stores the effective per-junction parameters in `smoothing_config` (including the numeric `s` used per variable in `s_factor_auto`), remembers its arguments in `_last_smoothing_kwargs`, and translates FITPACK's cryptic `maxit ... s too small` `UserWarning` into a readable one-line diagnostic; `sandia_step_7_smooth_junctions()` gained `auto_s_strength` and a public `smoothing_config`; renamed the loop variables that shadowed `hours`/`s_factor`.

  - `pyweatherfiles/tmy/_core.py` — `generate_tmy()` now forwards `smoothing_hours`/`smoothing_s_factor`/`smoothing_auto_s_strength`/`smoothing_config` (it previously called Step 7 with no arguments at all).
  - `pyweatherfiles/tmy/_validation.py` — `correct_selection_by_temperature(regenerate=True)` re-smooths with `_last_smoothing_kwargs` instead of falling back to the defaults.
  - `pyweatherfiles/tmy/_compat.py` — deprecated `step_4_create_and_smooth_tmy()`/`_smooth_tmy_curve_fitting()` aligned with the new default.
  - `pyweatherfiles/tmy/_plotting.py` — `plot_smoothing_comparison()` handles a non-numeric `s_factor` in the title and reports the computed `s` per variable.
  - `tests/test_tmy_smoothing.py` (**new**, 18 tests) — default actually modifies the TMY, only junction windows change, junction discontinuities shrink, GHI/DNI untouched, annual mean preserved, `s_factor=0.0` still an exact no-op, `None`/explicit numbers, `ValueError`s, `smoothing_config` overrides, `generate_tmy()` forwarding, regeneration reuse, plot title.
  - `README.md`/`README_ES.md` §3.7 + §3.8, `AGENTS.md`, `INFORME_REVISION_GENERAL.md` (nota de cobertura de Fase 2).
  - Notebooks re-executed in place so their stored outputs match the new default: `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v01.ipynb` (74 code cells, 22 figures, 0 errors; Step 7 markdown also rewritten) and `examples/tutorial_pyweatherfiles.ipynb` (23 code cells, 7 figures, 0 errors). Neither contains any `s_factor=0.0` line any more.
- Validation:
  - Parameter sweep on real Seville EPW junctions (`k ∈ [0.002, 0.1]`, Jan→Feb and Jul→Aug, T_air and wind): `k = 0.02` chosen as the best trade-off between removing the discontinuity and preserving the diurnal swing.
  - Full pipeline over 15 years of real Seville data: 126/8760 hours modified; mean junction jump in `T_air` 2.20 → 0.89 degC (max 5.00 → 2.09), `T_dew` 3.25 → 1.71; RMS deviation inside the windows 0.78 degC; annual mean `T_air` unchanged within 0.001 degC; `GHI`/`DNI` bit-identical.
  - `python -m pytest tests/` → **432 passed** in 504 s (414 before + 18 new); after the fail-fast validation and the FITPACK-warning translation, `tests/test_tmy_smoothing.py + test_tmy_package.py + test_tmy_plotting.py + test_tmy_validation.py` re-run → 112 and 31 passed respectively, with the raw SciPy warning no longer escaping (and absent from both notebooks' stored outputs).
- Incident note: a one-line PowerShell `python -c` edit corrupted the notebook (a backtick in `` `auto` `` was interpreted by PowerShell as an escape and written as a BEL control character, breaking the JSON). Repaired from a small file-based Python script; do not pass Markdown/backticks through inline PowerShell commands.
- Next step: none pending for Step 7. `examples/tutorial_pyweatherfiles_v01.ipynb` (the user's untracked working copy) was deliberately left untouched — re-run it the same way if its stored outputs matter.
---
## 2026-09-19 — Clarified why Step 7 smoothing looks like a no-op (`s_factor=0.0`)

- Objective: answer why `plot_smoothing_comparison(junctions_to_plot=[('T_air', 1)])` in the case-study notebook draws the raw and the smoothed series exactly on top of each other.
- Finding: not a bug. `s_factor` is forwarded verbatim to `scipy.interpolate.UnivariateSpline` as `s`, and the default `s_factor=0.0` means **exact interpolation** — the spline passes through every fitted point, so the values written back into the junction window equal the raw ones to machine precision (`tmy_final == tmy_raw`). The notebook's Step 7 markdown wrongly stated that `s_factor=0.0` "lets the method choose the spline smoothing factor automatically" (automatic is `s=None`).
- Files:
  - `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v01.ipynb` — corrected the Step 7 markdown, added a `{note}` admonition explaining the overlapping curves and how to get a visible smoothing, and reworded the `plot_smoothing_comparison` intro (line-level patch; stored outputs untouched).
  - `README.md` / `README_ES.md` §3.7 — new bullet spelling out the practical consequence of the default (bilingual).
  - `pyweatherfiles/tmy/_assembly_smoothing.py` — expanded the `s_factor` docstrings (`_apply_smoothing`, `sandia_step_7_smooth_junctions`) and added a one-off console hint when `s_factor == 0.0` and no `smoothing_config` is supplied.
  - `notes/questions.md` — recorded the open design question about the default.
- Validation:
  - Isolated check: `UnivariateSpline` over 1440 noisy hourly points -> `s=0.0` max|diff| 1.1e-14; `s=None` 2.54; `s=100` 0.79; `s=5000` 7.56.
  - Full pipeline on synthetic 6-year data: `s_factor=0.0` -> max|diff T_air| 7.1e-15 and 0 hours changed; `s_factor=None` and `s_factor=2000` -> max|diff| 1.40 degC over 126 hours (11 junctions x 12 h window).
  - `python -m pytest tests/test_tmy_plotting.py tests/test_tmy_package.py -q` -> 57 passed.
- Next step: decide (see [[questions|Open questions]]) whether the shipped default should remain a no-op or become an effective smoothing; if it changes, the case-study notebook's Step 7 wording must be revisited.
---
## 2026-09-14 — Fixed NCDH sign error and added summer-month filter

- Objective: fix a conceptual error in the night-cooling-potential (NCDH) indicator, spotted by Daniel/Rafa while auditing Leon in `fig3_overview_grid_by_city.png`: NCDH must be the degrees *missing* to reach 25 degC (`max(0, 25 - T)`, cooling potential/deficit), not the degrees *above* it (`max(0, T - 25)`, classic overheating CDH). Also add a calendar-month filter, restricted to July-September for this indicator, keeping the existing 00:00-08:00 (inclusive) night window.
- Files:
  - `pyweatherfiles/degree_hours/calculator.py` — `DegreeHoursCalculator._compute_dh`/`calculate()` gained `months` (calendar-month filter, ANDed with `hours`) and `invert_cooling` (flips the cooling formula to `max(0, SP_cooling - T)`) parameters.
  - `pyweatherfiles/degree_hours/group_trend_analyzer.py` — `EpwGroupTrendAnalyzer`'s `hours_scenarios` config now forwards `months`/`invert_cooling` per scenario.
  - `analysis_scripts/climate_evolution_trend_separate_climates.py` and `analysis_scripts/climate_evolution_trend.py` — the night scenario is now `night_potential_jul_sep` / `night_cooling_potential_25_jul_sep` (`hours=0-8` inclusive, `months=[7,8,9]`, `invert_cooling=True`); both scripts re-run end to end.
  - `analysis_scripts/export_hourly_degreehours_audit.py` — hourly audit column renamed `NCDH25_0_8h` -> `NCDH_25`, using the corrected formula.
  - `README.md` / `README_ES.md` — documented the new `months`/`invert_cooling` parameters (§6.3, §6.6, bilingual).
  - `tests/test_degree_hours_calculator_extra.py`, `tests/test_degree_hours_group_trend_analyzer.py` — new unit tests for `months`/`invert_cooling` (calculator + scenario forwarding).
- Validation:
  - Full suite: `python -m pytest tests/` -> 414 passed.
  - Hour-by-hour cross-check against the user-provided reference workbook (`analysis_scripts/leon_hourly_degreehours_audit_RMP.xlsx`, column `NCDH_25`): regenerated `analysis_scripts/leon_hourly_degreehours_audit.xlsx` matches exactly except for June (the reference draft used months>5/<10 i.e. Jun-Sep; the agreed final range is Jul-Sep only) — zero mismatches in Jul/Aug/Sep or outside hours 0-8.
  - Re-ran both `climate_evolution_trend_separate_climates.py` and `climate_evolution_trend.py`; NCDH now shows a physically sensible *decreasing* trend over time in every city (less night cooling potential as the climate warms), unlike the previous (incorrect) formula.
- Incident note: mid-session, the editor-integrated file-edit tools intermittently wrote stale/garbled buffers to disk, corrupting `pyweatherfiles/degree_hours/calculator.py` and `tests/test_degree_hours_calculator_extra.py` at least once each. Recovered via `git checkout --` (for files with no prior uncommitted changes) or by reconstructing from content already captured earlier in the same session, then re-applied every change through small, disk-only Python patch scripts (read/replace/write + `py_compile`) instead, verifying each step with `git diff`/`pytest`. No data was lost; flagging here in case the same tool instability recurs.
- Next step: none pending; the by-city figures/CSVs/summary in `analysis_scripts/` are already regenerated with the corrected formula.

---
## 2026-09-14 — Hourly audit export for Leon degree-hours
- Objective: create an auditable hourly export (HDH20/CDH25/NCDH25) to verify `fig3_overview_grid_by_city.png`, especially Leon.
- Files: `analysis_scripts/export_hourly_degreehours_audit.py`, `analysis_scripts/leon_hourly_degreehours_audit.xlsx`, this work log.
- Finding: NCDH is reproduced as cooling degree-hours constrained to 00:00-08:00 (`hours=range(0, 8)`, `mode='cooling'`), and yearly totals are directly recoverable from hourly sums.
- Validation: ran `python analysis_scripts/export_hourly_degreehours_audit.py --city leon`; `yearly_diff_vs_reference` shows zero differences for 2015-2025 vs `analysis_scripts/climate_trend_variables.csv`.
- Next step: replicate with other cities if needed (`--city seville`, `--city madrid`, etc.) or use the hourly sheet for manual spot checks.
---
## 2026-09-13 — Obsidian vault paths renamed to English
- Objective: replace the remaining Spanish and mixed-language vault paths with safe English names and repair all dependent references.
- Files: [[Home]], [[notes/README]], [[obsidian-tutorial]], this work log, [[decisions]], the templates, `AGENTS.md`, `.github/copilot-instructions.md`, and local Obsidian configuration.
- Decision: [[decisions#D-002 — Keep Obsidian vault documentation and paths in English|D-002]] now applies to vault paths as well as content; use lowercase ASCII `kebab-case` names.
- Validation: verified YAML frontmatter, wiki-link targets and headings, Obsidian configuration paths, and the Git rename detection.
- Next step: create new notes from [[notes/templates/daily-note|daily-note]] or [[notes/templates/decision-record|decision-record]].
---
## 2026-09-13 — Obsidian vault documentation translated to English
- Objective: align all Obsidian-facing documentation with the repository's English language convention.
- Files: [[Home]], [[notes/README]], [[obsidian-tutorial]], this work log, the supporting notes and templates, and `.github/copilot-instructions.md`.
- Decision: [[decisions#D-002 — Keep Obsidian vault documentation and paths in English|D-002]] establishes English prose, visible link labels, templates, and metadata for the vault.
- Validation: reviewed wiki-link targets, template placeholders, YAML frontmatter, and Git changes.
- Next step: use the English work-log and decision templates for future project work.
---
## 2026-09-12 — Obsidian context integrated into Copilot
- `.github/copilot-instructions.md` was added so non-trivial tasks consult the latest relevant entry in this work log and only the related notes that are needed.
- `AGENTS.md` links to that protocol for agents that use repository instructions.
- The usage guide is available in [[obsidian-tutorial|the Obsidian tutorial]].
- Next step: request tasks normally through chat; context is retrieved from these notes when relevant.
---
## 2026-09-12 — Obsidian vault initialized
- `Home.md` was created as the project index.
- Notes for the work log, decisions, questions, and references were added.
- Local `.obsidian/` configuration was ignored, and notes were protected from `sync_branch.bat`.
- Next step: record analysis, development, and documentation sessions here.