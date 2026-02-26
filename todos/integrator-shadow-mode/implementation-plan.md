# Implementation Plan: integrator-shadow-mode

## Plan Objective

Stand up a production-like integrator runtime in non-destructive shadow mode.

## Phase 1: Lease and Queue Core

### Task 1.1: Implement lease lifecycle

**File(s):** `teleclaude/core/integration/lease.py`

- [ ] Implement atomic acquire/renew/release for `integration/main`.
- [ ] Implement stale-lease break behavior when TTL expires.

### Task 1.2: Implement durable queue processing

**File(s):** `teleclaude/core/integration/queue.py`, `teleclaude/core/integration/runtime.py`

- [ ] Process candidates FIFO by `ready_at`.
- [ ] Record auditable status transitions.

## Phase 2: Shadow Runtime Behavior

### Task 2.1: Simulate integration outcomes without main push

**File(s):** `teleclaude/core/integration/runtime.py`

- [ ] Re-check readiness before each candidate apply.
- [ ] Emit `would_integrate` or `would_block` without pushing canonical `main`.

### Task 2.2: Tests and quality checks

**File(s):** `tests/unit/test_integrator_shadow_mode.py`, `tests/integration/test_integrator_shadow_mode.py`

- [ ] Add concurrency, lease-expiry, FIFO, and restart coverage.
- [ ] Run `make test`.
- [ ] Run `make lint`.

## Phase 3: Review Readiness

- [ ] Confirm shadow mode cannot push canonical `main` under any path.
- [ ] Confirm runtime remains resumable after restart.
