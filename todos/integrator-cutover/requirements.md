# Requirements: integrator-cutover

## Problem

Canonical `main` integration is still executed through orchestrator-owned
finalize apply steps. That keeps a non-integrator path capable of merging and
pushing `main`, which violates the singleton integrator authority model defined
in `docs/project/spec/integration-orchestrator.md`.

## Intended Outcome

Cut over to the event-driven singleton integrator as the only path that can
merge and push canonical `main`, while preserving deterministic safety checks,
serialized queue processing, and operational containment controls.

## Scope

### In scope

1. **R1 - Integrator authority cutover**
   Make integrator runtime execution the sole owner of canonical `main`
   merge/push operations.
2. **R2 - Legacy finalize-apply retirement**
   Remove/disable orchestrator-owned canonical merge/push steps from
   `next-finalize` post-completion flow; finalize remains evidence-producing
   (`FINALIZE_READY`) only.
3. **R3 - Live apply mode on integrator runtime**
   Promote the shadow lease+queue runtime from observational outcomes to real
   integration apply outcomes (`integration_completed`, `integration_blocked`).
4. **R4 - Safety gate parity at apply boundary**
   Preserve pre-apply safety guarantees from `integration-safety-gates` (dirty
   canonical main, main-ahead/divergence, unknown git state) before canonical
   writes.
5. **R5 - Blocked integration containment**
   On conflicts or failed apply preconditions, emit blocked outcome evidence and
   never push partial `main` state.
6. **R6 - Cutover observability**
   Emit grep-friendly logs and persistent outcomes proving candidate identity,
   authority owner, result, and rationale.
7. **R7 - Rollback/containment control**
   Provide an explicit operational control to pause write-capable cutover mode
   (or return to non-writing behavior) without dropping queue state.
8. **R8 - Verification coverage**
   Add tests and operational checks that prove the new authority boundary and
   no-legacy-write guarantee.

### Out of scope

1. Follow-up todo creation/resume UX for blocked cases
   (`integration-blocked-flow` scope).
2. Redefining canonical event schema (`integration-events-model` scope).
3. New third-party services, libraries, or infrastructure.
4. Non-integration workflow redesign outside canonical `main` authority
   boundaries.

## Success Criteria

1. No non-integrator code path can merge/push canonical `main`.
2. Finalize post-completion flow no longer contains canonical merge/push apply
   steps.
3. Integrator processes `READY` candidates serially under lease
   `integration/main` and performs canonical apply in cutover mode.
4. Conflict/precondition failures produce blocked outcomes with evidence and no
   partial push.
5. Safety re-checks run at integrator apply time before canonical writes.
6. Containment toggle can pause canonical writes without corrupting queue/lease
   state.
7. Logs and persisted outcomes are sufficient to audit each integration
   decision.
8. Automated tests cover authority boundary, success path, blocked path, and
   containment behavior.

## Verification Path

1. Unit/integration tests for:
   - finalize flow no longer performing canonical apply,
   - integrator-owned apply path success/blocked outcomes,
   - lease-serialized integration behavior during cutover.
2. Regression tests for canonical safety gates at apply boundary.
3. Static checks that legacy canonical push commands are absent from finalize
   post-completion template.
4. Operational log checks via:
   `instrukt-ai-logs teleclaude --since <window> --grep "integration_completed|integration_blocked|integration/main|cutover"`.

## Dependencies and Preconditions

1. `integration-events-model` delivers canonical readiness projection and event
   persistence.
2. `integrator-shadow-mode` delivers durable lease+queue runtime foundation.
3. `integration-safety-gates` protections remain active and enforceable at the
   cutover apply boundary.
4. Daemon runtime remains available (`project/policy/daemon-availability`).
5. Persistence remains in canonical single DB (`project/policy/single-database`).

## Integration Safety

1. Cutover is controlled by explicit mode/config, not implicit behavior.
2. Entry/exit boundaries are explicit: enable cutover, disable cutover
   (containment), preserve queue integrity.
3. Canonical writes are all-or-nothing per candidate; blocked outcomes never
   push partial state.

## Constraints

1. Preserve adapter/core boundaries (`project/policy/adapter-boundaries`).
2. No host-level service management changes.
3. No new third-party dependencies in this slice.

## Risks

1. **Residual legacy path risk**: overlooked finalize/apply seams could still
   push `main`.
2. **State handoff risk**: queue items accumulated in shadow mode may require
   careful transition semantics at cutover.
3. **Containment misuse risk**: unclear pause/resume procedure could stall
   integration throughput.
