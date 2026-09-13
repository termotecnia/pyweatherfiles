---
aliases:
  - Obsidian tutorial
  - Obsidian guide
tags:
  - pyweatherfiles
  - documentation
  - obsidian
---

# Obsidian tutorial for `pyweatherfiles`

This vault uses the repository root as its knowledge space. Obsidian complements the existing code and documentation; it does not replace the READMEs, TODOs, or Sphinx documentation.

## 1. Where everything lives

| Location | Purpose |
|---|---|
| [[Home|`Home.md`]] | Project entry point and map. Open it when you start. |
| [[../README|`README.md`]] | Canonical technical reference in English. |
| [[TODO|`TODO.md`]] | Official task tracking. |
| `docs/source/` | Sources for the Sphinx/MyST documentation. |
| `notes/` | Working notes, decisions, questions, and references. |
| `notes/templates/` | Templates for creating consistent notes. |
| `notes/attachments/` | Images, PDFs, and other attachments created from Obsidian. |

> [!warning]
> Do not edit `docs/source/full_reference_*.md` or `docs/source/article_context.md` as primary sources: they are MyST wrappers for root-level documents. Use the originals linked from [[Home]].

## 2. Recommended workflow

### When starting a session

1. Open [[Home]].
2. Review [[TODO|the official tasks]] and the latest entry in [[notes/work-log|the work log]].
3. In `notes/work-log.md`, add a new entry at the top using [[notes/templates/daily-note|the session template]].
4. Add a verifiable objective to the entry and link only the files that are needed.

### While working

- Use wiki-style internal links to connect code, documentation, and results.
- Mark concrete steps with `- [ ]` and `- [x]`.
- If you make a design or reproducibility decision, record it in [[notes/decisions|the decision log]].
- If an unresolved question arises, add it to [[notes/questions|open questions]].
- For an external source, dataset, standard, or paper, use [[notes/references|references]].

### When finishing

1. Write what changed, which validation you ran, and the next step in [[notes/work-log|the work log]].
2. Update `TODO.md` if the official state of a task changed.
3. If the note should be shared, include it in the next Git commit.

## 3. Writing and linking notes

### Wiki links

Use wiki links to avoid copying context:

- `[[../README]]` links to the technical reference.
- `[[../README|technical reference]]` changes the visible text.
- `[[notes/decisions#D-001 — Keep Obsidian as a non-intrusive documentation layer|D-001]]` links to a specific section.
- `[[analysis_scripts/conclusion_report]]` links to analysis results.

When you type `[[`, Obsidian suggests existing files. Choose an item from the list to avoid creating broken links.

### Essential Markdown

```markdown
# Title
## Section

- List item
- [ ] Pending task
- [x] Completed task

**important text**
`code or path`

> Note or quotation
```

Attachments dragged into or pasted into notes are stored in `notes/attachments/` by the current vault configuration. Always review their size, provenance, and license before adding them to Git.

### Properties and tags

Each note can start with YAML properties between `---`. Use them for stable information, such as `type`, `date`, or `status`. Tags are useful for short, cross-cutting topics:

- `#tmy`
- `#epw`
- `#trends`
- `#decision`
- `#documentation`

Do not use tags to repeat the whole folder structure or to replace links between documents.

## 4. Creating notes with templates

The native **Templates** plugin is enabled and looks for templates in `notes/templates/`.

1. Create a new note; it will be saved in `notes/` by default.
2. Open the command palette with `Ctrl+P`.
3. Run **Templates: Insert template**.
4. Choose `daily-note` for a working session or `decision-record` for a persistent decision.
5. Complete the empty fields and add links to the evidence.

You can also use the file explorer to duplicate and rename a template.

## 5. Finding information quickly

- **Global search:** `Ctrl+Shift+F`. Search for terms, tags, class names, or text from a decision.
- **Quick switcher:** `Ctrl+O`. Open a file by name; type `Home`, `work-log`, `TODO`, or a module name.
- **Backlinks:** open a note's incoming-links panel to see which documents use it.
- **Outgoing links:** check whether an important note already leads to the right evidence.
- **Local graph:** use it from a specific note to explore relationships without the noise of the entire repository.

## 6. Using Obsidian to reduce context and token use

The work log should be the compact memory of the work. A useful entry is usually 5 to 12 lines long:

```markdown
## 2026-09-12 — Review degree-hour trend

- Objective: validate the global estimator.
- Files: [[pyweatherfiles/degree_hours/group_trend_analyzer.py|group trend analyzer]], [[INFORME_REVISION_GENERAL]].
- Finding: ...
- Validation: `python -m pytest tests/...`
- Next step: ...
```

To request help in a new session, identify the note to read and limit the scope. For example:

```text
Read `notes/work-log.md` and only the linked files that are necessary.
Continue the latest entry.
Objective: [specific outcome].
Do not modify files outside: [paths].
When finished, update the work log with changes, validation, and the next step.
```

This recovers relevant context from the vault instead of repeating background, results, and decisions in chat.

### Automatic chat context

The repository includes `.github/copilot-instructions.md`. For non-trivial tasks, Copilot consults the latest relevant entry in [[notes/work-log|the work log]] and, only when applicable, the decisions, questions, and linked documents. You can therefore keep your usual workflow: ask for the task directly in chat.

The instruction avoids loading every note for simple or general questions. To limit or avoid that context, say so explicitly—for example, “respond without consulting notes” or “use only `file.md`”. Explicit instructions in each message take precedence over the vault protocol.

## 7. Git and safety

- Notes in `notes/` and `Home.md` are project documents and can be shared through Git.
- `.obsidian/` is ignored: it stores the interface, plugins, and local preferences for this installation.
- `sync_branch.bat` protects `Home.md` and `notes/` while running its cleanup, but **can delete other untracked files**. Do not run it when you have results, data, or code outside those paths that are not saved in Git.
- Before sharing a note, remove sensitive paths, credentials, personal information, or provisional results that must not be published.

## 8. Quick checklist

- [ ] I started from [[Home]].
- [ ] I recorded the objective, evidence, and next step in [[notes/work-log|the work log]].
- [ ] I saved a durable decision in [[notes/decisions|the decision log]], if applicable.
- [ ] I updated the canonical TODO when a task changed state.
- [ ] I reviewed which notes and attachments should be included in Git.

## Related links

- [[notes/README|Vault quick guide]]
- [[notes/work-log|Work log]]
- [[notes/decisions|Decisions]]
- [[notes/questions|Open questions]]
- [[notes/references|References]]
- [[Home]]
