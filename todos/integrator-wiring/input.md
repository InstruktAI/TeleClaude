# Input: integrator-wiring

## Context

The integration module (`teleclaude/core/integration/`) was delivered across five
rollout slices (integration-safety-gates, integration-events-model,
integrator-shadow-mode, integrator-cutover, integration-blocked-flow). All are
merged to main with full test coverage.

**The module is a fully tested library with zero production consumers.**

Nothing outside `teleclaude/core/integration/` imports from it. The old paradigm
still runs: the orchestrator's POST_COMPLETION for `/next-finalize`
(`next_machine/core.py:232-278`) does inline merge, push, cleanup — twelve steps
directly on canonical main.

## The problem it solves

The current flow has chronic issues:

1. **Bidirectional file sync** — `sync_slug_todo_from_worktree_to_main` and
   `sync_slug_todo_from_main_to_worktree` copy state.yaml and planning artifacts
   between main and worktrees. Ownership is split: main seeds state.yaml, worktree
   owns build/review progress, then it gets copied back. Any misstep causes drift.

2. **Inline twelve-step finalize** — The orchestrator does fetch, switch, pull,
   merge, delivery bookkeeping commit, demo snapshot commit, worktree remove,
   branch delete, todo cleanup commit, push, restart — all inline on canonical
   main. Any failure mid-sequence leaves main in partial state.

3. **No serialization** — Parallel deliveries can race on main. The orchestrator
   serializes implicitly by being single-threaded, but that's fragile.

## What exists (the library)

- **Event types** — `review_approved`, `finalize_ready`, `branch_pushed`,
  `integration_blocked` with full payload contracts (`events.py`)
- **Readiness projection** — tracks candidate `(slug, branch, sha)` readiness
  from events, including reachability and integrated checks (`readiness_projection.py`)
- **Queue** — durable FIFO queue for READY candidates (`queue.py`)
- **Lease** — singleton lease with TTL, renewal, stale-break (`lease.py`)
- **Runtime** — `IntegratorShadowRuntime` that drains queue under lease, with
  main-branch clearance probes, blocked outcome handling, follow-up linking,
  and `CanonicalMainPusher` callback for live mode (`runtime.py`)
- **Authorization** — `IntegratorCutoverControls`, `require_integrator_owner`,
  `resolve_cutover_mode` for controlled transition (`authorization.py`)
- **Blocked follow-up** — todo creation for blocked candidates with linkage
  and resume UX (`blocked_followup.py`)
- **Service** — `IntegrationEventService` that combines store + projection
  with ingest/replay API (`service.py`)
- **File-based event store** — append-only log (`event_store.py`) — to be
  superseded by the notification service's Redis Streams

## Dependency: event-platform

This todo depends on `event-platform` (the event processing platform).
Integration events flow through the notification service's Redis Streams pipeline
instead of the file-based event store. This gives us:

1. **Unified event bus** — integration events are event-platform events,
   not a separate event system. `NotificationProducer.emit()` replaces file appends.
2. **Admin notifications for free** — delivery to main and integration blocked
   are natural notification lifecycle events. Admins see them in TUI, Telegram,
   web — all surfaces that the notification service already delivers to.
3. **Event taxonomy alignment** — integration events map to the
   `domain.software-development.deployment.*` taxonomy:
   - `domain.software-development.review.approved` ← review_approved
   - `domain.software-development.deployment.started` ← finalize_ready
   - `domain.software-development.deployment.completed` ← integration succeeded
   - `domain.software-development.deployment.failed` ← integration_blocked
4. **Integrator trigger via processor callback** — when the notification
   processor sees integration-readiness events, it feeds them to the existing
   readiness projection and spawns the integrator when candidates go READY.
5. **File-based event store becomes redundant** — Redis Streams IS the event log.
   The readiness projection still runs (it's the integrator's brain) but consumes
   from the stream instead of from file replay.

## Authoritative spec

`docs/project/spec/integration-orchestrator.md` — defines events, readiness
predicate, lease semantics, queue semantics, lifecycle, and self-end authorization.
