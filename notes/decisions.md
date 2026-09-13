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
