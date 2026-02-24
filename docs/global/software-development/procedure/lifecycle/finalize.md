---
description: 'Finalize phase. Two-stage finalize: worker prepare, orchestrator apply.'
id: 'software-development/procedure/lifecycle/finalize'
scope: 'domain'
type: 'procedure'
---

# Finalize — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Goal

Advance `origin/main` only through canonical-root orchestrator apply after a worker proves the branch is finalize-ready.

## Preconditions

- `todos/{slug}/review-findings.md` exists with verdict APPROVE.
- `todos/{slug}/quality-checklist.md` exists.
- No unresolved deferrals.

## Stage A — Worker: finalize-prepare (worktree)

1. Read `todos/{slug}/review-findings.md` and confirm verdict APPROVE.
2. Integrate latest main inside the worktree:

   ```bash
   git fetch origin main
   git merge origin/main --no-edit
   ```

3. Resolve conflicts in the worktree where code context is available.
4. Report exactly:

   ```
   FINALIZE_READY: {slug}
   ```

5. Stop. Do **not** merge into canonical `main`, push, or modify delivery bookkeeping.

## Stage B — Orchestrator: finalize-apply (canonical root)

1. Verify worker output contains `FINALIZE_READY: {slug}`.
2. From canonical repository root on branch `main`, run apply:

   ```bash
   git fetch origin main
   git switch main
   git pull --ff-only origin main
   git merge {slug} --no-edit
   ```

3. Apply delivery bookkeeping:
   - non-bug todos: append to `todos/delivered.yaml` and remove from `todos/roadmap.yaml`
   - bug todos: skip delivery bookkeeping
4. Push canonical `main`:

   ```bash
   git push origin main
   ```

5. Continue orchestrator-owned snapshot/cleanup workflow.

## Report format (worker)

```
FINALIZE_READY: {slug}

Main integrated: yes
Apply ownership: orchestrator
```

## Outputs

- Worktree branch rebased/merged with latest `origin/main`.
- Orchestrator receives `FINALIZE_READY` and can safely apply from canonical root.

## Recovery

- If conflicts cannot be resolved in worker prepare, report blocker and stop.
- If apply fails (dirty canonical main, merge conflict, push rejection), resolve in orchestrator apply and retry.
