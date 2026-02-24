---
description: Sync todos with architecture docs and codebase. Detects AND fixes drift autonomously.
---

# Sync Todos

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/software-development/concept/orchestrator.md
- @~/.teleclaude/docs/software-development/policy/commits.md

## Purpose

Synchronize todos with architecture docs and the codebase, and fix drift.

## Inputs

- `docs/` architecture docs
- Codebase
- `todos/roadmap.yaml`

## Outputs

- Updated `todos/roadmap.yaml`
- Updated `todos/delivered.yaml`
- Deleted or updated `todos/{slug}/` folders (when required)

## Steps

- Phase 1: Parallel scanning (launch all 3 simultaneously)
  - Architecture scanner: discover architecture docs and return required actors/components and implied todos.
  - Codebase scanner: scan source directories and return implemented features and module paths.
  - Todos scanner: read `todos/roadmap.yaml` and return pending/completed items and folders.

- Phase 2: Reconcile and fix
  - If todo marked complete but code missing: mark pending in `roadmap.yaml`.
  - If code exists but todo marked pending: mark complete in `roadmap.yaml`.
  - If folder exists but not in roadmap: add to roadmap or delete folder.
  - If completed todo folder is ready to finalize: append to `todos/delivered.yaml`, remove from roadmap, delete folder.
  - If todo is obsolete (not in architecture): remove from roadmap (no delivered log).

- Direct edits
  - `todos/roadmap.yaml`: adjust status and remove delivered items.
- `todos/delivered.yaml`: prepend `{ slug, date, title, commit }`.
  - Delete delivered folders after logging and roadmap removal.
  - Delete obsolete folders after confirming they are not needed.

- Phase 3: Commit
  - If changes were made, commit them following the commits policy.

- Report completion with a summary of changes.
