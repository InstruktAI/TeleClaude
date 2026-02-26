# Requirements: integrator-shadow-mode

## Problem

Canonical `main` integration is currently executed directly by finalize apply
instructions in `next_machine`. The singleton lease+queue integrator contract is
defined in `docs/project/spec/integration-orchestrator.md`, but there is no
runtime path that continuously exercises that contract in production-like flow
without writing to canonical `main`.

## Intended Outcome

Run an event-driven singleton integrator in **shadow mode** that:

1. consumes canonical readiness inputs,
2. applies the same lease/queue/readiness rules as the orchestrator spec,
3. records deterministic "would integrate / would block / superseded" outcomes,
4. performs zero canonical `main` merge/push mutations.

This slice provides parity evidence before `integrator-cutover`.

## Scope

### In scope

1. **R1 - Shadow runtime lifecycle**
   Add an integrator runtime that starts from ready work, drains queue serially,
   and exits cleanly when queue is empty and checkpointed.
2. **R2 - Singleton lease + durable queue**
   Implement lease semantics (`integration/main`) and durable queue semantics
   (FIFO by `ready_at`, dedupe by candidate key, explicit status transitions).
3. **R3 - Readiness and supersession parity**
   Evaluate readiness using canonical signals from `integration-events-model`
   (`review_approved`, `finalize_ready`, `branch_pushed`) including supersession checks.
4. **R4 - Shadow-only execution contract**
   For each queued candidate, perform dry-run evaluation and record result as
   `would_integrate`, `would_block`, or `superseded` with evidence; do not
   merge/push canonical `main`.
5. **R5 - Observability and audit trail**
   Emit grep-friendly logs and persist outcome records sufficient to compare
   shadow decisions against current live finalize outcomes.
6. **R6 - Legacy path containment**
   Preserve current finalize apply behavior during shadow phase; shadow mode is
   additive and must not become the canonical merge path in this slice.
7. **R7 - Verification coverage**
   Add tests for lease exclusivity, queue ordering/dedupe, restart/resume, and
   "no canonical main writes" guarantees.

### Out of scope

1. Enforcing integrator as the only merge path (`integrator-cutover` scope).
2. Follow-up todo creation/resume UX for blocked integrations
   (`integration-blocked-flow` scope).
3. Re-defining canonical integration events/payload schema
   (`integration-events-model` scope).
4. New third-party infrastructure, services, or libraries.

## Success Criteria

1. READY candidates are enqueued once and processed FIFO by readiness timestamp.
2. Concurrent triggers never create multiple active lease holders for
   `integration/main`.
3. Shadow runtime records per-candidate outcomes with candidate identity
   (`slug`, `branch`, `sha`) and rationale.
4. Shadow path never performs canonical `main` merge/push/delivery mutations.
5. Existing finalize apply path remains functional and unchanged for live merges.
6. Restart/resume recovers pending queue work and handles stale lease break per
   lease policy.
7. Tests and logs provide evidence for items 1-6.

## Verification Path

1. Unit tests for lease acquisition/renewal/release and queue FIFO/dedup logic.
2. Unit/integration tests for shadow outcomes (`would_integrate`,
   `would_block`, `superseded`) and restart/resume behavior.
3. Regression tests confirming existing finalize apply instructions still perform
   canonical merge/push in this pre-cutover phase.
4. Operational log checks via `instrukt-ai-logs teleclaude --since <window> --grep <pattern>`.

## Dependencies and Preconditions

1. `integration-events-model` must define and deliver canonical persisted
   readiness/projection interfaces consumed by shadow mode.
2. Daemon runtime remains available for background queue processing
   (`project/policy/daemon-availability`).
3. Shadow persistence stays in the single project database file
   (`project/policy/single-database`).

## Integration Safety

1. Shadow mode is explicitly additive; it cannot mutate canonical `main`.
2. Entry/exit boundaries are explicit (toggleable shadow runtime, no cutover in
   this slice).
3. Rollback is containment-first: disable shadow runtime and retain existing
   finalize path.

## Constraints

1. No adapter boundary violations (`project/policy/adapter-boundaries`).
2. No new third-party dependencies.
3. Any new persisted models require migration/backward-compatibility notes
   (`project/policy/data-modeling`).

## Risks

1. **Contract drift risk**: readiness behavior diverges from
   `integration-events-model` outputs.
2. **False confidence risk**: shadow outcomes appear green while live finalize
   path still has unmodeled failure edges.
3. **Operational noise risk**: insufficiently-structured logs make parity
   evidence hard to consume.
