---
aliases:
  - ADR
  - Architecture decisions
tags:
  - pyweatherfiles
  - decision
---

# Decision log

Record decisions that change the project's design, reproducibility, data sources, or conventions. Add new entries at the top using [[notes/templates/decision-record|the decision template]].

---

## D-006 — One tutorial only, no article references in the repository, Read the Docs theme

- **Date:** 2026-09-21
- **Status:** accepted
- **Context:** `docs/source/` carried three overlapping entry points for a single runnable tutorial: `tutorial.md` (describing a notebook, `examples/tutorial_pyweatherfiles.ipynb`, that no longer exists in the repository), `tutorial_case_study.md` (a wrapper page for the real notebook, referencing a non-existent `Manuscript_TMY_v02.md`), and the notebook itself. The docs also exposed an `article_context` page wrapping a root-level `ARTICLE_CONTEXT_SEVILLA.md`, and both READMEs, `Home.md`, `notes/references.md` and several package docstrings referred to "the article"/"the manuscript". Additionally, `installation.md` documented how to build the documentation locally — developer information that is irrelevant to a package user reading the published site.
- **Decision:** (1) The **single tutorial** is `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb`, rendered directly in the toctree; `tutorial.md` and `tutorial_case_study.md` are deleted. (2) **No part of the repository mentions the article/manuscript** except that notebook, which is deliberately kept as-is because it will be linked as supplementary data of the future submission; `article_context.md` and `ARTICLE_CONTEXT_SEVILLA.md` are deleted and every "article"/"artículo"/"manuscript" wording in READMEs, `Home.md`, `notes/references.md`, `epw_comparator.py`, `session_manager.py`, `degree_hours/group_trend_analyzer.py` and `epw_trend_analyzer/` was reworded to neutral terms ("report", "methods section", "Seville/Madrid case study"). (3) `installation.md` no longer documents the local docs build; that information lives only in `AGENTS.md`/`TODO.md`. (4) The HTML theme is **`sphinx-rtd-theme`** instead of Furo.
- **Consequences:** `pyproject.toml`'s `docs` extra now requires `sphinx-rtd-theme>=3.1` (Furo removed) and `dist_build_docs.bat` checks for it; the `>=3.1` floor is deliberate: 3.0.x and earlier declare `sphinx<9`, so a looser pin would let pip downgrade Sphinx (or fail to resolve) on a clean Read the Docs build; `conf.py` lost `_copy_tutorial_notebook()` (there is nothing to copy any more) and uses `html_context` for the "Edit on GitHub" link instead of Furo's `source_repository` options. Any external link to `tutorial.html`, `tutorial_case_study.html` or `article_context.html` on Read the Docs will 404. Build validated: 0 warnings, 8 top-level pages + the rendered notebook.
- **Links:** [[notes/work-log|Work log]] (2026-09-21 entry), `docs/source/conf.py`, `docs/source/index.md`, `docs/source/installation.md`, `docs/source/quickstart.md`, [[AGENTS|Architecture and development workflow guide]]

---

## D-005 — `validate_*`/`summarize_*` return DataFrames instead of printing them

