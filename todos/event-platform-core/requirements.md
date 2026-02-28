# Requirements: event-platform-core

## Goal

Build the foundation of the event processing platform as a separate Python package
(`teleclaude_events/`) within the TeleClaude monorepo. This delivers: the event envelope,
a pipeline runtime with pluggable cartridges, Redis Streams ingress, SQLite notification
state as one projection, HTTP API, WebSocket push, daemon hosting, initial event schemas,
and consolidation of the old notification system.

Events are the primary concept. The pipeline runtime accepts cartridges — this phase ships
two (deduplication + notification projector). Later phases add trust, enrichment, correlation,
classification, and domain-scoped processing without changing the runtime.

## Scope

### In scope

1. **Separate package** (`teleclaude_events/`) at the monorepo root, sibling to `teleclaude/`.
   Clean dependency direction: `teleclaude` imports from `teleclaude_events`, never the reverse.
   `pyproject.toml` updated for package discovery.

2. **Five-layer envelope schema** (Pydantic model):
   - Identity: event type, version, source, timestamp, idempotency key
   - Semantic: level (0-3), domain, entity ref, description, **visibility** (`local`/`cluster`/`public`)
   - Data: payload (arbitrary JSON dict)
   - Affordances: action descriptors (structurally present, not processed in this phase)
   - Resolution: terminal conditions, resolution shape
   - Serialization: `to_stream_dict()` / `from_stream_dict()` for Redis wire format

3. **Event catalog**: Pydantic-based type registry. Each schema declares: event type,
   description, default level, domain, default visibility, idempotency fields, notification
   lifecycle mapping (which events create/update/resolve notifications), meaningful vs silent
   transitions, whether actionable.

4. **Redis Streams producer**: `emit()` function that XADD's an envelope to the
   `teleclaude:events` stream. Stateless — any process can emit. Maxlen trim (~10000).

5. **Pipeline runtime**: sequential cartridge executor. Reads from Redis Stream via consumer
   group (XREADGROUP). For each event: deserialize → run through ordered cartridge chain →
   ACK. The runtime is the foundation — it doesn't know what cartridges do, only how to
   call them in order. Cartridge interface:

   ```python
   async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None
   ```

   `PipelineContext` provides: event catalog, notification DB handle, push callback.

6. **Deduplication cartridge**: checks idempotency key derived from schema-declared payload
   fields. Drops duplicates (returns None). First cartridge in the chain.

7. **Notification projector cartridge**: reads the event's schema lifecycle declaration.
   If the event type declares a notification lifecycle, creates/updates/resolves the
   corresponding SQLite notification row. If no lifecycle declared, passes through (no-op
   for non-notification events). Last cartridge in the chain.

8. **Separate SQLite database** (`~/.teleclaude/events.db`). Notification table with:
   id, event_type, version, source, level, domain, visibility, entity, description,
   payload (JSON), human_status, agent_status, agent_id, resolution (JSON), timestamps,
   idempotency_key (UNIQUE). WAL mode.

9. **Notification state machine** — two orthogonal dimensions:
   - Human awareness: `unseen` → `seen`
   - Agent handling: `none` → `claimed` → `in_progress` → `resolved`
   - Meaningful transitions reset `human_status` to `unseen` (schema-declared).
   - Silent updates don't reset.

10. **HTTP API** on the existing daemon FastAPI server:
    - `GET /api/notifications` — list (filterable by level, domain, human_status,
      agent_status, visibility, since, limit, offset)
    - `GET /api/notifications/{id}` — single notification
    - `PATCH /api/notifications/{id}/seen` — mark seen/unseen
    - `POST /api/notifications/{id}/claim` — agent claims
    - `PATCH /api/notifications/{id}/status` — update agent status
    - `POST /api/notifications/{id}/resolve` — resolve with structured result

11. **WebSocket push**: emit notification events (created, updated, state changed) to
    connected TUI/web clients via the existing WebSocket subscription system. New
    subscription topic: `notifications`.

12. **Daemon hosting**: start pipeline processor as background task on daemon startup
    (same pattern as `NotificationOutboxWorker`). Stop on shutdown. Expose producer
    instance for other daemon components.

13. **Telegram delivery adapter**: receives processor callbacks, filters by level >= WORKFLOW,
    reuses existing `send_telegram_dm`. Registered as a push callback alongside WebSocket.

