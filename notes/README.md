---
aliases:
  - Vault guide
  - Using Obsidian
tags:
  - pyweatherfiles
  - documentation
---

# How to use the `pyweatherfiles` vault

For step-by-step Obsidian instructions, see [[obsidian-tutorial|the complete tutorial]].

## Purpose

This vault organizes working knowledge around the code without replacing the official documentation:

- `README.md` and `README_ES.md` are the authoritative technical reference.
- `TODO.md` and `TODO_ES.md` contain the official task tracking.
- `docs/source/` supplies the published Sphinx/MyST documentation.
- `notes/` gathers context, decisions, and tracking that complement those sources.

## Recommended workflow

1. Open [[Home]] when starting a session.
2. Record progress and relevant commands or results in [[work-log|the work log]].
3. When a choice affects the design, record it in [[decisions|the decision log]].
4. Keep researchable uncertainties in [[questions|open questions]].
5. Add sources, datasets, and reading material to [[references|references and resources]].
6. When closing a task, update the corresponding canonical `TODO` when appropriate.

## Note conventions

- Link internal files using wiki links; use a descriptive display text when it improves readability: `[[../README|technical reference]]`.
- Use existing tags sparingly: `#tmy`, `#epw`, `#trends`, `#documentation`, and `#decision`.
- Do not copy long sections from the READMEs or Sphinx; link to their canonical source.
- Templates in `templates/` provide the minimum structure for session notes and decisions.

## Git and safety

- Content in `notes/` **can be versioned**: add only notes that should be shared to Git.
- `.obsidian/` contains the interface configuration, plugins, and state for this installation; it is deliberately ignored.
- `sync_branch.bat` protects `Home.md` and `notes/` from its `git clean -fd`, even when you have not yet added them to Git.
- Attachments created from Obsidian are saved in `notes/attachments/`. Review their size and license before versioning them.

> [!note]
> To use this repository as a vault, select **Open folder as vault** in Obsidian and open the root folder at `D:\Python\pyweatherfiles`.
