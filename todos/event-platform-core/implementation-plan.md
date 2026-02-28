# Implementation Plan: event-platform-core

## Overview

Build the event processing platform core as a separate package (`teleclaude_events/`).
The plan is ordered for incremental testability: schema first, then storage, then pipeline,
then API, then wiring, then consolidation. Builder commits after each phase.

Codebase patterns to follow:

| Pattern             | Evidence                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------- |
| Redis Streams XADD  | `teleclaude/transport/redis_transport.py:1731` — `xadd(stream, data, maxlen=...)`         |
| Redis Streams XREAD | `teleclaude/transport/redis_transport.py:1001` — blocking XREAD with last_id tracking     |
| Durable last-ID     | `teleclaude/transport/redis_transport.py:621-644` — last processed ID in SQLite           |
| aiosqlite DB        | `teleclaude/core/db.py` — WAL mode, async connection management                           |
| Pydantic models     | Established pattern across codebase                                                       |
| FastAPI endpoints   | `teleclaude/api_server.py` — route registration on `self.app`                             |
| WebSocket push      | `teleclaude/api_server.py:1878-2354` — subscription + `_schedule_refresh_broadcast`       |
| Background task     | `teleclaude/daemon.py:1857` — `asyncio.create_task(worker.run())` + done callback         |
| Notification worker | `teleclaude/notifications/worker.py:24` — `NotificationOutboxWorker` (replacement target) |
| Telegram delivery   | `teleclaude/notifications/telegram.py` — `send_telegram_dm()` (reuse target)              |

## Phase 1: Package Foundation & Envelope Schema

### Task 1.1: Create package structure

**File(s):** `teleclaude_events/__init__.py`, `teleclaude_events/py.typed`, `pyproject.toml`

- [ ] Create `teleclaude_events/` at monorepo root (sibling to `teleclaude/`)
- [ ] Add `__init__.py` with public API:
  ```python
  from teleclaude_events.envelope import EventEnvelope, EventLevel, ActionDescriptor, EventVisibility
  from teleclaude_events.catalog import EventCatalog, EventSchema
  from teleclaude_events.producer import emit_event, EventProducer
  ```
- [ ] Add `py.typed` marker
- [ ] Update `pyproject.toml` packages.find include: `["teleclaude*"]` already matches
      `teleclaude_events*` — verify this works. If not, add explicit include.
- [ ] Verify: `python -c "from teleclaude_events import EventEnvelope"` succeeds
- [ ] Verify: `grep -r "from teleclaude\." teleclaude_events/` returns nothing

### Task 1.2: Define envelope schema

**File(s):** `teleclaude_events/envelope.py`

- [ ] Define `EventVisibility` string enum: `LOCAL = "local"`, `CLUSTER = "cluster"`, `PUBLIC = "public"`
- [ ] Define `EventLevel` integer enum: `INFRASTRUCTURE = 0`, `OPERATIONAL = 1`, `WORKFLOW = 2`, `BUSINESS = 3`
- [ ] Define `ActionDescriptor` Pydantic model:
  - `description: str`
  - `produces: str` (event type that this action would emit)
  - `outcome_shape: dict[str, str] | None = None`
- [ ] Define `EventEnvelope` Pydantic model:
  ```python
  class EventEnvelope(BaseModel):
      # Identity
      event: str                          # e.g. "domain.software-development.build.completed"
      version: int = 1
      source: str                         # e.g. "daemon", "prepare-worker"
      timestamp: datetime = Field(default_factory=datetime.utcnow)
      idempotency_key: str | None = None
      # Semantic
      level: EventLevel
      domain: str = ""
      entity: str | None = None           # e.g. "telec://todo/event-platform-core"
      description: str = ""
      visibility: EventVisibility = EventVisibility.LOCAL
      # Data
      payload: dict[str, object] = Field(default_factory=dict)
      # Affordances (structural, not processed in core)
      actions: dict[str, ActionDescriptor] | None = None
      # Resolution
      terminal_when: str | None = None
      resolution_shape: dict[str, str] | None = None
  ```
- [ ] Add `to_stream_dict(self) -> dict[str, str]`: serialize all fields to string dict for XADD
- [ ] Add `@classmethod from_stream_dict(cls, data: dict[bytes, bytes]) -> EventEnvelope`: deserialize
- [ ] Add `model_config` with `json_encoders` for datetime serialization

