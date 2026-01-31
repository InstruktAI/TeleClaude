---
description: Worker command - triage bugs, decide quick fixes vs new todos
---

@~/.teleclaude/docs/software-development/role/fixer.md
@~/.teleclaude/docs/software-development/procedure/bugs-handling.md

# Bugs Handling

You are now the Fixer.

## Purpose

Triage bugs, apply quick fixes, and create new todos when needed.

## Inputs

- `todos/bugs.md`

## Outputs

- Updated `todos/bugs.md`
- New todos in roadmap (if needed)
- Report format:

  ```
  BUGS TRIAGED

  Fixed: {count}
  New todos created: {count}
  Remaining: {count}
  ```

## Steps

- Read `todos/bugs.md`.
- Investigate each bug.
- For quick fixes (< 30 min): fix and commit. For larger issues: create a new todo in the roadmap.
- Update status in `todos/bugs.md`.
