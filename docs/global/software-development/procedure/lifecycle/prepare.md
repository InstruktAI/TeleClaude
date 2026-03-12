---
description: 'Prepare phase overview. Sequential artifact production with review gates, driven by the prepare state machine.'
id: 'software-development/procedure/lifecycle/prepare'
scope: 'domain'
type: 'procedure'
---

# Prepare — Procedure

## Goal

Produce reviewed, approved, and grounded preparation artifacts for a todo through
sequential phases, each producing one artifact that is reviewed before the next begins.

The prepare state machine (`telec todo prepare`) owns sequencing. The orchestrator
calls it in a loop and dispatches what is requested.

## Preconditions

- `todos/roadmap.yaml` exists and is readable.
- Target slug is active (not icebox, not delivered).

## Steps

### 1. Input refinement (human-driven, optional)

The human refines their thinking via `next-refine-input`, which rewrites
`todos/{slug}/input.md` and invalidates grounding.

### 2. Discovery (solo or triangulated)

When `input.md` exists and `requirements.md` is not yet approved, the state machine
dispatches a discovery worker. The worker decides whether to run solo (when the input
is concrete enough) or triangulated with a complementary partner (when ambiguity,
hidden assumptions, or unresolved architectural tension remain). Either path converges
to produce `requirements.md`.

At the `input_assessment → requirements_review` transition, the machine records
`prepare.input_consumed` once — marking that the input has been handed off to the
discovery worker and requirements production has started.

### 3. Requirements review

`requirements.md` is reviewed for completeness, testability, grounding, and
review-awareness before advancing.

### 4. Plan drafting (single-agent)

From approved requirements, a single agent produces `implementation-plan.md` and
`demo.md`. The plan is rationale-rich and review-aware — anticipating what the
reviewer will check so the builder produces no surprises.

### 5. Plan review

`implementation-plan.md` is reviewed against policies, Definition of Done gates,
and review lane expectations before advancing.

### 6. DOR gate (formal validation)

The complete artifact set is validated as a coherent whole. Cross-artifact fidelity,
DOR gate compliance, and review-readiness preview. This is the only phase that
can authorize readiness transition.

### 7. Artifact staleness cascade (idempotent)

The machine tracks artifact digests in `state.yaml.artifacts` for `input`, `requirements`,
and `implementation_plan`. On every invocation, it checks:

- If `input.md` changed since last recorded digest → cascade: both `requirements` and
  `implementation_plan` are marked stale, phase reverts to discovery.
- If `requirements.md` changed → cascade: `implementation_plan` is marked stale, phase
  reverts to plan drafting.
- If no changes → no staleness, phase routing proceeds normally.

### 8. Grounding check (idempotent)

When all artifacts exist and are approved and digests are current, the machine verifies
referenced file freshness: referenced file paths are diffed against current main. If
everything matches: PREPARED. If stale: re-grounding dispatches an agent to update the
plan.

This makes `telec todo prepare` safe to call at any time — first call creates,
subsequent calls verify and heal.

### 9. Split inheritance

When a todo is split via `telec todo split`, children inherit the parent's highest
approved prepare phase:

- Parent `requirements_review.verdict == "approve"` → child starts at `plan_drafting`
  with parent `requirements.md` copied and requirements verdict inherited.
- Parent `plan_review.verdict == "approve"` → child starts at `prepared` (fully
  ready for build) with both artifacts copied and both verdicts inherited.
- Parent with no approvals → child starts at discovery (normal flow).

Skipped phases are recorded in `state.yaml.audit.<phase>` with
`status: "skipped"` and `reason: "inherited_from_parent"`. Events `prepare.split_inherited`
and `prepare.phase_skipped` are emitted per child.

## Outputs

- `todos/{slug}/requirements.md` — triangulated, reviewed, approved.
- `todos/{slug}/implementation-plan.md` — review-aware, rationale-rich, reviewed, approved.
- `todos/{slug}/demo.md` — draft demonstration plan.
- `todos/{slug}/dor-report.md` — gate assessment.
- `todos/{slug}/state.yaml` — grounding metadata and DOR verdict.
- Events emitted at each phase transition (see below).

### Events

The state machine emits events at each phase transition for automation,
notifications, and auditing. The human does not interact with these — they
are consumed by automation (invalidation checks, notifications).

| Phase transition | Event |
|---|---|
| Input refined | `prepare.input_refined` |
| Discovery dispatched | `prepare.discovery_started` |
| Input consumed (→ requirements_review) | `prepare.input_consumed` |
| Requirements written | `prepare.requirements_drafted` |
| Requirements approved | `prepare.requirements_approved` |
| Plan written | `prepare.plan_drafted` |
| Plan approved | `prepare.plan_approved` |
| Artifact written and tracked | `prepare.artifact_produced` |
| Artifact stale (cascade) | `prepare.artifact_invalidated` |
| Finding recorded by reviewer | `prepare.finding_recorded` |
| Finding resolved | `prepare.finding_resolved` |
| Scoped re-review dispatched | `prepare.review_scoped` |
| Phase skipped via inheritance | `prepare.phase_skipped` |
| Child inherits parent phase | `prepare.split_inherited` |
| Grounding invalidated | `prepare.grounding_invalidated` |
| Re-grounding completed | `prepare.regrounded` |
| Preparation complete | `prepare.completed` |
| Preparation blocked | `prepare.blocked` |

The `grounding_invalidated` event is also emitted by automation outside the
state machine — when `telec todo prepare --invalidate-check` detects file path
overlap after an integration delivery.

### HITL boundary

The human interacts only with `input.md` via `next-refine-input`. Once the
state machine starts, all phases are fully autonomous. No human gates exist
inside the machine. The only human-facing event is `prepare.blocked` when
a decision genuinely requires human input.

## Recovery

- If any phase blocks, the state machine records the blocker and stops.
- The todo folder is the durable evidence trail for all outcomes.
