# Implementation Plan: fix-integration-queue-ghost

## Overview

Two surgical changes: (1) remove queue.json enqueue from daemon wiring, (2) remove the
handed_off TTL guard from the worktree scanner. Both are small, well-isolated edits.

## Phase 1: Core Changes

### Task 1.1: Remove queue.json enqueue from daemon wiring

**File(s):** `teleclaude/daemon_event_platform.py`

- [x] In `_build_integration_trigger()`, remove `IntegrationQueue` import and instantiation
- [x] Remove `integration_queue.enqueue(...)` call from `_ingest_callback`
- [x] Keep `_ingest_callback` feeding the projection (return ready candidates for spawn)
- [x] Keep `spawn_callback=spawn_integrator_session` (spawn path must stay)

### Task 1.2: Accept handed_off candidates unconditionally in scanner

**File(s):** `teleclaude/core/integration/step_functions.py`

- [x] In `_scan_finalize_ready_candidates()` (~line 290): change the `handed_off` branch to accept unconditionally instead of checking `handed_off_at < TTL`
- [x] In `_verify_slug_ready()` (~line 350): same change — accept `handed_off` without TTL guard
- [x] The lease prevents concurrent processing, so the TTL guard is redundant

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Update `tests/unit/core/integration/test_auto_enqueue.py` for scanner behavior change
- [x] Verify existing integration tests pass with `handed_off` acceptance
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
