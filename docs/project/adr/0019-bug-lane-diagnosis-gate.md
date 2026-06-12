---
adr_status: accepted
date: 2026-06-08
description: Bugs enter a mandatory diagnosis prepare stage and reuse the change plan→plan-review→build
  pipeline, replacing the no-prepare fix lane.
number: 19
supersedes:
  - project/adr/0015-kind-as-lifecycle-entry-point
visibility: public
---

# Bug Lane Diagnosis Gate — ADR

## Context

ADR `0015-kind-as-lifecycle-entry-point` mapped each SDLC kind to a lifecycle
entry point and routed `bug` straight to a fix lane: born at `PREPARED`, no PRD,
no upfront plan, with diagnosis embedded inside the `/next-bugs-fix` worker
session. In practice that conflation produced the failure this decision corrects:
the fix worker diagnoses and fixes in one ungated breath, the root cause is never
verified against the code before the fix is written, and "delivered yet ineffective"
fixes result (the Discord typing-indicator fix is the motivating example — it
passed review and fixed nothing).

The forces in play: bugs must not skip pre-work, but they also must not become
heavier than a feature. A bug's "what to build" is _discovered_ (the diagnosis),
not _specified_, so the missing rigor is a verified diagnosis gate — not a PRD.

## Decision

Bugs gain a mandatory **diagnosis** prepare stage and otherwise reuse the existing
`change` pipeline. The full kind→entry-point mapping (superseding 0015) is:

- `feature` → `PRD_DRAFTING` (PRD/intake → architecture → plan → plan-review).
- `change` → `PLAN_DRAFTING` (no PRD; `input` is the intent).
- `bug` → `DIAGNOSE` (new) → `PLAN_DRAFTING` → `PLAN_REVIEW` → `PREPARED`.
- `task` → `PREPARED` (non-SDLC; created silent).

For a bug, the `DIAGNOSE` phase is loaded inline by the prepare orchestrator
(like plan-drafting). It reads code, reproduces the symptom, traces the root cause
to specific code, and **prescribes** the fix approach and a verification approach
(an executable reproduction where possible, or a documented observable reproduction
plus a plan task to build the missing functional/e2e coverage). It produces a
`diagnosis` artifact; it does not open a worktree or commit. `next-prepare-plan`
consumes `diagnosis` "when present" (exactly as it consumes `architecture`), with
no kind-branching. `next-review-plan` validates the diagnosis in one clearly-fenced
section gated on the artifact's presence — there is no separate diagnosis review.
The reproduction test is authored by the builder during `/next-build` (RED→GREEN);
`/next-bugs-fix` and the standalone `bug-fix` work procedure are retired.

## Consequences

Positive:

- No bug reaches code changes without a root cause verified against the code and a
  cross-model review (plan-review) of the fix approach. The verification-adequacy
  judgment — including "build new coverage for this hard-to-reproduce bug" — is owned
  by plan-review.
- Maximal reuse: bugs ride the existing plan-draft → plan-review → build →
  build-review machinery and the existing lifecycle-router auto-dispatch (`bug` now
  routes to `/next-prepare` like `change`). No parallel rails, one new phase.
- The bug lane is shorter than a feature (no PRD, no architecture), so the rigor does
  not overshoot intent.

Negative / costs:

- Adding `LifecyclePhase.DIAGNOSE` touches every prepare-phase switch site
  (~74 across the next_machine) — a real regression surface that must be covered by
  tests.
- Every bug now pays a cross-model plan-review hop, including trivial ones. This is
  accepted deliberately: a "trivial bug" classifier would be intelligence in the wrong
  layer, and trivial bugs yield trivial plans that clear review fast.
- Hard-to-reproduce bugs cannot always anchor on an executable reproduction; the
  diagnosis must then prescribe building coverage, and plan-review judges adequacy.
  This is weaker than a deterministic repro but is the design's honest answer to the
  motivating case.

Invariants going forward:

- A bug must hold a `diagnosis` artifact before it can derive `PLAN_DRAFTING`.
- `task` remains the only fast-tracked-to-`PREPARED` kind.
- The bug builder's mandate is the reviewed `implementation-plan` plus the
  `diagnosis`, never a bare bug/input artifact.

## Alternatives Considered

- **Keep 0015's fix lane, harden the worker procedure only.** Rejected: a
  within-worker gate doesn't separate diagnosis from fix and leaves the unverified-
  diagnosis failure mode intact.
- **Route bugs through a dedicated diagnosis + separate diagnosis-review phase.**
  Rejected: a second review dispatch per bug for no gain over folding the diagnosis
  check into the existing plan-review.
- **A standalone `bug-analysis` artifact carrying a bespoke fix prescription.**
  Rejected in favor of reusing `implementation-plan`, so `/next-build` (a proven
  DoD-complete executor) runs the fix and `/next-bugs-fix` retires.