### Task 1.3: Define event catalog registry

**File(s):** `teleclaude_events/catalog.py`

- [ ] Define `NotificationLifecycle` model:
  ```python
  class NotificationLifecycle(BaseModel):
      creates: bool = False               # this event type creates a new notification
      updates: bool = False               # this event type updates an existing notification
      resolves: bool = False              # this event type resolves a notification
      group_key: str | None = None        # payload field that correlates lifecycle events
      meaningful_fields: list[str] = []   # payload changes that reset to unseen
      silent_fields: list[str] = []       # payload changes that update without unseen reset
  ```
- [ ] Define `EventSchema` model:
  ```python
  class EventSchema(BaseModel):
      event_type: str
      description: str
      default_level: EventLevel
      domain: str
      default_visibility: EventVisibility = EventVisibility.LOCAL
      idempotency_fields: list[str] = []  # payload fields composing idempotency key
      lifecycle: NotificationLifecycle | None = None  # None = not notification-worthy
      actionable: bool = False            # whether agents can claim/resolve
  ```
- [ ] Define `EventCatalog` class:
  - `_registry: dict[str, EventSchema]`
  - `register(schema: EventSchema) -> None` — raises on duplicate
  - `get(event_type: str) -> EventSchema | None`
  - `list_all() -> list[EventSchema]` — sorted by event_type
  - `build_idempotency_key(event_type: str, payload: dict) -> str | None` — from schema fields,
    returns `"{event_type}:{field1_val}:{field2_val}"` or None if no idempotency fields
- [ ] Define `build_default_catalog() -> EventCatalog` factory that registers all built-in schemas

---

## Phase 2: Storage Layer

### Task 2.1: SQLite database setup

**File(s):** `teleclaude_events/db.py`

- [ ] Define `EventDB` class:
  - `__init__(self, db_path: str | Path = "~/.teleclaude/events.db")`
  - `async init(self) -> None` — expand path, create parent dirs, open aiosqlite connection,
    enable WAL mode, create tables
  - `async close(self) -> None` — close connection cleanly
  - Internal: `self._conn: aiosqlite.Connection`

### Task 2.2: Notification table schema

**File(s):** `teleclaude_events/db.py`

- [ ] Create `notifications` table in `init()`:
  ```sql
  CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    level INTEGER NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'local',
    entity TEXT,
    description TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT,
    human_status TEXT NOT NULL DEFAULT 'unseen',
    agent_status TEXT NOT NULL DEFAULT 'none',
    agent_id TEXT,
    resolution TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seen_at TEXT,
    claimed_at TEXT,
    resolved_at TEXT,
    UNIQUE(idempotency_key)
  );
  ```
- [ ] Create indexes: `(event_type)`, `(level)`, `(domain)`, `(human_status)`, `(agent_status)`,
      `(visibility)`, `(created_at DESC)`
- [ ] Define `NotificationRow` TypedDict matching all columns
- [ ] Implement CRUD methods:
  - `async insert_notification(envelope: EventEnvelope, schema: EventSchema) -> int`
  - `async get_notification(id: int) -> NotificationRow | None`
  - `async list_notifications(**filters) -> list[NotificationRow]`
    (level, domain, human_status, agent_status, visibility, since, limit, offset)
  - `async update_human_status(id: int, status: str) -> bool`
  - `async update_agent_status(id: int, status: str, agent_id: str) -> bool`
  - `async resolve_notification(id: int, resolution: dict) -> bool`
  - `async upsert_by_idempotency_key(envelope, schema) -> tuple[int, bool]`
    (returns notification_id, was_created)
  - ~~`pipeline_state` methods removed — consumer group tracking handles this via Redis~~

---

## Phase 3: Pipeline Runtime & Cartridges

### Task 3.1: Pipeline context and cartridge protocol

**File(s):** `teleclaude_events/pipeline.py`

- [ ] Define `PipelineContext` dataclass:
  ```python
  @dataclass
  class PipelineContext:
      catalog: EventCatalog
      db: EventDB
      push_callbacks: list[Callable]  # async callbacks for notification events
  ```
- [ ] Define `Cartridge` Protocol:
  ```python
  class Cartridge(Protocol):
      name: str
      async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None: ...
  ```

### Task 3.2: Deduplication cartridge

