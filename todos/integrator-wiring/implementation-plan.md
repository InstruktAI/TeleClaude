# Implementation Plan: integrator-wiring

## Plan Objective

Connect the existing integration module to the production orchestration flow
via the event platform's (`teleclaude_events`) pipeline runtime. Replace the
inline POST_COMPLETION merge/push with event-driven integrator handoff.
Activate the cutover.

Prerequisite: `event-platform-core` must be delivered first — it provides
`teleclaude_events` (envelope, catalog, producer, pipeline runtime, cartridge
interface, notification projector, SQLite state, API, push delivery).

## Phase 1: Integration Event Schemas

### Task 1.1: Register integration event schemas in the EventCatalog

**File(s):** `teleclaude_events/schemas/software_development.py` (extend
existing schema module from event-platform-core)

- [ ] Add `domain.software-development.review.approved` EventSchema:
      default_level=WORKFLOW, domain="software-development",
      idempotency_fields=["slug", "review_round"],
      lifecycle=NotificationLifecycle(creates=True, group_key="slug",
      meaningful_fields=["approved_at"])
- [ ] Add `domain.software-development.deployment.started` EventSchema:
      default_level=WORKFLOW, domain="software-development",
      idempotency_fields=["slug", "branch", "sha"],
      lifecycle=NotificationLifecycle(creates=True, group_key="slug",
      meaningful_fields=["ready_at"])
- [ ] Add `domain.software-development.deployment.completed` EventSchema:
      default_level=WORKFLOW, domain="software-development",
      idempotency_fields=["slug", "merge_commit"],
      lifecycle=NotificationLifecycle(resolves=True, group_key="slug",
      meaningful_fields=["integrated_at"])
- [ ] Add `domain.software-development.deployment.failed` EventSchema:
      default_level=BUSINESS, domain="software-development", actionable=True,
      idempotency_fields=["slug", "branch", "sha", "blocked_at"],
      lifecycle=NotificationLifecycle(updates=True, group_key="slug",
      meaningful_fields=["blocked_at"])
- [ ] Register all four in `build_default_catalog()` or a dedicated
      `register_integration_schemas(catalog)` function

## Phase 2: Event Emission from Orchestration Lifecycle

### Task 2.1: Create integration event bridge

**File(s):** `teleclaude/core/integration_bridge.py` (new)

- [ ] Create bridge module that imports `emit_event` (or `EventProducer`)
      from `teleclaude_events`
- [ ] `emit_review_approved(slug, reviewer_session_id, review_round)`
      → emits `domain.software-development.review.approved`
- [ ] `emit_deployment_started(slug, branch, sha, worker_session_id, orchestrator_session_id)`
      → emits `domain.software-development.deployment.started`
- [ ] `emit_deployment_completed(slug, branch, sha, merge_commit)`
      → emits `domain.software-development.deployment.completed`
- [ ] `emit_deployment_failed(slug, branch, sha, conflict_evidence, diagnostics, next_action)`
      → emits `domain.software-development.deployment.failed`
- [ ] Each function constructs an `EventEnvelope` and calls `emit_event()`

### Task 2.2: Wire emission into review-approved path

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] In the path where `mark-phase review approved` succeeds,
      call `emit_review_approved()` with slug, session ID, and review round
- [ ] This is in the `next-review` POST_COMPLETION flow and in
      `_resolve_review_phase()`

### Task 2.3: Wire emission into finalize path

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] In the `/next-finalize` POST_COMPLETION, after confirming FINALIZE_READY:
      call `emit_deployment_started()` with slug, branch, sha, session IDs
- [ ] This replaces the inline merge/push — the orchestrator stops here

## Phase 3: Integrator Trigger

### Task 3.1: Create integration trigger cartridge

**File(s):** `teleclaude_events/cartridges/integration_trigger.py` (new)

- [ ] Implement `IntegrationTriggerCartridge` following the cartridge interface:
      ```python
      async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None
      ```
- [ ] The cartridge fires on `domain.software-development.review.approved`,
      `domain.software-development.deployment.started`, and branch_pushed events
- [ ] For matching events: extract (slug, branch, sha) and feed to the
      `ReadinessProjection` (maintained in daemon memory via `PipelineContext`)
- [ ] When `ReadinessProjection` returns a newly-READY candidate, trigger
      integrator spawn via a daemon callback on `PipelineContext`
- [ ] Non-matching events: pass through unchanged (return the event)
- [ ] Register the cartridge in the pipeline chain (after dedup, before or
      alongside the notification projector)

### Task 3.2: Integrator session spawn/wake

**File(s):** `teleclaude/core/integration_bridge.py`

- [ ] `spawn_integrator_session(slug, branch, sha)` function callable from
      the trigger cartridge's daemon callback
- [ ] Check if an integrator session is already running (query active sessions
      with integrator role prefix)
- [ ] If no integrator running: spawn via `telec sessions start` with
      integrator system role, project path, and the READY candidate info
