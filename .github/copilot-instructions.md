# Copilot context instructions

## Automatic use of the Obsidian vault

The Obsidian vault is the repository root. For non-trivial development, analysis, debugging, documentation, or planning requests received through chat, retrieve context without asking the user to repeat it:

1. Read `AGENTS.md` and the latest relevant entry in `notes/work-log.md` before investigating or modifying files.
2. Read `notes/decisions.md`, `notes/questions.md`, and notes linked from the work log only when they are relevant to the task. Do not scan the entire vault by default.
3. Treat `README.md` and `README_ES.md` as the canonical technical reference, `TODO.md` and `TODO_ES.md` as official task tracking, and `docs/source/` as Sphinx/MyST documentation sources. Do not duplicate their content in notes.
4. After a significant repository change, add or update a concise entry in `notes/work-log.md`: objective, affected files, finding or decision, validation, and next step. When applicable, record durable decisions in `notes/decisions.md` and unresolved questions in `notes/questions.md`.

For simple questions, general explanations, or requests that do not require project context, respond directly without loading unnecessary notes. Explicit user instructions always take precedence: if the user asks not to read or update a note, respect that instruction.

## Technical scope

Copilot works with the vault's Markdown files; it does not need to control the Obsidian graphical interface. Use existing wiki links for navigation and keep notes concise. Local `.obsidian/` configuration is ignored by Git and must not be modified unless the user requests it.