**File(s):** `teleclaude_events/cartridges/dedup.py`

- [ ] Define `DeduplicationCartridge`:
  - `name = "dedup"`
  - `async def process(self, event, context)`:
    1. Look up schema in catalog
    2. Build idempotency key from schema + payload
    3. If key is None (no idempotency fields declared): pass through unchanged
    4. Set `event.idempotency_key` on the envelope
    5. Check if key already exists in `context.db` (`SELECT 1 FROM notifications WHERE idempotency_key = ?`)
    6. If exists: return None (drop the duplicate — event never reaches downstream cartridges)
    7. If new: return event (passes to projector which inserts)
  - Dedup is a hard gate — duplicates are dropped, not upserted.

### Task 3.3: Notification projector cartridge

**File(s):** `teleclaude_events/cartridges/notification.py`

- [ ] Define `NotificationProjectorCartridge`:
  - `name = "notification-projector"`
  - `async def process(self, event, context)`:
    1. Look up schema in catalog
    2. If schema has no lifecycle declaration: return event unchanged (pass-through)
    3. If lifecycle.creates: upsert notification via `context.db.upsert_by_idempotency_key()`
    4. If lifecycle.updates: find existing notification by group_key, update fields,
       check meaningful_fields → reset human_status to unseen if meaningful
    5. If lifecycle.resolves: find existing notification, set agent_status to resolved
    6. Call push callbacks: `(notification_id, event_type, was_created, is_meaningful)`
    7. Return event

### Task 3.4: Pipeline executor

**File(s):** `teleclaude_events/pipeline.py`

- [ ] Define `Pipeline` class:
  - `__init__(self, cartridges: list[Cartridge], context: PipelineContext)`
  - `async def execute(self, event: EventEnvelope) -> EventEnvelope | None`:
    Run event through cartridge chain sequentially. If any returns None, stop (event dropped).

### Task 3.5: Redis Streams consumer (event processor)

**File(s):** `teleclaude_events/processor.py`

- [ ] Define `EventProcessor` class:
  - Constructor: Redis client, `Pipeline`, stream name (`teleclaude:events`),
    consumer group (`event-processor`), consumer name (`{computer}-{pid}`)
  - `async start(self, shutdown_event: asyncio.Event) -> None`:
    1. Ensure consumer group: `XGROUP CREATE teleclaude:events event-processor $ MKSTREAM`
       (ignore error if group exists)
    2. Recover pending: `XREADGROUP GROUP event-processor {consumer} COUNT 10 STREAMS teleclaude:events 0`
       — process any un-ACK'd entries first
    3. Main loop (until shutdown):
       - `XREADGROUP GROUP event-processor {consumer} BLOCK 1000 COUNT 10 STREAMS teleclaude:events >`
       - For each entry: deserialize envelope, run pipeline.execute(), XACK
    4. On shutdown: finish in-flight, return

### Task 3.6: Producer utility

**File(s):** `teleclaude_events/producer.py`

- [ ] Define `EventProducer` class:
  - Constructor: async Redis client, stream name (default `teleclaude:events`),
    maxlen (default 10000)
  - `async emit(self, envelope: EventEnvelope) -> str`: XADD to stream, return entry ID
- [ ] Define module-level convenience function:
  ```python
  async def emit_event(
      event: str, source: str, level: EventLevel, domain: str = "",
      description: str = "", payload: dict | None = None,
      visibility: EventVisibility = EventVisibility.LOCAL,
      entity: str | None = None, **kwargs
  ) -> str
  ```
  Constructs envelope + emits via a module-level producer (lazy-initialized on first call,
  or raises if not configured). The daemon configures this on startup.

---

## Phase 4: API & WebSocket Integration

### Task 4.1: HTTP API endpoints

**File(s):** `teleclaude/api_server.py`

- [x] Add notification API routes (in `_setup_routes` or equivalent):
  - `GET /api/notifications` → `_list_notifications()`
    Query params: level (int), domain (str), human_status, agent_status, visibility,
    since (ISO8601), limit (int, default 50, max 200), offset (int)
  - `GET /api/notifications/{notification_id}` → `_get_notification()`
  - `PATCH /api/notifications/{notification_id}/seen` → `_mark_notification_seen()`
    Query param: `unseen=true` to mark unseen
  - `POST /api/notifications/{notification_id}/claim` → `_claim_notification()`
    Body: `{"agent_id": str}`
  - `PATCH /api/notifications/{notification_id}/status` → `_update_notification_status()`
    Body: `{"status": str, "agent_id": str}`
  - `POST /api/notifications/{notification_id}/resolve` → `_resolve_notification()`
    Body: `{"summary": str, "link": str | None, "resolved_by": str}`