- **Date:** 2026-09-20
- **Status:** accepted
- **Context:** Most diagnostic methods of `TMYGenerator` dumped their result with `print(df.to_string())`. On real data those tables are unreadable: `validate_step_1_data_loading()` printed two `describe()` blocks 16 columns wide, `validate_full_ranking_for_month()` 31 columns × 10 rows, `summarize_fs_results()` 17 columns × 60 rows and `validate_step_4_final_tmy()` both an 18-column composition table and a 16-column `describe()`. In a notebook (the case study is the main showcase of the API) that produces walls of fixed-width text, while the very same object rendered as a returned `DataFrame` is a proper, scrollable HTML table. It was also unclear *what* `validate_step_1_data_loading()` was validating, since printing `describe()` answers no specific question.
- **Decision:** Every diagnostic method returns its table and stores it in a `validation_*` attribute; what they print is only a short, human-readable summary (and can be silenced with `verbose=False` where it exists). `validate_step_1_data_loading()` was redefined around the three guarantees Step 1 actually provides (continuous grid / enough years / usable values) and now returns a **coverage table** — `validation_step1_coverage` — with the `describe()` tables transposed (one row per variable) in `validation_step1_hourly_stats`/`validation_step1_daily_stats`. `summarize_fs_results()` returns `validation_step3_proximity_ranking`; `validate_step_4_final_tmy()` returns `validation_step6_tmy_composition` and stores `validation_step6_tmy_final_stats`, and its docstring now points to `generate_full_summary()`/`validation_full_summary` as the preferred single consolidated audit. **Exception:** `validate_persistence_selection()` keeps printing — its per-month tables are narrow and are meant to be read as a sequential exclusion report.
- **Consequences:** No signature is broken (the methods previously returned `None` or the same object), but any code asserting on the old console text must be updated — `tests/test_tmy_validation.py` was. New public attributes: `source_years`, `validation_step1_coverage`, `validation_step1_hourly_stats`, `validation_step1_daily_stats`, `validation_step6_tmy_final_stats`. The case-study notebook no longer calls `validate_step_4_final_tmy()` at all (`validation_full_summary` covers it) and displays the returned tables instead.
- **Links:** [[notes/work-log|Work log]] (2026-09-20 entry), [[questions|Open questions]] (Q about the interpolated year), `pyweatherfiles/tmy/_validation.py`, [[../README#3-10-validation-diagnostics-and-visualization|README §3.10]], `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v03.ipynb`

---

## D-004 — Step 7 smooths by default, with a variance-normalized `s_factor='auto'`

- **Date:** 2026-09-19
- **Status:** accepted
- **Context:** `sandia_step_7_smooth_junctions()` defaulted to `s_factor=0.0`, which `scipy.interpolate.UnivariateSpline` interprets as *exact interpolation*: the spline passed through every fitted point, so the "smoothed" values were identical to the raw ones (max\|diff\| ~1e-14, 0 hours changed) and `tmy_final == tmy_raw`. Step 7 was therefore a silent no-op in every default run (including `generate_tmy()`), which contradicted its documented purpose and made `plot_smoothing_comparison()` draw two perfectly overlapping curves. The obvious alternative, SciPy's own automatic criterion (`s=None` → `s=n`), is unit-dependent: on real Seville data it flattened wind speed (12 h window swing 3.61 → 0.85 m/s) while barely touching temperature.
- **Decision:** `s_factor` now accepts `'auto'` (**new default**), a number, or `None`. `'auto'` computes, per variable and per junction, `s = auto_s_strength * n * var(y)` with `auto_s_strength = 0.02` (`TMYGenerator.AUTO_S_STRENGTH`), i.e. it allows a residual equal to 2% of the fitted series' variance. Being proportional to the variance it is unit-invariant, so temperature, dew point and wind speed all receive a comparable *relative* amount of smoothing. Numeric values keep their previous meaning (`0.0` remains available as an explicit, documented no-op for anyone who needs a TMY made strictly of measured hours), and `None` keeps SciPy's criterion. `k = 0.02` was chosen from a sweep (`k ∈ [0.002, 0.1]`) over real Seville junctions as the best trade-off between removing the discontinuity and preserving the diurnal swing. `sandia_step_7_smooth_junctions()` also exposes `smoothing_config` publicly for the first time, `generate_tmy()` forwards `smoothing_hours`/`smoothing_s_factor`/`smoothing_auto_s_strength`/`smoothing_config`, and `correct_selection_by_temperature(regenerate=True)` re-smooths with the settings originally used (`_last_smoothing_kwargs`) instead of reverting to defaults.
- **Consequences:** TMYs generated with default settings now differ from previous ones in 126 of 8 760 hours (the 11 × 12 h junction windows). Measured effect on 15 years of real Seville data: mean junction discontinuity in `T_air` 2.20 → 0.89 degC (max 5.00 → 2.09), RMS deviation inside the windows 0.78 degC, annual mean unchanged within 0.001 degC, `GHI`/`DNI` bit-identical (radiation is never smoothed). Any artefact generated before this change (EPWs, figures, notebooks with stored outputs) is therefore slightly stale and must be regenerated to stay consistent; the case-study notebook was re-executed for this reason.
- **Links:** [[notes/work-log|Work log]] (2026-09-19 entry), [[questions|Open questions]], `pyweatherfiles/tmy/_assembly_smoothing.py`, `tests/test_tmy_smoothing.py`, [[../README#3-7-step-7-monthly-junction-smoothing-sandia_step_7_smooth_junctions|README §3.7]]

---

## D-003 — NCDH is a cooling-potential (deficit) indicator, not a classic CDH restricted to night hours

- **Date:** 2026-09-14
- **Status:** accepted
- **Context:** Section 3.1's "night cooling potential" indicator (NCDH) was implemented as classic cooling degree-hours (`max(0, T - 25)`) restricted to 00:00-08:00. Daniel/Rafa spotted, while auditing Leon in `fig3_overview_grid_by_city.png`, that this measures overheating (excess above 25 degC) rather than the intended "how much passive night ventilation could still cool the building" (deficit below 25 degC). The correct formula is the mirror one, `max(0, 25 - T)`, restricted to 00:00-08:00 (inclusive) **and** to summer months (July-September) -- the only period where night ventilation potential is a meaningful design question.
- **Decision:** `DegreeHoursCalculator.calculate()`/`_compute_dh()` gained two reusable, generic parameters: `invert_cooling` (flips the cooling formula to `max(0, SP_cooling - T)`, a "potential/deficit" instead of "excess") and `months` (calendar-month filter, ANDed with the existing `hours` filter). `EpwGroupTrendAnalyzer.hours_scenarios` forwards both per scenario. The corrected indicator is named `night_potential_jul_sep` / column `cooling_dh_night_potential_jul_sep` (analysis scripts) and `NCDH_25` (audit workbook), matching the formula audited against the user-provided reference workbook (`analysis_scripts/leon_hourly_degreehours_audit_RMP.xlsx`, column `NCDH_25`), except that the final agreed month range is July-September only (the reference draft used June-September).
- **Consequences:** Any future degree-hours indicator needing a "potential/deficit below a threshold" (as opposed to "excess above it") should reuse `invert_cooling` rather than re-deriving the formula. Old CSV/figure outputs using the pre-fix column names (`cooling_dh_night_0_8h`, `night_cdh_25_0_8h`, `NCDH25_0_8h`) are stale and were regenerated; any external consumer of those column names must update to the new ones.
- **Links:** [[notes/work-log|Work log]] (2026-09-14 entry), [[../README#6-3-calculation-calculate|README §6.3/6.6]], `analysis_scripts/climate_evolution_trend_separate_climates.py`, `analysis_scripts/export_hourly_degreehours_audit.py`

---

## D-002 — Keep Obsidian vault documentation and paths in English

- **Date:** 2026-09-13
- **Status:** accepted
- **Context:** The repository's primary language is English, while the initial Obsidian documentation and some note paths were written in Spanish. This mismatch made the vault inconsistent with the codebase and its English technical documentation.
- **Decision:** Write all Obsidian-facing prose, visible link labels, templates, metadata, and vault paths in English. Use lowercase ASCII `kebab-case` filenames and folder names. Update links and configuration whenever a vault item is renamed.
- **Consequences:** Future vault notes and templates will use English-safe paths. Links should prefer the English README and TODO when an English canonical source is available. Spanish technical documents outside the vault remain unchanged unless separately requested.
- **Links:** [[Home]], [[../README]], [[notes/work-log]]

---

## D-001 — Keep Obsidian as a non-intrusive documentation layer

- **Date:** 2026-09-12
- **Status:** accepted
- **Context:** The project already has bilingual READMEs, TODO tracking, and Sphinx/MyST documentation. A navigable workspace is needed for notes and relationships between documents without creating duplicate sources.
- **Decision:** Use the repository root as the vault. Keep shareable notes in `notes/`, retain `Home.md` as the index, and exclude `.obsidian/` from version control.
- **Consequences:** Canonical documentation is not duplicated. Each installation can customize its Obsidian interface. Notes that should be shared must be explicitly added to Git.
- **Links:** [[Home]], [[../README]], [[docs/source/index]]
