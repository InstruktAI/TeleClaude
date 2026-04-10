---
id: 'software-development/procedure/lifecycle/prepare/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Prepare stage overview. Orchestrator loop driving the prepare state machine through discovery, review, drafting, gate, and grounding phases.'
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discovery.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/readiness-gate.md

## Goal

Drive the prepare state machine by calling `telec todo prepare [slug]` in a loop.
Each call returns an instruction block. Execute it, then call again. Repeat until
the machine returns a terminal state (PREPARED or a blocker).

The state machine determines what happens. The orchestrator dispatches what is requested.
The orchestrator never makes routing decisions — the machine owns sequencing.

Produce reviewed, approved, and grounded preparation artifacts for a todo through
sequential phases, each producing one artifact that is reviewed before the next begins.

## Preconditions

1. `todos.db` roadmap exists and is readable.
2. Target slug is active (not icebox, not delivered) when slug is provided.

## Steps

### 1. Enter the state machine

Call `telec todo prepare [slug]`. Read the returned instruction block.

### 2. Execute the instruction

The state machine returns a linear script for the current state. The orchestrator executes it verbatim and then calls `telec todo prepare [slug]` again. Each phase follows the same loop: the state machine dispatches a worker when needed, relays review findings to the existing worker when a review returns `needs_work`, or emits cleanup commands on a successful terminal. The orchestrator never decides session lifecycle or branches on verdict — the state machine owns both.

Phases the state machine drives through:

- **Input assessment / requirements discovery** — dispatches `next-prepare-discovery` when `requirements.md` is missing.
- **Requirements review** — dispatches `next-review-requirements`; on `needs_work` relays findings to the live discovery worker via `telec sessions send`; on `approve` ends the phase workers.
- **Test specification build** — dispatches `next-build-specs` when xfail specs are missing.
- **Test spec review** — dispatches `next-review-specs`; on `needs_work` relays findings to the live spec builder; on `approve` ends the phase workers.
- **Plan drafting** — dispatches `next-prepare-draft` when `implementation-plan.md` is missing.
- **Plan review** — dispatches `next-review-plan`; on `needs_work` relays findings to the live draft worker; on `approve` ends the phase workers.

#### GATE REQUIRED

All artifacts exist and are approved. The state machine requests a DOR gate
assessment. Dispatch `next-prepare-gate` to a worker session.

The gate worker validates the full artifact set, stamps a verdict, and goes
idle. The orchestrator reads the verdict and acts on the **status**, not the
score:

- **`pass`** → call `telec todo prepare [slug]` again (expects PREPARED or
  GROUNDING CHECK).
- **`needs_work`** → the gate listed exact blockers. Dispatch a fixer to the
  appropriate phase (discovery if research is missing, draft if the plan is
  defective, test-spec if specs have bugs). After the fixer completes, re-run
  the gate. **The orchestrator never overrides `needs_work` to `pass`.** The
  score is informational — only the status determines the next action.
- **`needs_decision`** → escalate to the human. Report the blockers and stop.

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

Terminal success state. The state machine emits the cleanup script: `telec sessions end <id>` for each live worker tied to the slug, then `telec sessions end self` for the orchestrator. Execute verbatim.

#### BLOCKER

The machine encountered a condition it cannot resolve (missing input, human decision needed, review rounds exhausted). The state machine emits a blocker report that lists live session IDs for human inspection. No end commands are emitted — sessions stay alive as signal for the human.

### 3. Supervision

After dispatching a worker:

1. Set a heartbeat timer.
2. Wait for the worker notification.
3. On notification: call `telec todo prepare [slug]` again to advance. The state machine reads the latest state and emits the next action.
4. If the worker stalls (heartbeat fires with no progress), open a direct conversation to resolve. If still stuck after two iterations, record blockers and stop.

### HITL boundary

The human interacts only with `input.md` via `next-refine-input`. Once the
state machine starts, all phases are fully autonomous. No human gates exist
inside the machine. The only human-facing event is `prepare.blocked` when
a decision genuinely requires human input.

### Events

The state machine emits events at each phase transition for automation,
notifications, and auditing. The human does not interact with these — they
are consumed by automation (invalidation checks, notifications).

| Phase transition       | Event                           |
| ---------------------- | ------------------------------- |
| Input refined          | `prepare.input_refined`         |
| Discovery dispatched   | `prepare.discovery_started`     |
| Requirements written   | `prepare.requirements_drafted`  |
| Requirements approved  | `prepare.requirements_approved` |
| Test specs written     | `prepare.test_specs_drafted`    |
| Test specs approved    | `prepare.test_specs_approved`   |
| Plan written           | `prepare.plan_drafted`          |
| Plan approved          | `prepare.plan_approved`         |
| Grounding invalidated  | `prepare.grounding_invalidated` |
| Re-grounding completed | `prepare.regrounded`            |
| Preparation complete   | `prepare.completed`             |
| Preparation blocked    | `prepare.blocked`               |

The `grounding_invalidated` event is also emitted by automation outside the
state machine — when `telec todo prepare --invalidate-check` detects file path
overlap after an integration delivery.

## Outputs

1. Preparation artifacts produced through the state machine phases:
   `requirements.md`, test specification files (expected-failure-marked),
   `implementation-plan.md`.
2. Each artifact reviewed and approved before the next phase begins.
3. Grounding metadata in `todo state (todos.db)` for staleness detection.
4. State machine-driven session cleanup on the PREPARED terminal.

## Recovery

1. If a worker session fails, read the error and retry once. On second failure,
   record the blocker and stop.
2. If the state machine returns an unexpected instruction, log it and stop.
   Do not improvise — the machine owns sequencing.
3. If direct conversation with a worker stalls, write blockers to `dor-report.md`
   and proceed to cleanup.
