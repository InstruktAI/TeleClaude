---
description: Finalize phase. Verify approval, merge to main, log delivery, and cleanup.
id: software-development/procedure/lifecycle/finalize
scope: domain
type: procedure
---

# Finalize — Procedure

## Goal

Merge approved work to main, log delivery, and clean up.

## Preconditions

- `todos/{slug}/review-findings.md` exists with verdict APPROVE.
- No unchecked tasks in `implementation-plan.md`.
- No unresolved deferrals.

## Steps

1. Read `trees/{slug}/todos/{slug}/review-findings.md` and confirm verdict APPROVE.
2. Verify:
   - `implementation-plan.md` tasks all `[x]`.
   - `requirements.md` success criteria checked.
   - No unresolved deferrals.
3. Use commit hooks for verification (lint + unit tests).
4. Merge to main:

   ```bash
   git fetch origin main
   git checkout main
   git pull --ff-only origin main
   git merge {slug} --no-edit
   ```

5. Resolve conflicts if needed, then re-run verification.
6. Push main:

   ```bash
   git push origin main
   ```

7. Append to `todos/delivered.md`:

   ```
   | {date} | {slug} | {title} | DELIVERED | {commit-hash} |
   ```

8. Remove the item for `{slug}` from `todos/roadmap.md`.
9. Delete `todos/{slug}/` after logging delivery and updating the roadmap.
10. Remove the worktree for `{slug}` if it exists.

## Report format

```
FINALIZE COMPLETE: {slug}

Merged: yes
Delivered log: updated
Roadmap: updated
Worktree: removed
```

## Outputs

- Merged changes on `main`.
- Updated `todos/delivered.md` and `todos/roadmap.md`.
- Removed `todos/{slug}/` and any worktree.

## Recovery

- If verification fails or merge conflicts persist, report the blocker and stop.
