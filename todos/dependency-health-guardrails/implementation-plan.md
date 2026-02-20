# Implementation Plan: Dependency Health Guardrails

## Plan Objective

Deliver safe failure behavior for API socket + Redis outages so destructive operations are blocked during unhealthy periods, with clear recovery and operator visibility.

## Proposed Work Breakdown

This item is broad and cross-cutting. Draft recommendation is to execute as dependent phases, each with explicit exit checks.

### Phase 1: Health + Circuit-Breaker Foundation

1. Add dependency health model and breaker primitives.
2. Standardize unhealthy-dependency exception contract (`dependency`, `state`, `retry_after`).
3. Wire wrappers at key API socket / Redis call boundaries.

Verification:

1. Unit tests for breaker transitions and backoff behavior.
2. Unit tests for error payload shape and retry-after semantics.

### Phase 2: Destructive-Operation Safety Gate

1. Enumerate destructive paths and add health gate checks.
2. Ensure blocked operations return explicit, non-destructive errors.
3. Confirm no timeout-derived signal directly triggers destructive cleanup.

Verification:

1. Integration tests proving cleanup/termination/delete paths are blocked when unhealthy.
2. Regression tests proving healthy-state behavior remains unchanged.

### Phase 3: Recovery Probes + Controlled Backpressure

1. Add probe scheduling driven by breaker state.
2. Add subsystem-level degraded behavior (reduced/paused heavy polling where appropriate).
3. Ensure transition logging is emitted for unhealthy -> recovering -> healthy.

Verification:

1. Tests for recovery progression (open -> half-open -> closed).
2. Observability checks for transition logs and retry timing.

### Phase 4: Client/Operator Surface Hardening

1. Ensure adapters/API/MCP endpoints preserve and expose retry context.
2. Normalize user-facing messages across surfaces.

Verification:

1. Endpoint/adapter tests for propagated dependency + retry data.
2. Manual smoke checks with injected Redis/API failures.

## Entry and Exit Criteria

Entry:

1. Requirements are approved with destructive-operation scope clarified.
2. Dependency classification (`critical`) is finalized for API socket + Redis.

Exit:

1. All verification checks above pass.
2. No destructive operation is reachable from timeout/failure cascades.
3. Recovery path is observable and deterministic under fault injection.

## Dependencies and Preconditions

1. No upstream todo dependency currently declared in `todos/roadmap.yaml`.
2. Requires local fault-injection capability (or deterministic test doubles) for Redis/API failures.
3. Requires agreement on explicit bypass policy for user-forced termination requests.

## Risks and Mitigations

1. Risk: Over-blocking legitimate admin operations during transient issues.
   Mitigation: Define narrow destructive operation list + explicit policy for forced actions.
2. Risk: Flapping causes noisy state transitions.
   Mitigation: Jittered backoff + transition logging throttling policy.
3. Risk: Cross-cutting wiring misses one destructive path.
   Mitigation: Centralized destructive-op inventory and regression tests per path.

## Recommended Split (If Needed)

If a single builder session cannot complete safely, split into:

1. `dependency-health-core` (phase 1)
2. `dependency-health-safety-gate` (phase 2)
3. `dependency-health-recovery-backpressure` (phase 3-4)
