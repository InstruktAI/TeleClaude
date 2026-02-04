---
description: Sync todos with architecture docs and codebase. Detects AND fixes drift autonomously.
---

# Sync Todos

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/software-development/concept/orchestrator.md

## Purpose

Synchronize todos with architecture docs and the codebase, and fix drift.

## Inputs

- `docs/` architecture docs
- Codebase
- `todos/roadmap.md`

## Outputs

- Updated `todos/roadmap.md`
- Updated `todos/delivered.md`
- Deleted or updated `todos/{slug}/` folders (when required)

## Steps

- Phase 1: Parallel scanning (launch all 3 simultaneously)
  - Architecture scanner: discover architecture docs and return required actors/components and implied todos.
  - Codebase scanner: scan source directories and return implemented features and module paths.
  - Todos scanner: read `todos/roadmap.md` and return pending/completed items and folders.

- Phase 2: Reconcile and fix
  - If todo marked complete but code missing: mark pending in `roadmap.md`.
  - If code exists but todo marked pending: mark complete in `roadmap.md`.
  - If folder exists but not in roadmap: add to roadmap or delete folder.
  - If completed todo folder is ready to finalize: append to `todos/delivered.md`, remove from roadmap, delete folder.
  - If todo is obsolete (not in architecture): remove from roadmap (no delivered log).

- Direct edits
  - `todos/roadmap.md`: adjust status and remove delivered items.
  - `todos/delivered.md`: append `| {date} | {slug} | {title} | DELIVERED | {commit-hash} |`.
  - Delete delivered folders after logging and roadmap removal.
  - Delete obsolete folders after confirming they are not needed.

- Phase 3: Commit
  - If changes were made, commit:
    ```
    git add todos/
    git commit -m "chore(todos): sync roadmap with architecture and codebase"
    ```

- Report completion with a summary of changes.
