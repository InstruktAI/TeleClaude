# Requirements: integrator-wiring

## Goal

Wire the existing integration module into the production orchestration flow so
the event-driven singleton integrator becomes the only path that merges and
pushes canonical `main`. Use the notification service's Redis Streams pipeline
as the event bus — integration events are event-platform events, not a
separate system. Eliminate the inline twelve-step POST_COMPLETION merge and
the bidirectional worktree file sync.

## Why

The integration module was delivered across five rollout slices but never
connected to production. The orchestrator still merges and pushes main inline,
causing chronic state.yaml drift, split file ownership between worktrees and
main, and fragile multi-step sequences that leave main in partial state on
failure.

## In Scope

1. Integration event schemas in the notification service event catalog, aligned
   to the `domain.software-development.*` taxonomy.
2. Event emission from the orchestration lifecycle via `NotificationProducer.emit()`
   at review-approved, finalize-ready, and branch-pushed transitions.
3. Integrator trigger via notification processor callback — when readiness
   projection sees a READY candidate, spawn/wake the singleton integrator session.
4. Replacement of the `/next-finalize` POST_COMPLETION inline merge/push/cleanup
   with a FINALIZE_READY handoff to the integrator.
5. Integrator session that acquires the lease, drains the queue, merges from
   clean canonical refs, pushes main, does delivery bookkeeping and cleanup.
6. Notification lifecycle for integration events — admins see delivery success
   and integration-blocked alerts on all surfaces (TUI, Telegram, web).
7. Cutover activation: `IntegratorCutoverControls(enabled=True,
parity_evidence_accepted=True)`.
8. Removal of the file-based `IntegrationEventStore` — Redis Streams replaces it.
9. Removal of bidirectional `sync_slug_todo_from_worktree_to_main` /
   `sync_slug_todo_from_main_to_worktree` functions once the integrator owns
   the main-touching lifecycle.

## Out of Scope

1. Changes to the integration module's readiness projection, queue, lease, or
   runtime internals — these are delivered and tested. Only the event _source_
   changes (Redis Streams instead of file store).
2. Worker worktree behavior — workers keep operating in worktrees on feature
   branches as they do today.
3. Changes to the prepare/gate/review pipeline — only the finalize-and-merge
   path changes.
4. The notification service itself — that is a separate prerequisite todo.

## Functional Requirements

### FR1: Integration Event Schemas

1. The following event schemas MUST be registered in the notification service
   event catalog:
   - `domain.software-development.review.approved` — review passed, candidate
     eligible for finalization.
   - `domain.software-development.deployment.started` — finalize ready, candidate
     queued for integration.
   - `domain.software-development.deployment.completed` — integrated to main,
     delivery bookkeeping done.
   - `domain.software-development.deployment.failed` — integration blocked,
     needs attention.
2. Each schema MUST define idempotency fields, notification lifecycle
   declarations, and event level per the notification service contract.
3. The deployment lifecycle MUST declare a notification lifecycle:
   - `deployment.started` → creates notification, `agent_status: in_progress`
   - `deployment.completed` → resolves notification, terminal
   - `deployment.failed` → resets to `unseen`, needs attention

### FR2: Event Emission

1. When review is approved (`mark-phase review approved`), the orchestration
   flow MUST emit `domain.software-development.review.approved` via
   `NotificationProducer.emit()`.
2. When a finalizer reports `FINALIZE_READY`, the orchestration flow MUST emit
   `domain.software-development.deployment.started` with `(slug, branch, sha)`.
3. When the worker pushes the feature branch to remote, the flow MUST emit
   the branch-pushed signal as part of the deployment.started payload.
4. Events MUST flow through the notification service Redis Stream.

### FR3: Integrator Trigger

1. When the notification processor sees deployment.started events, it MUST feed
   the event data to the integration readiness projection.
2. When the readiness projection transitions a candidate to READY, the daemon
   MUST spawn (or wake) a singleton integrator session.
3. Only one integrator session may be active at a time (enforced by the
   existing lease mechanism).
4. If an integrator is already running, the new READY candidate MUST be queued
   (the existing queue handles this).

### FR4: POST_COMPLETION Replacement

1. The `/next-finalize` POST_COMPLETION MUST stop after confirming
   `FINALIZE_READY` and emitting events.
2. The orchestrator MUST NOT merge, push, or clean up canonical main.
3. The orchestrator MUST NOT do delivery bookkeeping (roadmap deliver, demo
   snapshot) — the integrator handles this.
4. The orchestrator MAY still end the worker session and release the finalize
   lock.

### FR5: Integrator Session Contract

1. The integrator session MUST acquire the integration lease before processing.
2. The integrator MUST drain the queue in FIFO order by `ready_at`.
3. For each candidate: merge `origin/<branch>` into clean `origin/main`,
   run delivery bookkeeping, demo snapshot, cleanup (worktree remove, branch
   delete, todo removal), push main.
4. On successful integration: emit `domain.software-development.deployment.completed`.
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
   by Redis Streams consumption.
2. The readiness projection MUST be fed from the notification processor
   callback, not from file replay.
3. The file-based event log file is no longer written or read.

### FR8: Eliminate Bidirectional Sync

1. `sync_slug_todo_from_worktree_to_main` and `sync_slug_todo_from_main_to_worktree`
   MUST be removed or reduced to a no-op once the integrator owns the
   main-touching lifecycle.
2. The integrator merges the full branch (which includes worktree changes to
   todo artifacts) — no manual file copying needed.

## Verification Requirements

1. End-to-end test: review.approved + deployment.started events → integrator
   spawns → merges → pushes main → deployment.completed emitted → cleanup done.
2. Test: deployment.failed event emitted on merge conflict → follow-up todo
   created → admin notification visible.
3. Test: non-integrator push to main is blocked when cutover is enabled.
4. Test: multiple READY candidates are processed FIFO.
5. Test: integrator self-ends when queue is empty.
6. Test: notification lifecycle — deployment.started creates notification,
   deployment.completed resolves it.
7. Regression: existing build/review/fix-review worker flows are unaffected.

## Dependencies

- `event-platform` — provides the event bus (Redis Streams producer,
  processor, catalog, push delivery). MUST be delivered first.

## Risks

1. Transition period: in-flight deliveries started under the old paradigm must
   complete before cutover. Migration path needed for active worktrees.
2. Integrator session failure mid-merge could leave main dirty. The existing
   safety gates and lease TTL handle this, but integration test coverage is
   needed.
3. Notification processor availability — if the processor is down, events
   queue in Redis Streams but the integrator won't trigger until it catches up.

## Constraints

1. The integration module internals (readiness projection, queue, lease,
   runtime, authorization, blocked followup) MUST NOT be modified except for
   replacing the file-based event source with Redis Streams consumption.
2. The authoritative spec is `docs/project/spec/integration-orchestrator.md`.
3. Workers continue operating in worktrees on feature branches — no worker
   changes.
4. The notification service's contract (producer API, processor callback,
   catalog schema registration) is the interface — no direct Redis Stream
   access outside the notification package.