- [x] All endpoints return JSON. Error responses: 404 (not found), 400 (invalid input).
- [x] The `EventDB` instance is stored on the API server (set during daemon startup).

### Task 4.2: WebSocket notification push

**File(s):** `teleclaude/api_server.py`

- [x] Add `notifications` as a subscribable topic in WebSocket handler
- [x] Define notification push callback (passed to pipeline as a push_callback):
  ```python
  async def _notification_push(notification_id: int, event_type: str,
                                was_created: bool, is_meaningful: bool) -> None:
      row = await self._event_db.get_notification(notification_id)
      payload = {
          "type": "notification_created" if was_created else "notification_updated",
          "notification": row,
      }
      self._schedule_refresh_broadcast(payload)  # existing broadcast mechanism
  ```
- [x] Filter: only push to clients subscribed to `notifications` topic

---

## Phase 5: Daemon Integration & First Producers

### Task 5.1: Daemon hosting

**File(s):** `teleclaude/daemon.py`

- [x] Import: `from teleclaude_events import EventDB, EventCatalog, EventProducer, EventProcessor, Pipeline`
- [x] Import cartridges: `from teleclaude_events.cartridges import DeduplicationCartridge, NotificationProjectorCartridge`
- [x] In `start()` (after existing background tasks):
  1. `self._event_db = EventDB()` → `await self._event_db.init()`
  2. `self._event_catalog = build_default_catalog()`
  3. `self._event_producer = EventProducer(redis_client=self._redis, stream="teleclaude:events")`
  4. Configure module-level producer in `teleclaude_events.producer`
  5. Build pipeline: `Pipeline([DeduplicationCartridge(), NotificationProjectorCartridge()], context)`
  6. `self._event_processor = EventProcessor(redis=self._redis, pipeline=pipeline, ...)`
  7. `self._event_processor_task = asyncio.create_task(self._event_processor.start(self.shutdown_event))`
  8. `self._event_processor_task.add_done_callback(self._log_background_task_exception("event_processor"))`
  9. Set `self._api_server._event_db = self._event_db` for API access
- [x] In shutdown: signal processor stop, await task, `await self._event_db.close()`

### Task 5.2: Wire first producers

**File(s):** `teleclaude/daemon.py`

- [x] After event processor is started, emit `system.daemon.restarted`:
  ```python
  await self._event_producer.emit(EventEnvelope(
      event="system.daemon.restarted",
      source="daemon",
      level=EventLevel.INFRASTRUCTURE,
      domain="system",
      visibility=EventVisibility.CLUSTER,
      description=f"Daemon restarted on {self.computer_name}",
      payload={"computer": self.computer_name, "pid": os.getpid()},
  ))
  ```
- [x] DOR event not wired (deferred — requires todo watcher changes beyond scope;
      `system.daemon.restarted` serves as the first producer demonstration)

### Task 5.3: Telegram delivery adapter

**File(s):** `teleclaude_events/delivery/__init__.py`, `teleclaude_events/delivery/telegram.py`,
`teleclaude/daemon.py`

- [x] Create `teleclaude_events/delivery/` package
- [x] Define `TelegramDeliveryAdapter`:
  - Constructor: `chat_id` (from config), `send_fn` (the actual telegram send function,
    injected to avoid importing from `teleclaude`)
  - `async def on_notification(self, notification_id, event_type, was_created, is_meaningful)`:
    If level >= WORKFLOW and was_created: format message and call `send_fn`
- [x] In daemon startup: if telegram configured, create adapter, add to push_callbacks
- [x] Copy `send_telegram_dm` function logic into the delivery adapter (or pass the existing
      function as `send_fn` before consolidation removes it)

### Task 5.4: Initial event catalog schemas

**File(s):** `teleclaude_events/schemas/__init__.py`, `teleclaude_events/schemas/system.py`,
`teleclaude_events/schemas/software_development.py`

