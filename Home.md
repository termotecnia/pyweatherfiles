---
aliases:
  - Home
  - Project dashboard
tags:
  - pyweatherfiles
  - index
---

# pyweatherfiles — Home

This is the entry point to the project's Obsidian vault. Project notes live in `notes/`; the existing technical and scientific documentation remains in its original location and is the canonical source.

## Start here

- [[README|Complete technical reference]]
- [[docs/source/quickstart|Quickstart guide]]
- [[docs/source/installation|Installation guide]]
- [[docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study|Tutorial notebook (Seville and Madrid)]]
- [[notes/README|How to use this vault]]
- [[notes/obsidian-tutorial|Obsidian tutorial for this project]]

## Active work

- [[TODO|Project tasks]]
- [[notes/work-log|Work log]]
- [[notes/decisions|Decision log]]
- [[notes/questions|Open questions]]
- [[notes/references|References and resources]]

## Context and results

- [[analysis_scripts/conclusion_report|Climate-trend analysis conclusions]]
- [[INFORME_REVISION_GENERAL|General review report]]
- [[AGENTS|Architecture and development workflow guide]]

## Code map

- `pyweatherfiles/tmy/` — TMY generation using Sandia/TMY3.
- `pyweatherfiles/degree_hours/` — degree hours and related trends.
- `pyweatherfiles/epw_trend_analyzer/` — multi-year climate trends.
- `analysis_scripts/` — analysis scripts and artifacts.
- `tests/` — automated tests.
- `docs/source/` — Sphinx/MyST documentation.

> [!tip]
> To create a new note, use the Obsidian command palette and **Templates: Insert template**. Templates are stored in `notes/templates/`.

> [!warning]
> `docs/source/full_reference_*.md` are MyST wrappers for the root-level `README.md` / `README_ES.md`. Use the original documents linked above to avoid working on duplicate content.
