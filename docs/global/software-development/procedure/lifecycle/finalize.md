---
description: 'Finalize phase. Two-stage finalize: worker prepare, orchestrator apply.'
id: 'software-development/procedure/lifecycle/finalize'
scope: 'domain'
type: 'procedure'
---

# Finalize — Procedure

## Goal

Advance `origin/main` only through canonical-root orchestrator apply after a worker proves the branch is finalize-ready.

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Preconditions

- `todos/{slug}/review-findings.md` exists with verdict APPROVE.
- `todos/{slug}/quality-checklist.md` exists.
- No unresolved deferrals.

## Steps

### Stage A — Worker: finalize-prepare (worktree)

1. Read `todos/{slug}/review-findings.md` and confirm verdict APPROVE.
2. Integrate latest main inside the worktree:

   ```bash
   git fetch origin main
   git merge origin/main --no-edit
   git push origin HEAD:{slug}
   ```

3. Resolve conflicts in the worktree where code context is available.
4. Report exactly:

   ```
   FINALIZE_READY: {slug}
   ```

5. Stop. Do **not** merge into canonical `main`, push `main`, or modify delivery bookkeeping.
   The orchestrator records durable finalize-ready state after verifying the report.

### Stage B — Orchestrator: finalize handoff

1. Verify worker output contains `FINALIZE_READY: {slug}`.
2. Record durable finalize-ready state for the slug.
3. Re-run the work state machine for the same slug:

   ```bash
   telec todo work {slug}
   ```

4. The slug-specific rerun emits the integration handoff facts from durable state.
5. Continue the orchestration loop without a slug:

   ```bash
   telec todo work
   ```

Worker report format:

```
FINALIZE_READY: {slug}

Main integrated: yes
Apply ownership: orchestrator
```

## Outputs

- Worktree branch rebased/merged with latest `origin/main`.
- Worktree branch pushed to `origin/{slug}`.
- Orchestrator receives `FINALIZE_READY`, records durable finalize-ready state, and then triggers the integration handoff via `telec todo work {slug}`.

## Recovery

- If conflicts cannot be resolved in worker prepare, report blocker and stop.
- If the branch is not pushed or the finalize-ready marker cannot be recorded, fix the branch publication issue and rerun the slug-scoped handoff step.
