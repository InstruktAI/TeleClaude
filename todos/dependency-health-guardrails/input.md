# Dependency Health Guardrails (API + Redis)

## Context

- Two critical dependencies (API socket + Redis transport) are unstable.
- Failures/timeouts are cascading into destructive operations (session termination, topic deletion).
- We already propagate errors to adapters/clients; we should leverage that to suppress destructive actions when unhealthy.

## Goal (High-Level)

- Introduce circuit-breaking + health-gated behavior so **errors/timeouts never trigger destructive ops**.
- Provide auto-healing probes with exponential backoff + jitter.
- Surface health state to clients with retry timing.

## Proposed Architecture

1. **Local Circuit Breakers** per dependency (API, Redis)
   - States: Closed, Open, Half-open
   - Exponential backoff with jitter; single-flight probes
   - On open: block real traffic; return fast error with `retry_after`

2. **Shared Health State**
   - `api: healthy|degraded|unhealthy`
   - `redis: healthy|degraded|unhealthy`
   - Aggregate to overall system health

3. **Global Safety Gate**
   - If any critical dependency is unhealthy, **block destructive operations**
   - Degrade to non-destructive behaviors (pause polling, mark unknown)

4. **Error Propagation**
   - Standard error payload includes dependency, retry_after, health state
   - Adapters/CLI show: "System unhealthy; retrying in Xs"

## Quick Alleviation (Immediate Patch)

- Treat timeouts as **errors** and **never as session exit**.
- Stop destructive cleanup on timeout-derived signals.
- Log and surface errors to UI adapters.

## Follow-up

- Implement health registry + circuit breaker wrapper
- Wire health gate into termination/cleanup paths
- Add probe scheduler and backoff policy
