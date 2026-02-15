---
description: 'Finalize phase. Verify approval, merge to main, log delivery, and cleanup.'
id: 'software-development/procedure/lifecycle/finalize'
scope: 'domain'
type: 'procedure'
---

# Finalize — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Goal

Merge approved work to main, log delivery, and clean up.

## Preconditions

- `todos/{slug}/review-findings.md` exists with verdict APPROVE.
- `todos/{slug}/quality-checklist.md` exists.
- No unresolved deferrals.

## Steps

1. Read `trees/{slug}/todos/{slug}/review-findings.md` and confirm verdict APPROVE.
2. Update only the Finalize section in `quality-checklist.md`.
   - Do not edit Build or Review sections.
3. Use commit hooks for verification (lint + unit tests).
4. Integrate main into the branch (inside the worktree — you have code context to resolve conflicts):

   ```bash
   git fetch origin main
   git merge origin/main --no-edit
   ```

   If conflicts occur, resolve them here in the worktree where you have full code context,
   commit the resolution, and re-run verification.

5. Merge branch to main (from the worktree, use `git -C` to operate on the main repo):

   ```bash
   MAIN_REPO="$(git rev-parse --git-common-dir)/.."
   git -C "$MAIN_REPO" fetch origin main
   git -C "$MAIN_REPO" switch main
   git -C "$MAIN_REPO" pull --ff-only origin main
   git -C "$MAIN_REPO" merge {slug} --no-edit
   ```

   This merge should be clean because step 4 already integrated main into the branch.

6. Push main:

   ```bash
   git -C "$MAIN_REPO" push origin main
   ```

7. Append to `todos/delivered.md` (use `$MAIN_REPO/todos/` paths):

   ```
   | {date} | {slug} | {title} | DELIVERED | {commit-hash} |
   ```

8. Remove the item for `{slug}` from `todos/roadmap.md`.

**STOP HERE.** Do not delete `todos/{slug}/`, the worktree, or the feature branch.
The orchestrator owns cleanup after `end_session` — the worker cannot safely delete
its own working directory.

## Report format

```
FINALIZE COMPLETE: {slug}

Merged: yes
Delivered log: updated
Roadmap: updated
Cleanup: orchestrator-owned (worktree, branch, todo folder)
```

## Outputs

- Merged changes on `main`.
- Updated `todos/delivered.md` and `todos/roadmap.md`.

## Recovery

- If verification fails or merge conflicts persist, report the blocker and stop.
