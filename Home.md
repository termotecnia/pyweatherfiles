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
- [[docs/source/installation|Installation and documentation build]]
- [[docs/source/tutorial_case_study|Seville and Madrid case study]]
- [[notes/README|How to use this vault]]
- [[notes/obsidian-tutorial|Obsidian tutorial for this project]]

## Active work

- [[TODO|Project tasks]]
- [[notes/work-log|Work log]]
- [[notes/decisions|Decision log]]
- [[notes/questions|Open questions]]
- [[notes/references|References and resources]]

## Context and results

- [[ARTICLE_CONTEXT_SEVILLA|Seville article context]]
- [[Manuscript_TMY_v02|TMY manuscript]]
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
> `docs/source/full_reference_*.md` and `docs/source/article_context.md` are MyST wrappers for root-level documents. Use the original documents linked above to avoid working on duplicate content.
