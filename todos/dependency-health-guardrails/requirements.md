# Requirements: Dependency Health Guardrails

## Intent

Prevent dependency outages (API socket and Redis transport) from triggering destructive operations, while preserving operator visibility and automatic recovery behavior.

## Why

Current timeout/failure cascades can incorrectly drive cleanup paths (session termination, channel/topic deletion). This causes avoidable data/session loss and amplifies incidents.

## In Scope

1. Dependency health model for API socket and Redis transport (`healthy`, `degraded`, `unhealthy`).
2. Circuit-breaker behavior for dependency-facing calls (closed/open/half-open).
3. Standard unhealthy-dependency error payload with retry timing.
4. Safety gate that blocks destructive operations while critical dependencies are unhealthy.
5. Recovery probing with exponential backoff + jitter.
6. Operator/client visibility for health transitions and retry expectations.

## Out of Scope

1. Replacing Redis or socket transport architecture.
2. New external observability vendors or alerting platforms.
3. Non-critical dependency hardening unrelated to API socket/Redis.

## Functional Requirements

### FR1: Dependency Health State

1. The system MUST track per-dependency health for `api_socket` and `redis_transport`.
2. The system MUST expose aggregate critical-dependency health.
3. State transitions MUST capture timestamp + causal error context.

### FR2: Circuit Breaking

1. Dependency-facing calls MUST pass through a breaker decision path.
2. Open breaker MUST fail fast with explicit retry timing.
3. Half-open mode MUST allow controlled probe traffic only.
4. Backoff MUST use exponential growth with jitter and configurable max interval.

### FR3: Safety Gate for Destructive Operations

1. Destructive operations MUST be blocked when any critical dependency is `unhealthy`.
2. At minimum, guards MUST cover session termination/cleanup and channel/topic deletion paths.
3. Guard denials MUST return actionable errors (dependency + retry guidance), not silent drops.

### FR4: Error Contract

1. Unhealthy dependency errors MUST include: dependency identifier, health state, retry-after seconds.
2. Adapter/API/MCP surfaces MUST preserve this context for user-visible messaging.

### FR5: Recovery Probes

1. System MUST attempt auto-recovery probes after breaker open events.
2. Probe cadence MUST honor breaker backoff policy.
3. Success path MUST transition to healthy/closed state and log transition.

## Verification Requirements

1. Timeout/failure scenarios MUST demonstrate no destructive cleanup triggered by dependency errors.
2. Breaker open/half-open/closed transitions MUST be test-covered.
3. Destructive command paths MUST have explicit tests for blocked behavior under unhealthy state.
4. Logs MUST include health transitions and retry timing.
5. User-facing error responses MUST include retry timing and dependency identifier.

## Edge Cases (Required or Deferred)

1. Simultaneous degradation of both dependencies.
2. Flapping dependency (repeated open/close transitions).
3. Manual session-end requests while system is unhealthy.
4. Partial recovery where one dependency returns while another remains unhealthy.

## Constraints and Assumptions

1. Existing timeout handling and error propagation plumbing remains the base path.
2. Guardrails are additive and must not break healthy-path latency materially.
3. No new third-party dependency is expected for this scope.

## Open Questions

1. Should user-confirmed explicit session termination bypass the safety gate, or always block while unhealthy?
2. Which operations are classified as destructive beyond current known paths (final authoritative list needed)?
3. What degraded-state behavior is acceptable for cache refresh and polling (pause vs reduced frequency per subsystem)?
