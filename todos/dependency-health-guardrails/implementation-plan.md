# Implementation Plan — Dependency Health Guardrails (API + Redis)

## Objective

Prevent destructive operations during dependency failures/timeouts, while enabling auto‑healing via circuit breakers and exponential backoff. Surface errors to clients without swallowing.

## Phase 0 (Immediate guardrails — applied)

- Timeouts are treated as errors, not session exits.
- Errors are surfaced to UI adapters; destructive cleanup is not triggered by timeout-derived signals.

## Phase 1 — Core health + circuit breakers

### 1. Health registry

- Add `teleclaude/core/health.py`:
  - `DependencyState` enum: `healthy | degraded | unhealthy`
  - `DependencyHealth` record: last_error, last_success, open_until, backoff_s
  - `HealthRegistry`: set/get state, record_success, record_failure

### 2. Circuit breaker wrapper

- Add `CircuitBreaker` class:
  - States: `Closed`, `Open`, `HalfOpen`
  - Exponential backoff with jitter; cap at 60s (configurable)
  - Single-flight probes during HalfOpen
- Wrapper API: `await breaker.call(dep_name, coro, probe_coro=None)`
  - If Open: raise `DependencyUnhealthy(retry_after=...)`
  - If HalfOpen: allow probe only
  - On success: close breaker
  - On failure: re-open with increased backoff

### 3. Standard error payload

- Add `DependencyUnhealthy` exception:
  - `dependency`, `retry_after`, `health_state`
- Ensure adapters/CLI receive human-readable message with retry time

## Phase 2 — Global safety gate (destructive ops)

- Add guard in destructive paths (terminate/delete/cleanup):
  - If any critical dependency unhealthy → deny with error
  - Surface to clients: "System unhealthy; retry in Xs"
- Gate targets:
  - `session_cleanup.terminate_session`
  - `command_handlers.close_session/end_session` (if not explicitly user‑confirmed)
  - any adapter channel/topic deletion calls

## Phase 3 — Auto‑healing probes

- Background probe loop per dependency:
  - Lightweight health checks only
  - Exponential backoff with jitter
  - Transition Open → HalfOpen → Closed

## Phase 4 — Backpressure + load shedding

- When unhealthy:
  - Drop/skip heavy reads
  - Pause cache refresh loops
  - Reduce polling frequency

## Phase 5 — Operator visibility

- Log health transitions + retry timing
- UI/CLI surface: "Dependency unhealthy; retry in Xs"

## Rollout notes

- Start with Redis + API wrapper at call sites
- Enable health gate for destructive ops once breaker is in place
- Add probes after breaker correctness is verified
