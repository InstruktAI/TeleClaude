---
description: 'Triage bugs, decide quick fixes vs new todos, and track resolution in bugs.md.'
id: 'software-development/procedure/bugs-handling'
scope: 'domain'
type: 'procedure'
---

# Bugs Handling — Procedure

## Goal

Convert raw bug reports into action: fix quickly when safe, otherwise create a todo with clear scope.

- Read `todos/bugs.md`.
- Find unchecked items (`[ ]`).
- If none, report and stop.

### 2.1 Understand

- Read the bug description.
- Identify affected files/components.
- Understand expected vs actual behavior.

### 2.2 Investigate

- Search the codebase and logs.
- Identify the root cause if possible.

### 2.3 Decide: Quick Fix or Todo

**Quick fix** if all are true:

- Small, localized change
- Low risk of regressions
- Clear expected outcome

**Otherwise create a todo**:

- Create `todos/{new_slug}/input.md` with the bug details
- Add `{new_slug}` to `todos/roadmap.md` as `[ ]`
- Mark the bug as converted (note the new slug)

### 2.4 If Quick Fix (Self-Healing Route)

If the fix is small and localized, follow the **Bugs Self-Healing** route:

1. **Use Special Worktree:** All bug fixes must be performed in the persistent `.bugs-worktree` directory (located at the project root, NOT in `worktrees/`).
2. **Update Worktree:** Always ensure the worktree is up to date:
   ```bash
   cd .bugs-worktree && git pull origin main
   ```
3. **Mark and Fix:**
   - Mark `[>]` in `bugs.md` while working.
   - Apply minimal fix.
   - Verify via commit hooks (lint + unit tests).
   - Mark `[x]` when fixed.
   - Commit one bug per commit with a descriptive message.
4. **Push:** Push the changes to main once verified.

Summarize fixes and any new todos created.

## Preconditions

- Bug report exists with reproduction steps or evidence.
- Access to the repository and relevant test environment.
- `.bugs-worktree` exists or can be created via `git worktree add .bugs-worktree main`.

## Steps

- Triage the report and attempt to reproduce.
- Record the bug in `todos/bugs.md` with severity and scope.
- Decide quick fix (Self-Healing) vs roadmap item.
- Apply fix in `.bugs-worktree` or create a new work item and update roadmap.

## Outputs

- Updated `todos/bugs.md` and/or a new roadmap item.
- Fix committed if resolved.

## Recovery

- If not reproducible, mark with `[?]` and document attempts.
- If regression occurs, mark `[!]` and create follow-up tasks.
