# Implementation Plan: integration-event-chain-phase2

## Overview

Wire the ReadinessProjection into the IntegrationTriggerCartridge as the integration gate,
create the missing `branch.pushed` event emission, and remove the legacy finalize lock
mechanism. The approach reuses existing projection and queue infrastructure, injecting them
into the cartridge via callbacks to maintain the `teleclaude_events/` → `teleclaude/`
dependency boundary.

## Phase 1: Event Infrastructure

### Task 1.1: Register `branch.pushed` event schema

**File(s):** `teleclaude_events/schemas/software_development.py`

- [x] Add `domain.software-development.branch.pushed` EventSchema to the integration
      lifecycle section (between `review.approved` and `deployment.started`)
- [x] Idempotency fields: `["branch", "sha", "remote"]`
- [x] Level: `EventLevel.WORKFLOW`, domain: `"software-development"`
- [x] Lifecycle: `NotificationLifecycle(creates=True, group_key="branch", meaningful_fields=["pushed_at"])`

### Task 1.2: Create `emit_branch_pushed()` helper

**File(s):** `teleclaude/core/integration_bridge.py`

- [x] Define `async def emit_branch_pushed(branch, sha, remote, *, pushed_at=None, pusher="")`
- [x] Follow existing `emit_review_approved` / `emit_deployment_started` pattern
- [x] Emit `domain.software-development.branch.pushed` with payload:
      `{branch, sha, remote, pushed_at, pusher}`
- [x] Source: `"finalizer/{TELECLAUDE_SESSION_ID}"`

### Task 1.3: Wire `emit_branch_pushed()` and `emit_deployment_started()` into the orchestrator dispatch

**File(s):** `teleclaude/core/next_machine/core.py` (finalize dispatch path)

**Design deviation from original spec:** Events are emitted at orchestrator dispatch time
(before the finalize worker starts), not inside the finalize worker after git push. This
approach seeds the projection immediately when the orchestrator decides to dispatch, so
the integrator can be spawned as soon as all 3 preconditions are observed. The finalize
worker's actual git push is not directly wired to an event emission.

- [x] Emit `review.approved` at dispatch time with `reviewer_session_id=TELECLAUDE_SESSION_ID`
- [x] Emit `branch.pushed` at dispatch time using the worktree HEAD SHA; remote defaults
      to `"origin"`
- [x] Emit `deployment.started` (maps to `finalize_ready`) with `worker_session_id` and
      `orchestrator_session_id` set to `TELECLAUDE_SESSION_ID`

---

## Phase 2: Cartridge Wiring

### Task 2.1: Add ingestion callback to IntegrationTriggerCartridge

**File(s):** `teleclaude_events/cartridges/integration_trigger.py`

- [x] Define callback type for ingestion:
      takes `(canonical_event_type: str, payload: Mapping)` →
      returns `Sequence[tuple[str, str, str]]` (list of `(slug, branch, sha)` ready candidates)
- [x] Add `ingest_callback` parameter to `__init__` (optional, like `spawn_callback`)
- [x] Add `"domain.software-development.branch.pushed"` to `INTEGRATION_EVENT_TYPES` set
- [x] Define event type mapping dict (platform → canonical):
  - `"domain.software-development.review.approved"` → `"review_approved"`
  - `"domain.software-development.branch.pushed"` → `"branch_pushed"`
  - `"domain.software-development.deployment.started"` → `"finalize_ready"`

### Task 2.2: Modify cartridge `process()` to use projection

**File(s):** `teleclaude_events/cartridges/integration_trigger.py`

- [x] For all events in `INTEGRATION_EVENT_TYPES` with a mapped canonical type:
      extract payload, call `ingest_callback(canonical_type, payload)`
- [x] If ingest returns ready candidates: call `spawn_callback` for the first ready
      candidate (singleton integrator pattern)
- [x] Remove the old `deployment.started`-only trigger logic
- [x] Events always pass through (return event — no pipeline termination)
- [x] Guard: if `ingest_callback` is None, skip ingestion (backward compat for tests)

