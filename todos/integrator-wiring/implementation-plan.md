# Implementation Plan: integrator-wiring

## Plan Objective

Connect the existing integration module to production via the event platform's
pipeline runtime. Replace the inline POST_COMPLETION merge/push with
event-driven integrator handoff. Relocate orchestrators into worktrees as
single-slug sessions. Remove dead code (finalize lock, bidirectional sync,
cross-slug loop, file-based event store). Activate the cutover.

## Phase 1: Integration Event Schemas

### Task 1.1: Register integration event schemas in the EventCatalog

**File(s):** `teleclaude_events/schemas/software_development.py`

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
- [ ] Add `domain.software-development.branch.pushed` EventSchema:
      default_level=WORKFLOW, domain="software-development",
      idempotency_fields=["branch", "sha", "remote"],
      lifecycle=None (informational — the readiness projection consumes it but
      it has no notification lifecycle of its own)
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
- [ ] Register all five in `build_default_catalog()` or a dedicated
      `register_integration_schemas(catalog)` function

## Phase 2: Event Emission Bridge

### Task 2.1: Create integration event bridge

**File(s):** `teleclaude/core/integration_bridge.py` (new)

- [ ] Create bridge module that imports `emit_event` from `teleclaude_events`
- [ ] `emit_review_approved(slug, reviewer_session_id, review_round)`
      → emits `domain.software-development.review.approved`
- [ ] `emit_branch_pushed(branch, sha, remote, pushed_at)`
      → emits `domain.software-development.branch.pushed`
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

### Task 2.4: Wire emission into branch push

**File(s):** `teleclaude/core/next_machine/core.py` or worker push path

- [ ] When the worker pushes the feature branch to remote, call
      `emit_branch_pushed()` with branch, sha, remote, timestamp
- [ ] Identify the exact push site in the build or finalize worker flow

## Phase 3: Integration Trigger and Integrator Session

### Task 3.1: Create integration trigger cartridge

**File(s):** `teleclaude_events/cartridges/integration_trigger.py` (new)

- [ ] Implement `IntegrationTriggerCartridge` following the cartridge interface:
      ```python
      async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None
      ```
- [ ] Match event types and translate to `IntegrationEvent` instances:
      - `domain.software-development.review.approved`
        → `IntegrationEvent(event_type="review_approved", ...)`
      - `domain.software-development.deployment.started`
        → `IntegrationEvent(event_type="finalize_ready", ...)`
      - `domain.software-development.branch.pushed`
        → `IntegrationEvent(event_type="branch_pushed", ...)`
- [ ] Feed translated events to the `ReadinessProjection` (maintained as
      cartridge state or via `PipelineContext`)
- [ ] When `ReadinessProjection.apply()` returns a newly-READY candidate,
      trigger integrator spawn via a daemon callback on `PipelineContext`
- [ ] Non-matching events: pass through unchanged (return the event)

### Task 3.2: Register cartridge in daemon startup

**File(s):** `teleclaude/daemon.py`

- [ ] Add `IntegrationTriggerCartridge` to the pipeline chain (~line 1722,
      after dedup, before or alongside the notification projector)
- [ ] The cartridge needs access to: `ReadinessProjection` instance, daemon
      session spawn callback
- [ ] On daemon startup, the projection starts empty — events in the Redis
      Stream history rebuild state as the processor catches up

### Task 3.3: Integrator session spawn

**File(s):** `teleclaude/core/integration_bridge.py`

- [ ] `spawn_integrator_session(slug, branch, sha)` callable from the trigger
      cartridge's daemon callback
- [ ] Check if an integrator session is already running (query active sessions
      with integrator role prefix)
- [ ] If no integrator running: spawn via session start with integrator
      command, project path, and READY candidate info
- [ ] If integrator already running: do nothing — candidate is queued, the
      running integrator will drain it

### Task 3.4: Define the integrator session command

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
      2. End worker session
      3. Emit `deployment.started` event (via bridge)
      4. Report: "Candidate queued for integration. Integrator will process."
      5. Return COMPLETE for this slug's lifecycle
- [ ] Remove the entire inline merge/push/cleanup sequence (old steps 6-11:
      safety re-check, merge, bookkeeping, demo snapshot, cleanup, push, restart)
- [ ] No lock acquisition, no lock release, no lock verification

## Phase 5: Orchestrator Worktree Relocation

### Task 5.1: Single-slug state machine entry

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] `next_work(slug)` — slug is now required, not optional
- [ ] Remove the `caller_session_id` parameter (was for lock release only)
- [ ] Remove the cross-slug iteration loop — the state machine processes one
      slug through its lifecycle (prepare → build → review → fix → finalize)
      and returns COMPLETE when done
- [ ] Derive project root from session context for operations that need it
      (roadmap reads, daemon API calls) — the session stores `project_path`
      alongside `subdir`

