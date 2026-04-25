---
description: 'Prepare phase overview. Pair-based discovery, turn-based artifact production, human approval, and grounding.'
id: 'software-development/procedure/lifecycle/prepare'
scope: 'domain'
type: 'procedure'
---

# Prepare — Procedure

## Goal

Produce reviewed, human-approved, and grounded preparation artifacts for a todo
through a persistent pair of workers who explore the problem together and then
produce artifacts in turns.

The prepare state machine (`telec todo prepare`) owns sequencing. The orchestrator
calls it in a loop and dispatches what is requested. The detailed orchestrator
procedure is in `prepare/overview.md`.

## Preconditions

- `todos.db` roadmap exists and is readable.
- Target slug is active (not icebox, not delivered).

## Steps

### 1. Human handoff

The human provides a work package — a brain dump, existing requirements, or any
starting state. The human may also edit preparation artifacts directly at any
time and hand the todo back to the machine with `telec todo reconcile {slug}`.

### 2. Discovery (pair-based)

Both workers are dispatched with the same work package. Each independently
reads and grounds itself (intake). After both complete intake, the orchestrator
links them via direct conversation. They explore the problem together — no
roles assigned. They surface hidden assumptions, check against codebase
reality, resolve unknowns, and converge on understanding.

### 3. Requirements (turn-based)

`A` writes `requirements.md` — recording what the pair discussed. `B` reviews:
did the writer capture everything? Fix-forward if gaps are found.

### 4. Human approval

The human reviews requirements. The human may talk directly to the pair to
refine. Both workers see the human's input via the direct link. Fix-forward
only — no going back to discovery. When satisfied, the orchestrator stamps
approval.

### 5. Test specs (turn-based)

`A` writes expected-failure-marked test specifications. `B` reviews.
Specs stay close to approved requirements while context is hot.

### 6. Implementation plan (turn-based)

`B` writes the implementation plan. `A` reviews.
The plan is derived from both requirements and test specs.

### 7. Grounding check (mechanical)

The machine verifies referenced file freshness. If stale, the plan writer
updates and the reviewer re-reviews. If fresh: PREPARED.

### 8. Split inheritance

When a todo is split via `telec todo split`, children inherit the parent's
highest approved prepare phase and artifacts. Skipped phases are recorded in
audit with `reason: "inherited_from_parent"`.

## Outputs

- `requirements.md` — pair-discovered, human-approved.
- Test specification files (expected-failure-marked).
- `implementation-plan.md` — review-aware, rationale-rich.
- Grounding metadata in `todos.db` state.
- Events emitted at each phase transition.

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

## Recovery

- If any phase blocks, the state machine records the blocker and stops.
- Fix-forward only — preserve what has been done, correct from current state.
