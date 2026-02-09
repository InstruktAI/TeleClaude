# Requirements: Dependency Health Guardrails

## Goal

Introduce circuit-breaking and health-gated behavior for critical dependencies (API socket + Redis transport) so that timeouts and outages never trigger destructive operations like session termination or topic deletion.

## Problem Statement

Two critical dependencies (API socket and Redis transport) experience intermittent failures. When failures or timeouts cascade, they trigger destructive cleanup operations (session termination, topic deletion) that worsen the situation. The system needs explicit health tracking and safety gates.

## Scope

### In scope

1. **Health registry** — per-dependency health state tracking (healthy/degraded/unhealthy).
2. **Circuit breaker wrapper** — states (Closed/Open/HalfOpen), exponential backoff with jitter, single-flight probes.
3. **Standard error payload** — `DependencyUnhealthy` exception with retry_after and health state.
4. **Global safety gate** — block destructive operations when any critical dependency is unhealthy.
5. **Auto-healing probes** — background health checks per dependency with backoff.
6. **Backpressure** — reduce load during degraded states (pause cache refresh, reduce polling).
7. **Operator visibility** — log health transitions and retry timing, surface to UI/CLI.

### Out of scope

- Adding new dependencies or transports.
- Replacing Redis or API socket architecture.
- External monitoring integration (Datadog, etc.).

## Functional Requirements

### FR1: Health registry

- `DependencyState` enum: `healthy`, `degraded`, `unhealthy`.
- `DependencyHealth` record: `last_error`, `last_success`, `open_until`, `backoff_s`.
- `HealthRegistry` class: `set_state()`, `get_state()`, `record_success()`, `record_failure()`.
- Aggregate health to overall system health.

### FR2: Circuit breaker

- States: Closed (normal), Open (blocking), HalfOpen (probe only).
- Exponential backoff with jitter, cap at 60s (configurable).
- Single-flight probes during HalfOpen.
- API: `await breaker.call(dep_name, coro, probe_coro=None)`.
- On Open: raise `DependencyUnhealthy(retry_after=...)`.

### FR3: Safety gate

- Guard in destructive paths: terminate_session, close_session/end_session, channel/topic deletion.
- If any critical dependency unhealthy → deny with error.
- Surface to clients: "System unhealthy; retry in Xs".

### FR4: Error propagation

- `DependencyUnhealthy` exception with `dependency`, `retry_after`, `health_state`.
- Adapters/CLI receive human-readable message with retry timing.

### FR5: Auto-healing probes

- Background probe loop per dependency.
- Lightweight health checks only.
- Exponential backoff with jitter.
- Transition Open → HalfOpen → Closed on success.

### FR6: Backpressure

- When unhealthy: drop/skip heavy reads, pause cache refresh loops, reduce polling frequency.

## Non-functional Requirements

1. Circuit breaker must not add measurable latency to healthy-path calls.
2. Health state transitions must be logged at INFO level.
3. Probe overhead must be minimal (lightweight checks only).

## Acceptance Criteria

1. Timeouts on API/Redis never trigger session termination.
2. Circuit breaker opens after configurable failure threshold.
3. HalfOpen state allows single probe, closes on success.
4. Destructive operations blocked when dependency unhealthy.
5. Error messages include retry_after timing.
6. Health state logged on every transition.
7. Auto-healing probes restore Closed state after recovery.
8. Existing tests pass with health infrastructure in place.

## Dependencies

None — standalone infrastructure work.
