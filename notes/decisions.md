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
