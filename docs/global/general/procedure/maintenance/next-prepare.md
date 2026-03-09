---
id: 'general/procedure/maintenance/next-prepare'
type: 'procedure'
scope: 'global'
description: 'Orchestration procedure for next-prepare. Calls the prepare state machine in a loop, dispatching workers as instructed until the todo is prepared.'
---

# Next Prepare — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-discovery.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Goal

Drive the prepare state machine by calling `telec todo prepare [slug]` in a loop.
Each call returns an instruction block. Execute it, then call again. Repeat until
the machine returns a terminal state (PREPARED or a blocker).

The state machine determines what happens. The orchestrator dispatches what is requested.
The orchestrator never makes routing decisions — the machine owns sequencing.

## Preconditions

1. `todos/roadmap.yaml` exists.
2. Target slug is active (not icebox, not delivered) when slug is provided.

## Steps

### 1. Enter the state machine

Call `telec todo prepare [slug]`. Read the returned instruction block.

### 2. Execute the instruction

The state machine returns one of the following instruction types:

#### INPUT ASSESSMENT / REQUIREMENTS DISCOVERY REQUIRED

`input.md` exists and `requirements.md` is still missing or needs rework. Dispatch
`next-prepare-discovery` to a worker session.

The discovery worker owns requirements production. It decides whether solo discovery
is enough or whether to triangulate with a complementary partner. Both paths converge
to the same output: `requirements.md`.

After requirements are written or revised, call `telec todo prepare [slug]` again.

#### REQUIREMENTS REVIEW REQUIRED

`requirements.md` exists but is not yet approved. Dispatch a reviewer to
validate requirements against the quality standard (completeness, testability,
grounding, review-awareness). The reviewer writes a verdict to `state.yaml`.

After review, call `telec todo prepare [slug]` again.

#### PLAN DRAFTING REQUIRED

Requirements are approved but `implementation-plan.md` does not exist.
Dispatch `next-prepare-draft` to a worker session. The draft agent grounds the
approved requirements, decides whether the work is atomic, and either:

- writes `implementation-plan.md` and `demo.md`, or
- splits the todo into dependent child work items and updates the holder breakdown.

After the plan is written or the split is materialized, call
`telec todo prepare [slug]` again.

#### PLAN REVIEW REQUIRED

`implementation-plan.md` exists but is not yet approved. Dispatch a reviewer
to validate the plan against policies, DoD gates, and review lane expectations.
The reviewer writes a verdict to `state.yaml`.

After review, call `telec todo prepare [slug]` again.

#### GROUNDING CHECK

All artifacts exist and are approved. The machine checks freshness:
- If `grounding.valid` is true and digests match: returns PREPARED.
- If stale: returns RE_GROUNDING REQUIRED with the diff of what changed.

#### RE_GROUNDING REQUIRED

The plan references files or policies that have changed since last grounding.
Dispatch `next-prepare-draft` with the diff to update the plan. After update, the
plan re-enters review.

Call `telec todo prepare [slug]` again.

#### PREPARED

Terminal state. The todo is ready for build. Sync to worktree if needed.
End all worker sessions and end yourself.

#### BLOCKER

The machine encountered a condition it cannot resolve (missing input, human
decision needed, superseded todo). Report the blocker and stop.

### 3. Supervision

After dispatching a worker:

1. Set a heartbeat timer.
2. Wait for the worker notification.
3. On notification: call `telec todo prepare [slug]` again to advance.
4. If the worker stalls (heartbeat fires with no progress), open a direct
   conversation to resolve. If still stuck after two iterations, record
   blockers and stop.

### 4. Cleanup

- **PREPARED**: end all worker sessions, then end yourself.
- **BLOCKER**: report the blocker. End worker sessions. End yourself.
  The todo folder is the durable evidence trail.

## Outputs

1. Preparation artifacts produced through the state machine phases:
   `requirements.md`, `implementation-plan.md`, `demo.md`.
2. Each artifact reviewed and approved before the next phase begins.
3. Grounding metadata in `state.yaml` for staleness detection.
4. All sessions ended on completion.

## Recovery

1. If a worker session fails, read the error and retry once. On second failure,
   record the blocker and stop.
2. If the state machine returns an unexpected instruction, log it and stop.
   Do not improvise — the machine owns sequencing.
3. If direct conversation with a worker stalls, write blockers to `dor-report.md`
   and proceed to cleanup.
