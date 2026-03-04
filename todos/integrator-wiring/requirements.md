# Requirements: integrator-wiring

## Goal

Wire the existing integration module into production so the event-driven
singleton integrator becomes the only path that merges and pushes canonical
`main`. Relocate orchestrators from the project root into their worktrees.
Use the event platform's (`teleclaude_events`) Redis Streams pipeline as the
event bus. Eliminate the inline twelve-step POST_COMPLETION merge, the
bidirectional worktree file sync, the file-based finalize lock, and the
cross-slug orchestrator loop.

## Why

The integration module was delivered across five rollout slices but never
connected to production. The orchestrator still merges and pushes main inline,
causing chronic state.yaml drift, split file ownership between worktrees and
main, fragile multi-step sequences that leave main in partial state on
failure, and implicit serialization through a file-based lock.

## In Scope

1. Integration event schemas registered in the `EventCatalog` via `EventSchema`,
   aligned to the `domain.software-development.*` taxonomy.
2. Event emission from the orchestration lifecycle via `emit_event()` /
   `EventProducer` at review-approved, finalize-ready, and branch-pushed
   transitions.
3. Integration trigger cartridge — a pipeline cartridge that feeds integration
   events to the readiness projection and spawns/wakes the singleton integrator
   when a candidate goes READY.
4. Replacement of the `/next-finalize` POST_COMPLETION inline merge/push/cleanup
   with event emission and stop.
5. Integrator session that acquires the lease, drains the queue, merges from
   clean canonical refs, pushes main, does delivery bookkeeping and cleanup.
6. Notification lifecycle for integration events — the notification projector
   cartridge creates/resolves notifications so admins see delivery success and
   integration-blocked alerts on all surfaces (TUI, Telegram, web).
7. Cutover activation: `IntegratorCutoverControls(enabled=True,
   parity_evidence_accepted=True)`.
8. Replacement of the file-based `IntegrationEventStore` with pipeline
   cartridge consumption.
9. Removal of bidirectional `sync_slug_todo_from_worktree_to_main` /
   `sync_slug_todo_from_main_to_worktree` functions.
10. Orchestrator worktree relocation — per-slug orchestrators dispatched into
    worktrees via `subfolder=trees/{slug}`.
11. Removal of finalize lock (`acquire_finalize_lock`, `release_finalize_lock`,
    `get_finalize_lock_holder`) and cross-slug orchestrator loop.

## Out of Scope

1. Changes to the integration module's readiness projection, queue, lease, or
   runtime internals — these are delivered and tested. Only the event _source_
   changes (pipeline cartridge instead of file store).
2. Worker worktree behavior — workers keep operating in worktrees on feature
   branches as they do today.
3. Changes to the prepare/gate/review pipeline — only the finalize-and-merge
   path and orchestrator dispatch model change.
4. Event-driven orchestrator spawning — deferred to domain infrastructure
   phases. Humans continue to kick off `/next-work {slug}`.
5. The event platform itself — `teleclaude_events` is already on main.

## Functional Requirements

### FR1: Integration Event Schemas

1. The following `EventSchema` entries MUST be registered in the `EventCatalog`
   (via `build_default_catalog()` or a dedicated registration module):
   - `domain.software-development.review.approved` — review passed, candidate
     eligible for finalization.
   - `domain.software-development.deployment.started` — finalize ready, candidate
     queued for integration.
   - `domain.software-development.branch.pushed` — feature branch pushed to
     remote, confirming reachability for merge.
   - `domain.software-development.deployment.completed` — integrated to main,
     delivery bookkeeping done.
   - `domain.software-development.deployment.failed` — integration blocked,
     needs attention.
2. Each `EventSchema` MUST define `idempotency_fields`, `lifecycle`
   (`NotificationLifecycle`), and `default_level` per the event platform
   contract.
3. The deployment lifecycle MUST declare a `NotificationLifecycle`:
   - `deployment.started` → `creates=True`, `group_key="slug"`
   - `deployment.completed` → `resolves=True`, `group_key="slug"`
   - `deployment.failed` → `updates=True`, `meaningful_fields=["blocked_at"]`,
     `group_key="slug"`

### FR2: Event Emission

1. When review is approved (`mark-phase review approved`), the orchestration
   flow MUST emit `domain.software-development.review.approved` via
   `emit_event()`.
2. When a finalizer reports `FINALIZE_READY`, the orchestration flow MUST emit
   `domain.software-development.deployment.started` with `(slug, branch, sha)`.
3. When the worker pushes the feature branch to remote, the flow MUST emit
   `domain.software-development.branch.pushed` as a **separate event** with
   `(branch, sha, remote, pushed_at)`. The readiness projection requires
   three distinct events (`review_approved`, `finalize_ready`, `branch_pushed`)
   to transition a candidate to READY — folding `branch_pushed` into another
   event's payload would break the predicate without modifying internals.
4. Events MUST flow through the event platform's Redis Stream
   (`teleclaude:events`).

### FR3: Integrator Trigger

1. An integration trigger cartridge MUST be registered in the pipeline runtime's
   cartridge chain. When the cartridge sees `review.approved`,
   `deployment.started`, or `branch.pushed` events, it MUST translate them to
   `IntegrationEvent` instances and feed them to the readiness projection.
2. When the readiness projection transitions a candidate to READY, the
   cartridge (or its callback) MUST spawn (or wake) a singleton integrator
   session via the daemon.
3. Only one integrator session may be active at a time (enforced by the
   existing lease mechanism).
4. If an integrator is already running, the new READY candidate MUST be queued
   (the existing queue handles this).

