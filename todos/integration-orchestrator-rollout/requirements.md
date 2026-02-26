# Requirements: integration-orchestrator-rollout

## Goal

Define the rollout contract that moves TeleClaude from parallel worker-driven
mainline integration to an event-driven singleton integrator model, while
preserving high-throughput parallel branch work.

## Why

Parallel workers should keep shipping independently, but canonical `main`
integration must be serialized, auditable, and low-risk.

## In Scope

1. Rollout-level requirements for the five integration slices:
   1. `integration-safety-gates` (already delivered)
   2. `integration-events-model`
   3. `integrator-shadow-mode`
   4. `integrator-cutover`
   5. `integration-blocked-flow`
2. Dependency ordering and phase-gated progression across those slices.
3. Integration authority boundary (`main` is integration-owned).
4. Rollout-level verification expectations and go/no-go evidence.
5. Explicit traceability for the launcher-runtime hardening included in this branch at
   `teleclaude/adapters/discord_adapter.py::_build_session_launcher_view`.

## Out of Scope

1. Implementing the internals of child slices in this parent todo, beyond the scoped
   launcher-runtime hardening listed in "In Scope".
2. Replacing Git workflow fundamentals (worktrees/feature branches stay).
3. Non-integration architecture work outside the orchestrator contract.

## Functional Requirements

### FR1: Ordered Rollout

1. The rollout MUST execute in the five ordered slices defined in `input.md`.
2. `integration-safety-gates` completion MUST remain a prerequisite for later slices.
3. Each subsequent slice MUST depend on completion of the prior slice.

### FR2: Integrator Authority Boundary

1. Canonical `main` merge/push authority MUST be reserved for the integrator.
2. Workers and finalizers MAY continue pushing non-main feature/worktree branches.

### FR3: Event-Driven Readiness Contract

1. The rollout MUST use `review_approved`, `finalize_ready`, and `branch_pushed`
   as canonical readiness signals.
2. Readiness MUST require branch/sha alignment and remote reachability checks as
   defined in `docs/project/spec/integration-orchestrator.md`.
3. `worktree dirty -> clean` MUST NOT be treated as an integration-ready signal.

### FR4: Serialized Integration Runtime

1. Integration execution MUST be singleton via lease key `integration/main`.
2. Candidate processing MUST be queue-backed and FIFO by readiness timestamp.
3. Each candidate MUST resolve to `integration_completed`, `integration_blocked`,
   or `superseded` without partial mainline pushes.

### FR5: Shadow-Then-Cutover Progression

1. Shadow mode MUST run singleton orchestration without canonical `main` merges.
2. Cutover MUST make the integrator the only path that can merge/push canonical
   `main`.
3. Blocked integration flow MUST emit actionable evidence and create resumable
   follow-up work.

## Verification Requirements

1. `todos/roadmap.yaml` MUST encode the rollout dependency order.
2. Each active child slice MUST have draft+gate artifacts before build dispatch.
3. Cutover acceptance MUST verify no non-integrator path can push canonical `main`.
4. Blocked-flow acceptance MUST verify conflict cases produce resumable,
   evidence-rich blocked outcomes.

## Constraints and Assumptions

1. Local-first development remains default.
2. Big-bang replacement is disallowed; rollout is incremental and shippable per slice.
3. `docs/project/spec/integration-orchestrator.md` is the source-of-truth contract.
4. No new third-party integration is introduced by this parent rollout scope.

## Risks

1. Cutover risk if legacy merge/push paths remain reachable.
2. Event contract drift between parent and child slice plans.
3. Queue/lease edge cases causing stalled integration if resume semantics are unclear.

## Open Questions

1. What exact parity evidence is required before shadow-mode exit is allowed?
2. What is the authoritative follow-up todo template for `integration_blocked`?
3. What explicit rollback trigger allows temporary cutover reversal, if any?
