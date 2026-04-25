---
id: 'software-development/procedure/lifecycle/prepare/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Prepare stage overview. Orchestrator drives the pair through discovery, artifact production, human approval, gate, and grounding.'
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discovery.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/readiness-gate.md

## Goal

Drive the prepare state machine by calling `telec todo prepare [slug]` in a loop.
The machine dispatches a persistent pair of workers who explore the problem
together and then produce artifacts in turns. The orchestrator dispatches what
the machine requests and supervises the pair.

Produce reviewed, human-approved, and grounded preparation artifacts for a todo.

## Preconditions

1. `todos.db` roadmap exists and is readable.
2. Target slug is active (not icebox, not delivered) when slug is provided.

## Steps

### 1. Enter the state machine

Call `telec todo prepare [slug]`. Read the returned instruction block.

### 2. Execute the instruction

The state machine returns a linear script for the current state. The
orchestrator executes it verbatim and then calls `telec todo prepare [slug]`
again. The orchestrator never makes routing decisions — the machine owns
sequencing.

### The prepare flow

#### Discovery (pair-based)

The machine dispatches both workers and links them via
`telec sessions send <session> --direct`. Both workers receive the same input —
whatever the todo carries (brain dump, existing requirements, any starting
state). Both read the codebase, the roadmap, and applicable docs.

They explore the problem together through direct conversation. No roles are
assigned during discovery. Both contribute freely through their natural lens.
They surface hidden assumptions, check against reality, challenge each other's
thinking, and converge on understanding.

Discovery ends when the pair has converged. The machine then assigns a writer.

#### Requirements (turn-based)

`A` writes `requirements.md` — recording what the pair discussed and agreed on.
`B` reviews: did the writer capture everything? Is anything missing or
misrepresented?

If the review finds gaps (`needs_work`), the writer corrects. When the pair
agrees the requirements are complete, they are ready for human approval.

#### Human approval of requirements

The human reads the requirements. The human may talk directly to the pair
(the writer) to add or correct things. When the human is satisfied, the
orchestrator stamps requirements as approved.

**Human approval is explicit and non-optional.** The machine does not proceed
to test specs until the human has approved requirements.

#### Test specs (turn-based)

`A` writes test specifications (expected-failure-marked). `B` reviews.
Specs stay close to the just-approved requirements while context is hot.

#### Implementation plan (turn-based)

`B` writes the implementation plan. `A` reviews.
The plan is derived from both requirements and test specs.

#### Gate (pair self-assessment)

The pair checks their own complete artifact set against Definition of Ready.
This is self-assessment — the pair evaluates whether what they produced is
ready to build.

- **`pass`** → the machine continues to grounding check.
- **`needs_work`** → the pair identified gaps. The machine routes back to fix
  the deficient artifact.
- **`needs_decision`** → escalate to the human.

#### Grounding check

The machine checks whether referenced files have changed since the artifacts
were last grounded.

- If fresh: PREPARED.
- If stale: the plan must be updated against the current codebase and
  re-reviewed.

#### PREPARED

Terminal success. The machine emits cleanup for all live sessions tied to the
slug. Execute verbatim.

#### BLOCKER

The machine cannot proceed (human decision needed, review rounds exhausted).
Sessions stay alive as signal for the human.

### 3. Supervision

After dispatching workers:

1. Set a heartbeat timer.
2. Wait for worker notifications.
3. On notification: call `telec todo prepare [slug]` again to advance.
4. If a worker stalls (heartbeat fires with no progress), open a direct
   conversation to resolve. If still stuck after two iterations, record
   blockers and stop.

### Human touchpoints

- The human may edit preparation artifacts directly at any time, then hand the
  todo back to the machine with `telec todo reconcile [slug]`.
- The human approves requirements before test specs begin.
- The human may be escalated to when the machine or pair encounters a blocker
  requiring judgment.

### Events

| Phase transition            | Event                           |
| --------------------------- | ------------------------------- |
| Discovery dispatched        | `prepare.discovery_started`     |
| Requirements written        | `prepare.requirements_drafted`  |
| Requirements human-approved | `prepare.requirements_approved` |
| Test specs written          | `prepare.test_specs_drafted`    |
| Test specs reviewed         | `prepare.test_specs_approved`   |
| Plan written                | `prepare.plan_drafted`          |
| Plan reviewed               | `prepare.plan_approved`         |
| Grounding invalidated       | `prepare.grounding_invalidated` |
| Re-grounding completed      | `prepare.regrounded`            |
| Preparation complete        | `prepare.completed`             |
| Preparation blocked         | `prepare.blocked`               |

## Outputs

1. `requirements.md` — human-approved.
2. Test specification files (expected-failure-marked).
3. `implementation-plan.md`.
4. Grounding metadata in `todos.db` state.
5. Session cleanup on PREPARED terminal.

## Recovery

1. If a worker session fails, read the error and retry once. On second failure,
   record the blocker and stop.
2. If the state machine returns an unexpected instruction, log it and stop.
3. If direct conversation with a worker stalls, write blockers to `dor-report.md`
   and stop.
