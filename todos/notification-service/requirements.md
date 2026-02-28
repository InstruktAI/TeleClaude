# Requirements: notification-service

## Goal

Build an event-driven notification service as a separate package within the TeleClaude monorepo.
The service is the single source of truth for all autonomous platform events — background workers,
agent decisions, job completions, system health, and todo lifecycle transitions. It replaces all
existing bespoke notification paths (`notification_outbox`, session outbox workers, hook outbox
notification paths, direct channel posting for operational events).

The notification service is the platform's nervous system: sensory input (events via Redis Streams),
processing (schema-driven routing), motor output (state updates + delivery), awareness (multi-surface
projections of the same truth via API, WebSocket push, and Discord).

## Scope

### In scope

1. **Separate package** (`teleclaude_notifications/`) with clean dependency direction:
   `teleclaude` imports from the notification package, never the reverse.
2. **Envelope schema** (Pydantic models) with identity, semantic, data, and resolution layers.
   The affordance layer (actions) is structurally present but not yet processed.
3. **Redis Streams ingress**: producer utility (`xadd`) for appending events; consumer group
   in the notification processor for ordered, persistent, replayable consumption.
4. **Notification processor**: async worker that reads from the Redis Stream consumer group,
   applies schema rules, and projects events into the SQLite read model. Schema-driven: adding
   a new event type requires only a schema definition, zero processor code.
5. **Separate SQLite database** owned by the notification service (not the daemon's DB).
   Notification table with: id, event type, level, domain, source, entity ref, description,
   payload (JSON), human awareness state, agent handling state, idempotency key, timestamps,
   resolution data.
6. **Notification state machine** with two orthogonal dimensions:
   - Human awareness: `unseen` → `seen`
   - Agent handling: `none` → `claimed` → `in_progress` → `resolved`
7. **HTTP API** on the existing daemon API server for:
   - List notifications (filterable by level, domain, status, time range)
   - Get single notification
   - Mark seen / mark unseen
   - Claim notification (agent)
   - Update handling status (agent)
   - Resolve notification (agent, with structured result)
8. **WebSocket push**: emit notification events (created, updated, state changed) to connected
   TUI/web clients via the existing WebSocket infrastructure.
9. **Daemon hosting**: daemon starts the notification processor on startup, stops on shutdown.
   The notification package could theoretically run in any Python host process.
10. **Initial dog-food event catalog** — Pydantic schema definitions for:
    - Todo lifecycle: `todo.created`, `todo.dumped`, `todo.activated`, `todo.artifact_changed`,
      `todo.dependency_resolved`, `todo.dor_assessed`
    - System: `system.daemon_restarted`, `system.worker_crashed`
    - Build/review: `build.completed`, `review.verdict_ready`, `review.needs_decision`
11. **First producers wired**: daemon restart event, todo state transitions (at minimum
    `todo.dor_assessed` for prepare-quality-runner dependency).
12. **Idempotency**: per-schema idempotency key derivation from payload fields. Duplicate
    events are deduplicated or appended per schema declaration.
13. **`telec events list` CLI command**: list registered event types with descriptions.
14. **Consolidation**: remove the existing `teleclaude/notifications/` package (outbox worker,
    router, telegram delivery, discovery) and its `notification_outbox` DB table/migrations
    once the new service is operational. Wire the remaining Telegram delivery need (admin alerts)
    through the new service as a delivery adapter.

### Out of scope (deferred to follow-up todos)

- **Affordance processing**: the envelope schema includes the `actions` field structurally,
  but the processor does not interpret or execute affordances in this phase.
- **Progressive automation / graduated sovereignty**: AI-driven discover → interpret → approve →
  codify → consume cycle. Future work.
- **Consumption spectrum** (AI-assisted, discovery modes): `telec events discover`, `telec events watch`.
- **Discord delivery surface**: notifications posted/edited in Discord #notifications channel.
  Requires Discord adapter integration. Separate todo.
- **`telec://` URI scheme**: platform-wide resource addressing and per-client resolvers.
- **External service callback envelope pattern**: enrichment round-trip for external services.
- **Content lifecycle events**: depends on `content-dump-command` todo.
- **Stale claim GC**: automatic expiry of stale `claimed`/`in_progress` notifications.
  Can be added as a maintenance task later.
- **Referential integrity checks**: lazy/periodic checks when referenced entities are deleted.
- **Web frontend notifications panel**: depends on web frontend existing.
- **Event level filtering in TUI**: TUI notification view with level-based filtering.

## Success Criteria

- [ ] Notification package exists as a separate directory with no imports from `teleclaude.*`.
- [ ] A producer can emit an event via a single function call that XADD's to the Redis Stream.
- [ ] The processor reads from the stream, deduplicates, and writes to the SQLite read model.
- [ ] The API returns a list of notifications filterable by level and status.
- [ ] WebSocket clients receive push events when notifications are created or updated.
- [ ] At least one dog-food producer is wired (daemon restart or todo.dor_assessed).
- [ ] The old `teleclaude/notifications/` package is removed and its DB table is no longer used.
- [ ] Adding a new event type requires only a Pydantic schema definition — no processor changes.
- [ ] `telec events list` shows all registered event types.
- [ ] `make test` passes with tests covering producer, processor, state machine, and API.
- [ ] `make lint` passes.

## Constraints

- Must use Redis Streams (already running Redis). No additional message brokers.
- Must use a separate SQLite file (not the daemon's DB). Consistent with the design rationale
  in `input.md` — no write contention, independent lifecycle, clean ownership.
- The notification package must have zero imports from `teleclaude.*`. Dependency direction is
  strictly one-way.
- Wire format is JSON. Internal models are Pydantic. The envelope schema is versioned.
- Async-first: all I/O operations must be async, consistent with the codebase.

## Risks

- **Scope creep**: the vision in `input.md` is large. This todo scopes to the core service.
  Dependent features (progressive automation, URI scheme, Discord delivery) are explicitly
  deferred.
- **Redis Streams learning curve**: the codebase uses Redis Streams for cross-computer messaging
  already, but consumer groups may introduce new patterns (acknowledgment, pending entries).
- **Migration from old system**: removing the existing notification package requires finding all
  call sites and rewiring. The outbox is used by the daemon for Telegram admin alerts.
- **Separate database coordination**: the notification service's SQLite file needs its own
  migration runner, connection management, and lifecycle — parallel to but independent of
  the daemon's DB infrastructure.
