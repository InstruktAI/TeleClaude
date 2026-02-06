---
description: Worker command - triage bugs, decide quick fixes vs new todos
---

# Bugs Handling

You are now the Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/fixer.md
- @~/.teleclaude/docs/software-development/procedure/bugs-handling.md

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

- **Prepare Worktree:**
  - Go to `.bugs-worktree` (create if missing: `git worktree add .bugs-worktree main`).
  - Pull latest main: `git pull origin main`.
- Read `todos/bugs.md`.
- Investigate each bug.
- For quick fixes (< 30 min): fix in `.bugs-worktree`, verify, and commit. For larger issues: create a new todo in the roadmap.
- Update status in `todos/bugs.md`.
