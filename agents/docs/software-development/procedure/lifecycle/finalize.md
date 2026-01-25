---
description: Finalize phase. Verify approval, merge to main, log delivery, and cleanup.
id: software-development/procedure/lifecycle/finalize
scope: domain
type: procedure
---

# Lifecycle: Finalize — Procedure

## Prerequisite

Review must be APPROVE in `todos/{slug}/review-findings.md`.

## 1) Verify Prerequisites

- Read `trees/{slug}/todos/{slug}/review-findings.md`
- Stop if verdict is not APPROVE

## 2) Final Completeness Checks

- No unchecked tasks in `implementation-plan.md`
- No unchecked success criteria in `requirements.md`
- No unresolved deferrals

If any check fails, stop and report to the orchestrator.

## 3) Final Verification

Use commit hooks (lint + unit tests) as verification.

## 4) Main Dirty Policy

Dirty main is expected. Stash local changes, merge, then restore.

## 5) Merge to Main (FF-only)

```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
git merge {slug} --no-edit
```

Resolve conflicts if needed, then re-run verification.

## 6) Push

```bash
git push origin main
```

## 7) Restore Local Main Changes

If you stashed in step 4, run `git stash pop` and report any conflicts.

## 8) Log Delivery

Append to `todos/delivered.md`:

```
| {date} | {slug} | {title} | DELIVERED | {commit-hash} |
```

## 9) Update Roadmap

Remove the item for `{slug}` from `todos/roadmap.md`.

## 10) Remove Todo Folder

Delete `todos/{slug}/` after logging delivery and updating the roadmap.

## 11) Final Commit and Push

Commit log + roadmap + todo folder removal and push to main.

## 12) Remove Worktree

If a worktree exists for `{slug}`, remove it as the final cleanup step.