14. **Initial event schemas** (Pydantic):
    - System: `system.daemon.restarted`, `system.worker.crashed`
    - Planning: `domain.software-development.planning.todo_created`,
      `domain.software-development.planning.todo_dumped`,
      `domain.software-development.planning.todo_activated`,
      `domain.software-development.planning.artifact_changed`,
      `domain.software-development.planning.dependency_resolved`,
      `domain.software-development.planning.dor_assessed`
    - Build/review: `domain.software-development.build.completed`,
      `domain.software-development.review.verdict_ready`,
      `domain.software-development.review.needs_decision`

15. **First producers wired**:
    - `system.daemon.restarted` emitted on daemon startup (after processor ready)
    - `domain.software-development.planning.dor_assessed` emitted when DOR state changes

16. **`telec events list` CLI command**: list registered event types with description,
    level, domain, visibility. Table format.

17. **Idempotency**: per-schema idempotency key derivation from payload fields. Duplicates
    deduplicated by the dedup cartridge (dropped before projection).

18. **Consolidation**: remove `teleclaude/notifications/` package (outbox worker, router,
    telegram delivery, discovery). Remove `notification_outbox` table methods from `db.py`.
    Add migration that drops `notification_outbox` table. Rewire all call sites to new
    producer or remove if dead.

### Out of scope (later sub-todos of event-platform)

- Trust evaluator, enrichment, correlation, classification cartridges (→ event-system-cartridges)
- Domain pipeline (parallel per domain), personal subscriptions (→ event-domain-infrastructure)
- Domain guardian AIs, folder hierarchy (→ event-domain-infrastructure)
- Signal processing pipeline (→ event-signal-pipeline)
- Alpha container / Docker sidecar (→ event-alpha-container)
- Mesh distribution, public event forwarding (→ event-mesh-distribution)
- Domain pillars (→ event-domain-pillars)
- Affordance processing / execution
- `telec://` URI scheme
- Discord delivery surface
- Progressive automation cycle
- Autonomy matrix (L1/L2/L3 configuration) — the visibility field is structural in this phase
  but cluster/public distribution is not wired until mesh-distribution

## Success Criteria

- [ ] `teleclaude_events/` exists with no `teleclaude.*` imports
- [ ] `from teleclaude_events import EventEnvelope, emit_event, EventCatalog` works
- [ ] A producer can emit an event via `emit_event()` that XADD's to Redis Stream
- [ ] Pipeline runtime reads events and pushes them through cartridge chain
- [ ] Dedup cartridge drops duplicate events (same idempotency key)
- [ ] Notification projector creates SQLite rows for lifecycle-declared events
- [ ] API returns notifications filterable by level, domain, status
- [ ] WebSocket clients receive push events when notifications are created/updated
- [ ] Telegram adapter delivers high-level notifications
- [ ] `telec events list` shows all registered event types
- [ ] At least one dog-food producer is wired (daemon restart)
- [ ] Old `teleclaude/notifications/` package is removed
- [ ] Adding a new event type requires only a schema definition — no runtime changes
- [ ] `make test` passes with coverage for envelope, catalog, pipeline, DB, API
- [ ] `make lint` passes

## Constraints

- Redis Streams (already running). No additional message brokers.
- Separate SQLite file (`~/.teleclaude/events.db`). Not the daemon's DB.
- Zero imports from `teleclaude.*` in the events package. One-way dependency.
- Wire format: JSON. Internal models: Pydantic. Schema versioned.
- Async-first: all I/O async (aiosqlite, redis-py async).
- Pipeline runtime must accept arbitrary cartridges — the dedup and projector are just the
  first two. Adding more later must not require runtime changes.
- Consumer group `event-processor` with one consumer per daemon instance.

## Risks

- **XREADGROUP pattern**: the channels module (`teleclaude/channels/consumer.py`) already
  uses `xreadgroup` with `ensure_consumer_group`. The builder should reference this existing
  pattern directly. Lower risk than initially assessed.
- **Migration from old system**: `notification_outbox` call sites need auditing. The
  `NotificationRouter.enqueue()` calls need to be found and rewired.
- **Separate DB coordination**: own init, connection management, WAL mode, clean shutdown.
  Parallel to but independent of daemon's DB infrastructure.
- **Scope**: 22 tasks across 8 phases. Large but incrementally testable — builder commits
  after each phase and can resume in a new session.