### FR4: POST_COMPLETION Replacement

1. The `/next-finalize` POST_COMPLETION MUST stop after confirming
   `FINALIZE_READY` and emitting `deployment.started`.
2. The orchestrator MUST NOT merge, push, or clean up canonical main.
3. The orchestrator MUST NOT do delivery bookkeeping (roadmap deliver, demo
   snapshot) — the integrator handles this.
4. The orchestrator MUST NOT acquire, release, or check the finalize lock.
   The lock is removed entirely — the integrator's lease is the serialization
   mechanism.

### FR5: Integrator Session Contract

1. The integrator session MUST acquire the integration lease before processing.
2. The integrator MUST drain the queue in FIFO order by `ready_at`.
3. For each candidate: merge `origin/<branch>` into clean `origin/main`,
   run delivery bookkeeping, demo snapshot, cleanup (worktree remove, branch
   delete, todo removal), push main.
4. On successful integration: emit
   `domain.software-development.deployment.completed`.
5. If merge fails: emit `domain.software-development.deployment.failed` with
   evidence, create follow-up todo (existing blocked_followup module).
6. When queue is empty: release lease, write checkpoint, self-end.

### FR6: Cutover Activation

1. The cutover controls MUST be set to `enabled=True` with
   `parity_evidence_accepted=True`.
2. The shell wrappers (git, gh, pre-push) MUST enforce the integrator-only
   main push policy by default.

### FR7: Replace File-Based Event Store

1. The `IntegrationEventStore` (file-based append-only log) MUST be replaced
   by pipeline cartridge consumption.
2. The readiness projection MUST be fed from the integration trigger cartridge,
   not from file replay.
3. The file-based event log file is no longer written or read.

### FR8: Eliminate Bidirectional Sync

1. `sync_slug_todo_from_worktree_to_main` and
   `sync_slug_todo_from_main_to_worktree` MUST be removed.
2. All call sites of these functions MUST be removed.
3. The integrator merges the full branch (which includes worktree changes to
   todo artifacts) — no manual file copying needed.

### FR9: Orchestrator Worktree Relocation

1. Each orchestrator session MUST be dispatched into its worktree using the
   existing `subfolder=trees/{slug}` mechanism. The `project` parameter
   remains the canonical project root.
2. The state machine MUST operate on a single assigned slug — no cross-slug
   iteration.
3. When the slug lifecycle completes (FINALIZE_READY emitted or error), the
   state machine returns COMPLETE and the orchestrator session ends.
4. The state machine MUST derive the project root from session context for
   operations that need it (roadmap reads, daemon API calls).

### FR10: Dead Code Removal

1. `acquire_finalize_lock`, `release_finalize_lock`, `get_finalize_lock_holder`
   MUST be removed from `next_machine/core.py`.
2. The `caller_session_id` parameter on `next_work()` (used only for lock
   release) MUST be removed.
3. Lock acquisition logic in the finalize dispatch path MUST be removed.
4. Lock release logic at the start of `next_work()` MUST be removed.
5. The cross-slug iteration loop in `next_work()` MUST be replaced with a
   single-slug lifecycle.

## Verification Requirements

1. End-to-end test: review.approved + branch.pushed + deployment.started
   events → integrator spawns → merges → pushes main →
   deployment.completed emitted → cleanup done.
2. Test: deployment.failed event emitted on merge conflict → follow-up todo
   created → admin notification visible.
3. Test: non-integrator push to main is blocked when cutover is enabled.
4. Test: multiple READY candidates are processed FIFO.
5. Test: integrator self-ends when queue is empty.
6. Test: notification lifecycle — deployment.started creates notification,
   deployment.completed resolves it.
7. Regression: existing build/review/fix-review worker flows are unaffected.
8. Test: orchestrator session starts in worktree, operates on single slug,
   does not iterate cross-slug.
9. Test: finalize lock functions are absent from codebase.
10. Test: bidirectional sync functions are absent from codebase.

## Dependencies

- `teleclaude_events` package — already on main. Provides `EventCatalog`,
  `EventSchema`, `Pipeline`, `Cartridge`, `EventProducer`, `emit_event()`,
  `EventProcessor`, notification projector.

## Risks

1. Transition period: in-flight deliveries started under the old paradigm must
   complete before cutover. Migration path needed for active worktrees.
2. Integrator session failure mid-merge could leave main dirty. The existing
   safety gates and lease TTL handle this, but integration test coverage is
   needed.
3. Pipeline runtime availability — if the pipeline is down, events queue in
   Redis Streams but the integrator won't trigger until it catches up.
4. Orchestrator relocation changes the `cwd` context for the state machine.
   Path resolution for roadmap/daemon operations must be verified against
   session context (`project_path` vs `resolve_working_dir`).

## Constraints

1. The integration module internals (readiness projection, queue, lease,
   runtime, authorization, blocked followup) MUST NOT be modified except for
   replacing the file-based event source with pipeline cartridge consumption.
2. The authoritative spec is `docs/project/spec/integration-orchestrator.md`.
3. Workers continue operating in worktrees on feature branches — no worker
   changes.
4. The event platform's contract (`EventProducer`/`emit_event()`, cartridge
   interface, `EventCatalog`/`EventSchema` registration) is the interface —
   no direct Redis Stream access outside `teleclaude_events`.
5. Main is read-only for all actors except the integrator. No orchestrator,
   worker, or daemon code may write to canonical main after this wiring.
6. The `project`/`subfolder` dispatch mechanism MUST NOT change — it is the
   existing infrastructure for worktree-based sessions.
