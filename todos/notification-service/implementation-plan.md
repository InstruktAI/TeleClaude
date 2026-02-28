# Implementation Plan: notification-service

## Overview

Build the notification service as a separate Python package (`teleclaude_notifications/`) that
the daemon hosts. The approach follows the event-sourcing architecture from the design: Redis
Streams as the event log, SQLite as the read model, and a processor that projects events into
queryable notification state. The existing `teleclaude/notifications/` outbox system is removed
after the new service is operational.

The plan is ordered for incremental testability: schema first, then storage, then processing,
then API, then wiring, then consolidation.

## Phase 1: Package Foundation & Envelope Schema

### Task 1.1: Create package structure

**File(s):** `teleclaude_notifications/__init__.py`, `teleclaude_notifications/py.typed`

- [ ] Create `teleclaude_notifications/` at the monorepo root (sibling to `teleclaude/`)
- [ ] Add `__init__.py` with public API exports
- [ ] Add `py.typed` marker for type checking
- [ ] Add the package to `pyproject.toml` as a local dependency or namespace package
- [ ] Verify: `from teleclaude_notifications import ...` works; no `teleclaude.*` imports in the package

### Task 1.2: Define envelope schema

**File(s):** `teleclaude_notifications/envelope.py`

- [ ] Define `EventEnvelope` Pydantic model with five layers:
  - Identity: `event` (str), `version` (int), `source` (str), `timestamp` (datetime), `idempotency_key` (str | None)
  - Semantic: `level` (int, 0-3), `domain` (str), `entity` (str | None), `description` (str)
  - Data: `payload` (dict[str, object])
  - Affordances: `actions` (dict[str, ActionDescriptor] | None) — structurally present, not processed
  - Resolution: `terminal_when` (str | None), `resolution_shape` (dict | None)
- [ ] Define `ActionDescriptor` model: `description`, `produces`, `outcome_shape`
- [ ] Define `EventLevel` integer enum: `INFRASTRUCTURE = 0`, `OPERATIONAL = 1`, `WORKFLOW = 2`, `BUSINESS = 3`
- [ ] Add `to_stream_dict()` → dict for Redis XADD, `from_stream_dict()` classmethod for deserialization
- [ ] Schema version field defaults to `1`

### Task 1.3: Define event catalog registry

**File(s):** `teleclaude_notifications/catalog.py`

- [ ] Define `EventSchema` base class/model that declares:
  - `event_type` (str, e.g. `todo.created`)
  - `description` (str)
  - `default_level` (EventLevel)
  - `domain` (str)
  - `idempotency_fields` (list[str] — payload fields that compose the idempotency key)
  - `meaningful_transitions` (list[str] — payload field changes that reset to unread)
  - `silent_updates` (list[str] — payload field changes that update without unread reset)
  - `actionable` (bool — whether agents can claim/resolve)
- [ ] Define `EventCatalog` class: registry of `EventSchema` instances keyed by event type
- [ ] `register(schema: EventSchema)` method
- [ ] `get(event_type: str) -> EventSchema | None` method
- [ ] `list_all() -> list[EventSchema]` method
- [ ] `build_idempotency_key(event_type, payload) -> str` from schema fields

---

## Phase 2: Storage Layer

### Task 2.1: SQLite database setup

**File(s):** `teleclaude_notifications/db.py`

- [ ] Create async SQLite connection manager for a separate database file
      (path configurable, default: `~/.teleclaude/notifications.db`)
- [ ] Implement `async init_db()` that creates tables if not exist
- [ ] Implement `async close()` for clean shutdown
- [ ] Use aiosqlite (already a project dependency)
- [ ] WAL mode for concurrent readers

### Task 2.2: Notification table schema

**File(s):** `teleclaude_notifications/db.py`

- [ ] Create `notifications` table:
  ```sql
  CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    level INTEGER NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    entity TEXT,
    description TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT,
    -- Human awareness
    human_status TEXT NOT NULL DEFAULT 'unseen',  -- unseen, seen
    -- Agent handling
    agent_status TEXT NOT NULL DEFAULT 'none',     -- none, claimed, in_progress, resolved
    agent_id TEXT,
    -- Resolution
    resolution TEXT,  -- JSON: {summary, link, resolved_by, resolved_at}
    -- Timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seen_at TEXT,
    claimed_at TEXT,
    resolved_at TEXT,
    -- Dedup
    UNIQUE(idempotency_key)
  );
  ```
