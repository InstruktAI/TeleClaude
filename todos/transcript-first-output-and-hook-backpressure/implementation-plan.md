# Implementation Plan - transcript-first-output-and-hook-backpressure

## Objective

Unify output into a single transcript-driven producer, keep hooks strictly control-plane, and add bounded backpressure/coalescing so burst hook traffic cannot overwhelm the system.

## Preconditions

- No new third-party dependencies are required.
- Existing hook outbox and output polling infrastructure are reused and tightened.
- Verification must be executable through deterministic tests (no interactive-only gate).

## Requirement Traceability

- `R1` Single output producer -> Phases 1, 3, 5
- `R2` Hook role as control plane only -> Phases 1, 3, 5
- `R3` Bounded backpressure/coalescing -> Phases 2, 4, 5
- `R4` Deterministic cadence/final flush -> Phases 1, 3, 5
- `R5` Observability and noise control -> Phases 4, 5

## Phase 1 - Establish Single Output Data Plane (R1, R2, R4)

- [ ] Enumerate all output producer call sites and mark one canonical producer path.
- [ ] Remove direct output fanout from hook-driven `tool_use` / `tool_done` handlers.
- [ ] Keep session-stop final flush behavior intact.
- [ ] Verify output progression still occurs from transcript deltas on cadence tick.

### Files (expected)

- `teleclaude/core/agent_coordinator.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/output_poller.py`
- related adapter send paths only as needed

## Phase 2 - Hook Backpressure and Coalescing Policy (R3)

- [ ] Apply explicit event classification (`critical` vs `bursty`) from requirements.
- [ ] Implement bounded per-session processing for bursty hook classes at the actual queue point.
- [ ] Implement coalescing strategy for bursty classes (latest-wins or per-turn aggregate).
- [ ] Preserve strict ordering and non-drop behavior for critical events.

### Files (expected)

- `teleclaude/daemon.py` (session outbox queue and worker dispatch)
- `teleclaude/core/db.py` / `teleclaude/core/db_models.py` (if queue state persistence changes)
- `teleclaude/core/agent_coordinator.py`
- `teleclaude/hooks/receiver.py` (only if classification inputs change)

## Phase 3 - Cadence and Contract Hardening (R1, R2, R4)

- [ ] Keep default output cadence at 1.0s with explicit configurability.
- [ ] Document contract: transcript cadence drives output publication; hooks are control-plane only.
- [ ] Confirm no hidden fast path bypasses remain.

### Files (expected)

- `teleclaude/core/output_poller.py`
- `teleclaude/config/*` (if interval is made configurable)
- architecture/spec docs

## Phase 4 - Observability and Noise Control (R3, R5)

- [ ] Add metrics/counters for queue depth, lag, coalesced count, and output tick/fanout.
- [ ] Replace per-event spam with sampled summary logs for suppression/coalescing paths.
- [ ] Add warning thresholds for sustained lag/backlog.

### Files (expected)

- `teleclaude/daemon.py`
- `teleclaude/core/agent_coordinator.py`
- metrics/logging plumbing used by daemon/runtime

## Phase 5 - Validation and Safety (R1-R5)

- [ ] Unit tests for single-producer enforcement and no duplicate output emission.
- [ ] Unit/integration tests for bounded queue/coalescing behavior.
- [ ] Regression tests for session-stop final flush.
- [ ] Synthetic burst test that asserts lag targets (`p95 < 1s`, `p99 < 3s`) under normal load profile.
- [ ] Update `demo.md` commands so `telec todo demo run transcript-first-output-and-hook-backpressure` is executable.

### Files (expected)

- `tests/unit/test_agent_coordinator.py`
- `tests/unit/test_threaded_output_updates.py`
- `tests/unit/test_polling_coordinator.py`
- `tests/unit/test_daemon.py`
- `tests/unit/test_hook_receiver.py`
- additional targeted tests as needed

## Rollout Notes

- Roll out in two steps:
  - Step A: disable hook-driven output fanout.
  - Step B: enable bounded coalescing/backpressure.
- Keep a short-lived feature flag if rollback safety is needed during cutover.

## Definition of Done

- [ ] One canonical output producer path remains.
- [ ] Hook bursts no longer cause output duplication/flood behavior.
- [ ] Hook backlog is bounded with measurable lag targets.
- [ ] Tests and docs updated to reflect the new contract.