### Task 5.2: Update orchestrator dispatch format

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Update `format_tool_call()` for orchestrator dispatch to use
      `subfolder=trees/{slug}` — the orchestrator lands in the worktree
- [ ] The `project` parameter remains the canonical project root
- [ ] Verify path resolution: the state machine `cwd` is now the worktree
      path, so existing `worktree_cwd` construction may simplify or be
      removed where the orchestrator already operates from the worktree

### Task 5.3: Update `/next-work` command handler

**File(s):** relevant command handler / command artifact

- [ ] The command now requires a slug argument (no more "pick next ready item")
- [ ] Dispatch instructions reference the worktree as the operating directory
- [ ] No cross-slug awareness in the command output

## Phase 6: Dead Code Removal and Cutover

### Task 6.1: Remove finalize lock

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Remove `acquire_finalize_lock` function (~line 2164)
- [ ] Remove `release_finalize_lock` function
- [ ] Remove `get_finalize_lock_holder` function (~line 2257)
- [ ] Remove lock release logic at start of `next_work()` (~line 2765-2776)
- [ ] Remove lock acquisition in finalize dispatch path (~line 3158-3199)
- [ ] Remove all call sites and references to these functions

### Task 6.2: Remove bidirectional sync

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Remove `sync_slug_todo_from_worktree_to_main` (~line 1986)
- [ ] Remove `sync_slug_todo_from_main_to_worktree` (~line 2005)
- [ ] Remove all call sites (~line 2945)

### Task 6.3: Replace file-based event store

**File(s):** `teleclaude/core/integration/service.py`,
`teleclaude/core/integration/event_store.py`

- [ ] Decouple `IntegrationEventService` from `IntegrationEventStore`
- [ ] The readiness projection is fed from the integration trigger cartridge
      (Task 3.1), not from file replay
- [ ] Remove or deprecate `IntegrationEventStore` and its file I/O

### Task 6.4: Activate cutover controls

**File(s):** environment configuration, agent session setup

- [ ] Set `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED=1` in daemon and agent
      session environments
- [ ] Set `TELECLAUDE_INTEGRATOR_PARITY_EVIDENCE=accepted` in integrator
      session environment
- [ ] Verify shell wrappers (git, gh, pre-push) enforce the policy

### Task 6.5: Clean up phantom state

**File(s):** `todos/integration-events-model/` (empty directory)

- [ ] Remove the empty `todos/integration-events-model/` directory
- [ ] Verify no stale roadmap reference remains

## Phase 7: Validation

### Task 7.1: End-to-end integration test

**File(s):** `tests/integration/test_integrator_wiring.py` (new)

- [ ] Test: emit review.approved + branch.pushed + deployment.started →
      integrator spawns → acquires lease → merges → deployment.completed
      emitted → push → cleanup
- [ ] Test: second READY candidate while integrator running → queued,
      processed after first
- [ ] Test: merge conflict → deployment.failed emitted → follow-up todo
      created → admin notification visible
- [ ] Test: integrator self-ends when queue empty

### Task 7.2: Notification lifecycle test

**File(s):** `tests/integration/test_integrator_wiring.py`

- [ ] Test: deployment.started creates notification with in_progress status
- [ ] Test: deployment.completed resolves the notification
- [ ] Test: deployment.failed resets notification to unseen

### Task 7.3: Orchestrator relocation tests

**File(s):** `tests/integration/test_integrator_wiring.py`

- [ ] Test: orchestrator dispatched with subfolder=trees/{slug} starts in
      worktree
- [ ] Test: state machine operates on single slug, returns COMPLETE
- [ ] Test: no cross-slug iteration occurs

### Task 7.4: Dead code absence tests

**File(s):** `tests/integration/test_integrator_wiring.py`

- [ ] Test: `acquire_finalize_lock` absent from codebase
- [ ] Test: `release_finalize_lock` absent from codebase
- [ ] Test: `sync_slug_todo_from_worktree_to_main` absent from codebase
- [ ] Test: `sync_slug_todo_from_main_to_worktree` absent from codebase

### Task 7.5: Regression tests

**File(s):** existing test suites

- [ ] Verify build/review/fix-review worker flows are unaffected
- [ ] Verify feature-branch pushes still allowed
- [ ] Verify non-integrator main push is blocked
- [ ] Run `make test` and `make lint`

### Task 7.6: Review readiness

- [ ] Confirm all FRs from requirements.md are reflected in code changes
- [ ] Confirm POST_COMPLETION no longer touches canonical main
- [ ] Confirm integrator is the only path that pushes main
- [ ] Confirm orchestrators start in worktrees (single-slug, no cross-slug)
- [ ] Confirm finalize lock, bidirectional sync, cross-slug loop are gone
- [ ] Confirm notification lifecycle works end-to-end
- [ ] Confirm file-based event store is decoupled
- [ ] Document any deferrals in `deferrals.md` if applicable