- [x] `system.py`:
  - `system.daemon.restarted` — level: INFRASTRUCTURE, visibility: CLUSTER,
    idempotency: [computer, pid], lifecycle: creates notification
  - `system.worker.crashed` — level: OPERATIONAL, visibility: CLUSTER,
    idempotency: [worker_name, timestamp], lifecycle: creates notification, actionable: true
- [x] `software_development.py`:
  - `domain.software-development.planning.todo_created` — level: WORKFLOW, lifecycle: creates
  - `domain.software-development.planning.todo_dumped` — level: WORKFLOW, lifecycle: creates
  - `domain.software-development.planning.todo_activated` — level: WORKFLOW, lifecycle: creates
  - `domain.software-development.planning.artifact_changed` — level: OPERATIONAL, lifecycle: updates (silent)
  - `domain.software-development.planning.dependency_resolved` — level: WORKFLOW, lifecycle: updates (meaningful)
  - `domain.software-development.planning.dor_assessed` — level: WORKFLOW,
    lifecycle: creates/updates (meaningful on score change), actionable: true
  - `domain.software-development.build.completed` — level: WORKFLOW, lifecycle: resolves
  - `domain.software-development.review.verdict_ready` — level: WORKFLOW, lifecycle: updates (meaningful)
  - `domain.software-development.review.needs_decision` — level: BUSINESS, lifecycle: updates (meaningful), actionable: true
- [x] `__init__.py`: `register_all(catalog: EventCatalog)` that registers all schemas
- [x] Wire into `build_default_catalog()`

### Task 5.5: CLI command

**File(s):** `teleclaude/cli/` (new `events` subcommand)

- [x] `telec events list` — table output: event_type, level, domain, visibility, description, actionable
- [x] Uses `build_default_catalog()` to list schemas (no daemon connection needed)

---

## Phase 6: Consolidation

### Task 6.1: Remove old notification system

**File(s):** `teleclaude/notifications/` (entire directory), `teleclaude/daemon.py`,
`teleclaude/core/db.py`, `teleclaude/core/migrations/`

- [ ] Remove `teleclaude/notifications/` directory entirely
- [ ] Remove `notification_outbox_task` startup in daemon.py (~line 1857)
- [ ] Remove `NotificationOutboxWorker` and `NotificationRouter` imports
- [ ] Remove from `db.py`: `enqueue_notification`, `fetch_notification_batch`,
      `claim_notification`, `mark_notification_delivered`, `mark_notification_failed`
- [ ] Add migration (next sequence number) that drops `notification_outbox` table
- [ ] Audit call sites: grep for `enqueue_notification`, `NotificationRouter`, `notification_outbox`
      — rewire to `emit_event()` or remove if dead code
- [ ] Verify: `grep -r "notification_outbox\|NotificationRouter\|NotificationOutboxWorker" teleclaude/`
      returns nothing (except migration files)

---

## Phase 7: Tests

### Task 7.1: Unit tests

**File(s):** `tests/test_events/`

- [ ] `test_envelope.py`: serialization/deserialization, to_stream_dict/from_stream_dict round-trip,
      visibility enum, level enum
- [ ] `test_catalog.py`: register, get, list_all, build_idempotency_key, duplicate registration error
- [ ] `test_db.py`: init, insert, get, list with filters, upsert by idempotency key, state machine
      transitions (mark seen, claim, update status, resolve)
- [ ] `test_cartridges.py`: dedup drops duplicates, dedup passes non-duplicates, projector creates
      notification for lifecycle events, projector passes through non-lifecycle events
- [ ] `test_pipeline.py`: full chain — dedup → projector, event dropped by dedup never reaches projector

### Task 7.2: Integration test

- [ ] `test_integration.py`: producer → Redis Stream → processor → SQLite → API query.
      Requires running Redis (skip if unavailable). Emit event, wait for processor to handle,
      query API, verify response.

### Task 7.3: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify: `grep -r "from teleclaude\." teleclaude_events/` returns nothing
- [ ] Verify: old `teleclaude/notifications/` no longer exists
- [ ] Verify: no unchecked tasks remain

---

## Phase 8: Review Readiness

- [ ] Confirm all requirements reflected in code
- [ ] Confirm all tasks marked `[x]`
- [ ] Run `telec todo demo validate event-platform-core`
- [ ] Document any deferrals in `deferrals.md`