- [ ] Add indexes: `(event_type)`, `(level)`, `(human_status)`, `(agent_status)`, `(created_at DESC)`
- [ ] Add CRUD methods:
  - `insert_notification(envelope: EventEnvelope) -> int`
  - `get_notification(id: int) -> NotificationRow | None`
  - `list_notifications(filters) -> list[NotificationRow]`
  - `update_human_status(id, status) -> bool`
  - `update_agent_status(id, status, agent_id) -> bool`
  - `resolve_notification(id, resolution) -> bool`
  - `upsert_by_idempotency_key(envelope) -> tuple[int, bool]` (id, was_created)
- [ ] Define `NotificationRow` TypedDict for query results

---

## Phase 3: Redis Streams Ingress & Processor

### Task 3.1: Producer utility

**File(s):** `teleclaude_notifications/producer.py`

- [ ] Define `NotificationProducer` class:
  - Constructor takes `redis_url: str` (or async Redis client)
  - `async emit(envelope: EventEnvelope) -> str` — XADD to stream, returns stream entry ID
  - Stream name: `teleclaude:notifications` (configurable)
  - Maxlen trim: `XADD ... MAXLEN ~ 10000` to prevent unbounded growth
- [ ] Convenience function: `async emit_event(event_type, source, level, domain, description, payload, **kwargs) -> str`
      that constructs an envelope and emits it
- [ ] The producer is stateless — any process can create one and emit events

### Task 3.2: Notification processor (consumer)

**File(s):** `teleclaude_notifications/processor.py`

- [ ] Define `NotificationProcessor` class:
  - Constructor takes Redis client, `NotificationDB`, `EventCatalog`, and a callback for push notifications
  - Consumer group name: `notification-processor`
  - Consumer name: unique per daemon instance (e.g., `{computer_name}-{pid}`)
  - `async start(shutdown_event: asyncio.Event)` — main loop:
    1. Ensure consumer group exists (`XGROUP CREATE ... MKSTREAM`)
    2. Read from stream with `XREADGROUP ... BLOCK 1000 COUNT 10`
    3. For each entry: deserialize envelope, look up schema in catalog
    4. Compute idempotency key from schema + payload
    5. Upsert into SQLite (dedup or create)
    6. Determine if transition is meaningful (schema rules) → set human_status accordingly
    7. ACK the stream entry (`XACK`)
    8. Call push callback with (notification_id, event_type, was_created, is_meaningful)
  - Pending entry recovery: on startup, process any un-ACK'd entries (`XREADGROUP ... > 0`)
  - Graceful shutdown: stop reading, finish in-flight processing
- [ ] Unknown event types (no schema in catalog): store with defaults, log warning

---

## Phase 4: API & WebSocket Integration

### Task 4.1: HTTP API endpoints

**File(s):** `teleclaude/api_server.py` (extend existing)

- [ ] `GET /api/notifications` — list notifications with query params:
  - `level` (int, filter by minimum level)
  - `domain` (str)
  - `human_status` (str: unseen, seen)
  - `agent_status` (str: none, claimed, in_progress, resolved)
  - `since` (ISO8601 timestamp)
  - `limit` (int, default 50, max 200)
  - `offset` (int, default 0)
- [ ] `GET /api/notifications/{id}` — single notification
- [ ] `PATCH /api/notifications/{id}/seen` — mark seen (or unseen with `?unseen=true`)
- [ ] `POST /api/notifications/{id}/claim` — agent claims (body: `{agent_id}`)
- [ ] `PATCH /api/notifications/{id}/status` — update agent status (body: `{status, agent_id}`)
- [ ] `POST /api/notifications/{id}/resolve` — resolve (body: `{summary, link, resolved_by}`)
- [ ] All endpoints return JSON with notification data

### Task 4.2: WebSocket notification push

**File(s):** `teleclaude/api_server.py` (extend existing)

- [ ] Define a `notification_push` callback that the processor calls
- [ ] Broadcast notification events to WebSocket clients:
  - `{type: "notification_created", notification: {...}}`
  - `{type: "notification_updated", notification: {...}}`
- [ ] WebSocket clients can subscribe to notification events (extend existing subscription system)

---

## Phase 5: Daemon Integration & CLI

### Task 5.1: Daemon hosting

**File(s):** `teleclaude/daemon.py`

