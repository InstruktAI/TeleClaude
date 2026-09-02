---
description: 'Finalize phase. Worker prepares the branch; the work orchestrator records handoff and exits.'
visibility: 'public'
---

# Finalize — Procedure

## Required reads

## Goal

Prepare a reviewed branch for integration and end the work orchestrator after the
finalize-ready handoff is recorded. The work orchestrator never advances
`origin/main`; delivery is triggered by the integration event chain after the
workflow state reaches `finalize_ready`.

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

3. Resolve conflicts in the worktree where code context is available. `origin/main` is the leading baseline: preserve accepted main behavior, reapply the reviewed branch intent on top, run the relevant tests and quality gates, and commit the resolution.
4. Publish the finalized branch:

   ```bash
   git push origin HEAD:{slug}
   ```

5. Report exactly:

   ```
   FINALIZE_READY: {slug}
   ```

6. Stamp finalize readiness: `telec todo stamp {slug} --finalize-ready`.

### Stage B — Work orchestrator: record handoff and end

The work orchestrator's authority ends here. It records the handoff — it does not
perform integration. Integration is a separate singleton role (`/next-integrate`)
with its own lease, worktree (`trees/_integration/`), and dispatch path. The work
orchestrator must never dispatch `/next-integrate` or call `telec todo integrate`.

1. Re-run the work state machine for the same slug:

   ```bash
   telec todo work {slug}
   ```

2. The slug-specific rerun emits the integration handoff facts from durable state.
3. Execute the terminal cleanup script emitted by the state machine:

   ```bash
   telec sessions end <child-session-id>
   telec sessions end self
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
- Orchestrator receives `FINALIZE_READY`, records durable finalize-ready state via
  `telec todo work {slug}`, executes worker cleanup, and ends itself.

## Recovery

- If conflicts arise in worker prepare, resolve them in the worktree before reporting readiness. Report blocker only when the conflict requires human product judgment, an architectural decision, or missing context that cannot be recovered from the prepared artifacts and code.
- If the branch is not pushed or the finalize-ready marker cannot be recorded, fix
  the branch publication issue and rerun the slug-scoped handoff step.
