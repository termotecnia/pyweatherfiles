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
