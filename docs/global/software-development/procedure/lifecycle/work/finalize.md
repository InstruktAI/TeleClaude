---
description: 'Finalize phase. Two-stage finalize: worker prepare, orchestrator apply.'
id: 'software-development/procedure/lifecycle/work/finalize'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Finalize — Procedure

## Goal

Advance `origin/main` only through canonical-root orchestrator apply after a worker proves the branch is finalize-ready.

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Preconditions

- `telec todo artifacts read {slug} review-findings` exists with verdict APPROVE.
- `telec todo artifacts read {slug} quality-checklist` exists.
- No unresolved deferrals.

## Steps

### Stage A — Worker: finalize-prepare (worktree)

1. Read `telec todo artifacts read {slug} review-findings` and confirm verdict APPROVE.
2. Integrate latest main inside the worktree:

   ```bash
   git fetch origin main
   git merge origin/main --no-edit
   ```

3. Resolve conflicts in the worktree where code context is available.
4. Publish the finalized branch:

   ```bash
   git push origin HEAD:{slug}
   ```

5. Report exactly:

   ```
   FINALIZE_READY: {slug}
   ```

6. Stamp finalize readiness: `telec todo stamp {slug} --finalize-ready`.
7. Stop. Do **not** merge into canonical `main`, push `main`, or modify delivery bookkeeping.

### Stage B — Work orchestrator: record handoff (not integration)

The work orchestrator's authority ends here. It records the handoff — it does not
perform integration. Integration is a separate singleton role (`/next-integrate`)
with its own lease, worktree (`trees/_integration/`), and dispatch path. The work
orchestrator must never dispatch `/next-integrate` or call `telec todo integrate`.

1. Re-run the work state machine for the same slug:

   ```bash
   telec todo work {slug}
   ```

2. The slug-specific rerun emits the integration handoff facts from durable state.
3. Continue the orchestration loop without a slug:

   ```bash
   telec todo work
   ```

4. If the state machine does not advance past finalize, report the blocker and stop.
   Do not escalate scope into integration.

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