- [ ] If integrator already running: do nothing — candidate is queued, the
      running integrator will drain it

### Task 3.3: Define the integrator session command

**File(s):** `agents/commands/next-integrate.md` (new)

- [ ] Create the command that the integrator session executes
- [ ] The command: acquire lease → drain queue → for each candidate:
      1. Merge `origin/<branch>` into clean `origin/main`
      2. If merge conflict: call `emit_deployment_failed()`, create follow-up
         todo (existing blocked_followup), mark queue item blocked, continue
      3. Run delivery bookkeeping (`telec roadmap deliver`, delivery commit)
      4. Demo snapshot (if demo.md exists)
      5. Cleanup (worktree remove, branch delete, todo removal, cleanup commit)
      6. Push main
      7. Call `emit_deployment_completed()`
      8. `make restart`
- [ ] When queue empty: release lease, write checkpoint, self-end
- [ ] Use `IntegratorShadowRuntime` with `shadow_mode=False` and
      `CanonicalMainPusher` callback that performs the git merge/push

## Phase 4: POST_COMPLETION Replacement

### Task 4.1: Truncate next-finalize POST_COMPLETION

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Replace the current 12-step POST_COMPLETION for `next-finalize` with:
      1. Read worker output, confirm FINALIZE_READY
      2. Verify finalize lock ownership
      3. End worker session
      4. Emit `deployment.started` event (via bridge)
      5. Release finalize lock
      6. Report: "Candidate queued for integration. Integrator will process."
      7. Call `{next_call}` (state machine continues)
- [ ] Remove steps 6-11 of the old flow (safety re-check, merge, bookkeeping,
      demo snapshot, cleanup, push, restart)
- [ ] The delivery bookkeeping, cleanup, and push now happen in the integrator
      session (Phase 3, Task 3.3)

## Phase 5: Cutover, Cleanup, and Sync Removal

### Task 5.1: Activate cutover controls

**File(s):** environment configuration, agent session setup

- [ ] Set `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED=1` in daemon and agent
      session environments
- [ ] Set `TELECLAUDE_INTEGRATOR_PARITY_EVIDENCE=accepted` in integrator
      session environment
- [ ] Verify shell wrappers (git, gh, pre-push) enforce the policy

### Task 5.2: Replace file-based event store with pipeline consumption

**File(s):** `teleclaude/core/integration/service.py`, `teleclaude/core/integration/event_store.py`

- [ ] The `IntegrationEventService` no longer reads from or writes to the
      file-based event log
- [ ] The readiness projection is fed from the integration trigger cartridge
      (Task 3.1), not from file replay
- [ ] The `IntegrationEventStore` class and its file I/O can be removed or
      stubbed — the Redis Stream (via pipeline runtime) is the event log
- [ ] On daemon startup, replay integration-relevant events from Redis Stream
      history to rebuild the readiness projection state

### Task 5.3: Remove bidirectional worktree sync

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Remove `sync_slug_todo_from_worktree_to_main` (line ~1986)
- [ ] Remove `sync_slug_todo_from_main_to_worktree` (line ~2005)
- [ ] Remove all call sites of these functions (line ~2945)
- [ ] The integrator merges the full branch — todo artifact changes in the
      worktree are included in the branch merge

### Task 5.4: Clean up phantom state

**File(s):** `todos/integration-events-model/` (empty directory)

- [ ] Remove the empty `todos/integration-events-model/` directory
- [ ] Verify no stale roadmap reference remains

## Phase 6: Validation

### Task 6.1: End-to-end integration test

**File(s):** `tests/integration/test_integrator_wiring.py` (new)

- [ ] Test: emit review.approved + deployment.started → integrator spawns →
      acquires lease → merges → deployment.completed emitted → push → cleanup
- [ ] Test: second READY candidate while integrator running → queued, processed
      after first
- [ ] Test: merge conflict → deployment.failed emitted → follow-up todo created
      → admin notification visible
- [ ] Test: integrator self-ends when queue empty

### Task 6.2: Notification lifecycle test

**File(s):** `tests/integration/test_integrator_wiring.py`

- [ ] Test: deployment.started creates notification with in_progress status
- [ ] Test: deployment.completed resolves the notification
- [ ] Test: deployment.failed resets notification to unseen

### Task 6.3: Regression tests

**File(s):** existing test suites

- [ ] Verify build/review/fix-review worker flows are unaffected
- [ ] Verify feature-branch pushes still allowed
- [ ] Verify non-integrator main push is blocked
- [ ] Run `make test` and `make lint`

## Phase 7: Review Readiness

- [ ] Confirm all FRs from requirements.md are reflected in code changes
- [ ] Confirm POST_COMPLETION no longer touches canonical main
- [ ] Confirm integrator is the only path that pushes main
- [ ] Confirm bidirectional sync functions are removed
- [ ] Confirm notification lifecycle works end-to-end
- [ ] Confirm file-based event store is removed
- [ ] Document any deferrals in `deferrals.md` if applicable