### Task 2.3: Wire cartridge in daemon

**File(s):** `teleclaude/daemon.py`

- [x] Create ingest callback closure that wraps:
  1. `IntegrationEventService.ingest(event_type, payload)` — feed to projection
  2. Check `result.transitioned_to_ready` for READY candidates
  3. For each ready candidate: `IntegrationQueue.enqueue(key=candidate.key, ready_at=candidate.ready_at)`
  4. Return list of `(slug, branch, sha)` tuples for ready candidates
- [x] Pass ingest callback to `IntegrationTriggerCartridge` constructor alongside
      existing `spawn_callback`

---

## Phase 3: Legacy Removal

### Task 3.1: Remove finalize lock functions

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Remove constants: `_FINALIZE_LOCK_NAME`, `_FINALIZE_LOCK_STALE_MINUTES`
- [x] Remove `_finalize_lock_path()` helper
- [x] Remove `acquire_finalize_lock()` function (~line 2165)
- [x] Remove `release_finalize_lock()` function (~line 2221)
- [x] Remove `get_finalize_lock_holder()` function (~line 2242)
- [x] Remove lock acquisition in step 9 (finalize dispatch, ~line 3092)
- [x] Remove lock release on `compose_agent_guidance` failure (~line 3099)
- [x] Remove lock re-entry check at `next_work()` entry (~lines 2674-2683)

### Task 3.2: Remove `caller_session_id` parameter

**File(s):** `teleclaude/core/next_machine/core.py`, `teleclaude/api/todo_routes.py`

- [x] Remove `caller_session_id` parameter from `next_work()` signature (~line 2647)
- [x] Remove all conditional logic that depended on `caller_session_id`
- [x] Remove `caller_session_id` check in finalize dispatch guard (~line 3079-3090)
- [x] Update `/todos/work` API route to not pass `identity.session_id` to `next_work()`

### Task 3.3: Rewrite POST_COMPLETION["next-finalize"]

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Remove step 3-4 (lock ownership verification)
- [x] Remove step 6 (`telec todo integrate {args}`)
- [x] Remove step 7 (`rm -f todos/.finalize-lock`)
- [x] Keep: read worker output, confirm FINALIZE_READY, end worker session, call `{next_call}`
- [x] The integrator is now triggered by the event chain, not the orchestrator

### Task 3.4: Remove lock from session cleanup

**File(s):** `teleclaude/core/session_cleanup.py`

- [x] Remove `from teleclaude.core.next_machine.core import release_finalize_lock`
- [x] Remove `release_finalize_lock(project_path, session_id)` call from
      `cleanup_session_resources()` (~line 66-68)

---

## Phase 4: Validation

### Task 4.1: Add cartridge wiring tests

- [x] Test: cartridge feeds `review.approved` event to ingest callback with correct
      canonical type and payload
- [x] Test: cartridge feeds `branch.pushed` event to ingest callback
- [x] Test: cartridge feeds `deployment.started` event to ingest callback
- [x] Test: spawn callback only called when ingest returns non-empty ready candidates
- [x] Test: spawn callback NOT called when ingest returns empty (not yet READY)
- [x] Test: non-integration events pass through unchanged (no ingest/spawn call)

### Task 4.2: Test `emit_branch_pushed`

- [x] Test: `emit_branch_pushed()` produces correct EventEnvelope with expected payload
- [x] Test: payload contains `branch`, `sha`, `remote`, `pushed_at`, `pusher`

### Task 4.3: Update existing tests

- [x] Update tests that pass `caller_session_id` to `next_work()` calls
- [x] Remove tests for `acquire_finalize_lock`, `release_finalize_lock`,
      `get_finalize_lock_holder`
- [x] Update `test_integrator_wiring.py` to verify new three-event trigger behavior
- [x] Update mocks that patch `release_finalize_lock` in test suites

### Task 4.4: Quality checks

- [x] Run `make test`
- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