- [ ] Import `NotificationProcessor`, `NotificationDB`, `NotificationProducer`, `EventCatalog`
- [ ] In daemon startup:
  1. Initialize `NotificationDB` (open separate SQLite, run init)
  2. Build `EventCatalog` with all registered schemas
  3. Create `NotificationProducer` (using existing Redis connection)
  4. Create `NotificationProcessor` (Redis, DB, catalog, push callback)
  5. Start processor as background task
- [ ] In daemon shutdown: signal processor to stop, close notification DB
- [ ] Expose `NotificationProducer` instance for other daemon components to emit events

### Task 5.2: Wire first producers

**File(s):** `teleclaude/daemon.py`, `teleclaude/services/` (as needed)

- [ ] Emit `system.daemon_restarted` on daemon startup (after notification processor is ready)
- [ ] Emit `todo.dor_assessed` when DOR state changes in state.yaml (hook into todo watcher
      or state sweep — whichever detects dor changes)
- [ ] Verify: notifications appear in the SQLite read model after emission

### Task 5.3: Telegram delivery adapter

**File(s):** `teleclaude_notifications/delivery/telegram.py`, `teleclaude/daemon.py`

- [ ] Create `teleclaude_notifications/delivery/` package with a `TelegramDeliveryAdapter`
- [ ] The adapter receives notification creation callbacks from the processor
- [ ] Filter: only deliver notifications at level >= WORKFLOW (L2) or specific event types
      configured for Telegram delivery (e.g., `review.needs_decision`, `system.worker_crashed`)
- [ ] Reuse the existing `send_telegram_dm` function from `teleclaude/notifications/telegram.py`
      (copy the function into the new package before Phase 6 removes the old package)
- [ ] Register the Telegram adapter as a second push callback alongside WebSocket in daemon startup
- [ ] Verify: a high-level notification triggers both WebSocket push and Telegram delivery

### Task 5.5: Initial event catalog schemas

**File(s):** `teleclaude_notifications/schemas/`

- [ ] Create schema directory with one file per domain
- [ ] `teleclaude_notifications/schemas/todo.py`:
  - `todo.created`, `todo.dumped`, `todo.activated`, `todo.artifact_changed`,
    `todo.dependency_resolved`, `todo.dor_assessed`
- [ ] `teleclaude_notifications/schemas/system.py`:
  - `system.daemon_restarted`, `system.worker_crashed`
- [ ] `teleclaude_notifications/schemas/build.py`:
  - `build.completed`, `review.verdict_ready`, `review.needs_decision`
- [ ] Register all schemas in a default catalog factory function

### Task 5.6: CLI command

**File(s):** `teleclaude/cli/` (telec events subcommand)

- [ ] `telec events list` — list all registered event types with description and level
- [ ] Output format: table with columns: event_type, level, domain, description, actionable

---

## Phase 6: Consolidation

### Task 6.1: Remove old notification system

**File(s):** `teleclaude/notifications/` (entire directory), `teleclaude/daemon.py`,
`teleclaude/core/db.py`

- [ ] Remove `teleclaude/notifications/` package entirely
- [ ] Remove `notification_outbox_task` startup in daemon
- [ ] Remove `NotificationOutboxWorker` and `NotificationRouter` imports
- [ ] Remove `notification_outbox` table methods from `db.py`
      (`enqueue_notification`, `fetch_notification_batch`, `claim_notification`,
      `mark_notification_delivered`, `mark_notification_failed`)
- [ ] Keep migration `009_add_notification_outbox.py` and `019_add_delivery_channel.py`
      in place (migrations are append-only) but add a migration that drops the
      `notification_outbox` table
- [ ] Audit all call sites that used `NotificationRouter.enqueue()` and rewire to
      `NotificationProducer.emit()` or remove if no longer needed
- [ ] Verify: no references to old notification package remain

---

## Phase 7: Validation

### Task 7.1: Tests

- [ ] Unit tests for `EventEnvelope` serialization/deserialization
- [ ] Unit tests for `EventCatalog` registration and idempotency key derivation
- [ ] Unit tests for `NotificationDB` CRUD operations
- [ ] Integration test: producer → Redis Stream → processor → SQLite → API query
- [ ] Test notification state machine transitions (claim, resolve, mark seen)
- [ ] Test idempotency: duplicate event produces no new row
- [ ] Test WebSocket push callback is invoked on notification creation
- [ ] Run `make test`

### Task 7.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no `teleclaude.*` imports in `teleclaude_notifications/`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Verify old notification package is fully removed

---

## Phase 8: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
