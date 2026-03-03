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

## The problems it solves

The current flow has chronic issues:

1. **Bidirectional file sync** — `sync_slug_todo_from_worktree_to_main` and
   `sync_slug_todo_from_main_to_worktree` copy state.yaml and planning artifacts
   between main and worktrees. Ownership is split: main seeds state.yaml, worktree
   owns build/review progress, then it gets copied back. Any misstep causes drift.

2. **Inline twelve-step finalize** — The orchestrator does fetch, switch, pull,
   merge, delivery bookkeeping commit, demo snapshot commit, worktree remove,
   branch delete, todo cleanup commit, push, restart — all inline on canonical
   main. Any failure mid-sequence leaves main in partial state.

3. **No serialization** — Parallel deliveries can race on main. The finalize
   lock (`acquire_finalize_lock`, file-based with 30-minute stale timeout) was
   a band-aid — fragile and redundant once the integrator's lease exists.

4. **Orchestrator on main** — The orchestrator runs from the project root and
   reaches into worktrees. It owns the cross-slug iteration loop, picking ready
   items and dispatching workers. This prevents parallelism and couples unrelated
   slugs into a single session.

## Architectural decisions

These decisions emerged during preparation brainstorming and supersede the
original plan:

1. **Main is sacred.** Only the integrator touches canonical main. Orchestrators,
   workers, and the daemon are read-only on main after this wiring. The
   integrator's lease (compare-and-swap with 120s TTL, 30s renewal) provides
   atomic serialization — no file-based finalize lock needed.

2. **One orchestrator per todo.** No main orchestrator loop. Each slug gets its
   own orchestrator session, born in its worktree (`subfolder=trees/{slug}`),
   dies in its worktree. No cross-slug awareness. The existing
   `project`/`subfolder` dispatch mechanism handles this without format changes.

3. **Three-actor architecture.** Daemon (nervous system, event routing, pipeline)
   → Per-slug orchestrators (hands, in worktrees) → Integrator (sole gatekeeper
   of main).

4. **SDLC lifecycle is core.** The state machine and orchestration are core daemon
   functionality — too tightly coupled to be a pluggable cartridge.

5. **Event-driven spawning deferred.** Until domain infrastructure arrives
   (event-platform phases 3+7), humans kick off `/next-work {slug}`. The
   pipeline triggers the integrator automatically when candidates reach READY;
   automatic orchestrator spawning comes later.

6. **Dead code removal.** Finalize lock (acquire/release/get_holder),
   bidirectional sync functions, cross-slug iteration loop, and file-based
   event store are all removed. The integrator's lease, branch merge, and
   pipeline consumption replace them respectively.

## What exists (the integration library)

- **Event types** — `review_approved`, `finalize_ready`, `branch_pushed`,
  `integration_blocked` with full payload contracts (`events.py`)
- **Readiness projection** — tracks candidate `(slug, branch, sha)` readiness
  from three distinct events (`review_approved`, `finalize_ready`, `branch_pushed`),
  including reachability and integrated checks (`readiness_projection.py`)
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
  replaced by pipeline consumption

## What exists (the event platform)

`teleclaude_events` is on main with all needed interfaces:

- `EventCatalog`, `EventSchema`, `NotificationLifecycle` — event registration
- `Pipeline`, `PipelineContext`, `Cartridge` protocol — processing chain
- `EventProducer`, `emit_event()` — event emission to Redis Streams
- `EventProcessor` — Redis Stream consumer group loop
- Deduplication and notification projector cartridges — already in pipeline chain

Not blocked on event-platform container children (system cartridges, domain
infrastructure, signal pipeline, etc.). The base platform is sufficient.

## Authoritative spec

`docs/project/spec/integration-orchestrator.md` — defines events, readiness
predicate, lease semantics, queue semantics, lifecycle, and self-end authorization.
