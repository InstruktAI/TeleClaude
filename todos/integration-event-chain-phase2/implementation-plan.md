# Implementation Plan: integration-event-chain-phase2

## Overview

The recovered finalize handoff stays as-is. The remaining work is split into two
coherent slices:
1. finish the three-event readiness gate with `branch.pushed`
2. align integrator delivery bookkeeping and cleanup with worker role boundaries

The approach reuses existing projection, queue, and checkpoint infrastructure.
No new orchestration model is introduced.

## Phase 1: Three-Event Gate

### Task 1.1: Register `branch.pushed` event schema

**File(s):** `teleclaude_events/schemas/software_development.py`

- [ ] Add `domain.software-development.branch.pushed` EventSchema to the integration
      lifecycle section (between `review.approved` and `deployment.started`)
- [ ] Idempotency fields: `["branch", "sha", "remote"]`
- [ ] Level: `EventLevel.WORKFLOW`, domain: `"software-development"`
- [ ] Lifecycle: `NotificationLifecycle(creates=True, group_key="branch", meaningful_fields=["pushed_at"])`

### Task 1.2: Create `emit_branch_pushed()` helper

**File(s):** `teleclaude/core/integration_bridge.py`

- [ ] Define `async def emit_branch_pushed(branch, sha, remote, *, pushed_at=None, pusher="")`
- [ ] Follow existing `emit_review_approved` / `emit_deployment_started` pattern
- [ ] Emit `domain.software-development.branch.pushed` with payload:
      `{branch, sha, remote, pushed_at, pusher}`
- [ ] Source: `"finalizer/{TELECLAUDE_SESSION_ID}"`

### Task 1.3: Wire `emit_branch_pushed()` into the finalize worker

**File(s):** `teleclaude/core/next_machine/core.py` (POST_COMPLETION instructions for
`next-finalize`)

- [ ] Add instruction step after git push success: call `emit_branch_pushed(branch, sha, remote)`
- [ ] The finalize worker already knows branch and sha from its context; remote defaults
      to `"origin"`

---

## Phase 2: Cartridge Wiring

### Task 2.1: Add ingestion callback to IntegrationTriggerCartridge

**File(s):** `teleclaude_events/cartridges/integration_trigger.py`

- [ ] Define callback type for ingestion:
      takes `(canonical_event_type: str, payload: Mapping)` →
      returns `Sequence[tuple[str, str, str]]` (list of `(slug, branch, sha)` ready candidates)
- [ ] Add `ingest_callback` parameter to `__init__` (optional, like `spawn_callback`)
- [ ] Add `"domain.software-development.branch.pushed"` to `INTEGRATION_EVENT_TYPES` set
- [ ] Define event type mapping dict (platform → canonical):
  - `"domain.software-development.review.approved"` → `"review_approved"`
  - `"domain.software-development.branch.pushed"` → `"branch_pushed"`
  - `"domain.software-development.deployment.started"` → `"finalize_ready"`

### Task 2.2: Modify cartridge `process()` to use projection

**File(s):** `teleclaude_events/cartridges/integration_trigger.py`

- [ ] For all events in `INTEGRATION_EVENT_TYPES` with a mapped canonical type:
      extract payload, call `ingest_callback(canonical_type, payload)`
- [ ] If ingest returns ready candidates: call `spawn_callback` for the first ready
      candidate (singleton integrator pattern)
- [ ] Remove the old `deployment.started`-only trigger logic
- [ ] Events always pass through (return event — no pipeline termination)
- [ ] Guard: if `ingest_callback` is None, skip ingestion (backward compat for tests)

### Task 2.3: Wire cartridge in daemon

**File(s):** `teleclaude/daemon.py`

- [ ] Create ingest callback closure that wraps:
  1. `IntegrationEventService.ingest(event_type, payload)` — feed to projection
  2. Check `result.transitioned_to_ready` for READY candidates
  3. For each ready candidate: `IntegrationQueue.enqueue(key=candidate.key, ready_at=candidate.ready_at)`
  4. Return list of `(slug, branch, sha)` tuples for ready candidates
- [ ] Pass ingest callback to `IntegrationTriggerCartridge` constructor alongside
      existing `spawn_callback`

---

## Phase 3: Integrator Ownership Alignment

### Task 3.1: Convert delivery bookkeeping to AI-directed instructions

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] Refactor `_step_committed()` so it no longer runs `telec roadmap deliver` directly
- [ ] Refactor `_step_committed()` so it no longer runs `telec todo demo create` directly
- [ ] Refactor `_step_committed()` so it no longer stages/commits delivery changes directly
- [ ] Return explicit integrator instructions instead:
      run delivery bookkeeping, stage/commit with the prescribed message, then call
      `telec todo integrate` again
- [ ] Preserve checkpoint semantics so re-entry can detect when the agent has completed
      the requested bookkeeping step

### Task 3.2: Convert cleanup to AI-directed instructions

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] Refactor `_do_cleanup()` so it no longer directly removes the worktree, branches,
      todo directory, stages cleanup, commits cleanup, or restarts the daemon
- [ ] Return explicit integrator instructions for those operations instead
- [ ] Keep `queue.mark_integrated()` and checkpoint advancement deterministic; only advance
      once the integrator has completed the requested cleanup step
- [ ] Preserve idempotent re-entry when cleanup partially completed before retry

### Task 3.3: Remove stale direct-integrate assumptions

**File(s):** tests, wrappers, and any user-facing guidance that still references the old path

- [ ] Update tests that currently expect orchestrator-owned `telec todo integrate` handoff
- [ ] Update wrapper/help text so `FINALIZE_READY` points to integrator handoff, not
      `finalize-apply`
- [ ] Verify no user-facing text implies that non-integrator sessions call
      `telec todo integrate`

---

## Phase 4: Validation

### Task 4.1: Add cartridge wiring tests

- [ ] Test: cartridge feeds `review.approved` event to ingest callback with correct
      canonical type and payload
- [ ] Test: cartridge feeds `branch.pushed` event to ingest callback
- [ ] Test: cartridge feeds `deployment.started` event to ingest callback
- [ ] Test: spawn callback only called when ingest returns non-empty ready candidates
- [ ] Test: spawn callback NOT called when ingest returns empty (not yet READY)
- [ ] Test: non-integration events pass through unchanged (no ingest/spawn call)

### Task 4.2: Test `emit_branch_pushed`

- [ ] Test: `emit_branch_pushed()` produces correct EventEnvelope with expected payload
- [ ] Test: payload contains `branch`, `sha`, `remote`, `pushed_at`, `pusher`

### Task 4.3: Update existing tests

- [ ] Update `test_integrator_wiring.py` to verify new three-event trigger behavior
- [ ] Add tests for the AI-directed delivery-bookkeeping checkpoint transition
- [ ] Add tests for the AI-directed cleanup checkpoint transition
- [ ] Update any stale assertions that still encode orchestrator-owned integration

### Task 4.4: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
