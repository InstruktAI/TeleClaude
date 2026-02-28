# Implementation Plan: event-mesh-distribution

## Overview

Build in dependency order: cluster membership utilities first (pure logic), then the
mesh publishing cartridge (outbound), then ingress handler (inbound), then cartridge
schemas and sovereignty gate, then promotion tracking, then CLI, then daemon wiring,
then tests. Each phase is committable independently.

Codebase patterns to follow:

| Pattern                         | Evidence                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------- |
| Redis XADD to peer stream       | `teleclaude/transport/redis_transport.py:1731` — `xadd(f"messages:{computer}", data, maxlen=...)` |
| Peer discovery                  | `teleclaude/transport/redis_transport.py:826` — `discover_peers()` returns `list[PeerInfo]`       |
| Message dispatch (type routing) | `teleclaude/transport/redis_transport.py:976` — `messages:{computer}` stream poll loop            |
| Cartridge interface             | `teleclaude_events/pipeline.py` — `Cartridge` Protocol, `process(event, context)`                 |
| Pipeline context                | `teleclaude_events/pipeline.py` — `PipelineContext` dataclass                                     |
| Config extension pattern        | `teleclaude/config.py` — Pydantic config model                                                    |
| aiosqlite DB                    | `teleclaude_events/db.py` — WAL mode, `EventDB` class                                             |
| Daemon background task          | `teleclaude/daemon.py:1857` — `asyncio.create_task()` + done callback                             |

---

## Phase 1: Cluster & Peer Utilities

### Task 1.1: Mesh package scaffold and cluster utilities

**File(s):** `teleclaude_events/mesh/__init__.py`, `teleclaude_events/mesh/cluster.py`

- [ ] Create `teleclaude_events/mesh/` package with `__init__.py`
- [ ] Define `get_cluster_peers(transport: RedisTransport, local_cluster: str | None) -> list[PeerInfo]`:
  - Call `transport.discover_peers()`
  - Filter to peers where `peer.cluster == local_cluster` (field TBD from codebase audit)
  - Exclude own `transport.computer_name`
  - Return empty list if `local_cluster` is None (no cluster configured)
- [ ] Define `get_all_peers(transport: RedisTransport) -> list[PeerInfo]`:
  - Call `transport.discover_peers()`
  - Exclude own `transport.computer_name`
- [ ] Audit `PeerInfo` dataclass in `redis_transport.py` to confirm available fields;
      add `cluster` field if missing (or read from heartbeat key metadata)
- [ ] Verify: peer list never contains own computer name

### Task 1.2: Config extension for cluster and autonomy

**File(s):** `teleclaude/config.py` (or wherever `ComputerConfig` is defined)

- [ ] Audit existing config model for `computer.cluster` field; add if absent:
  ```python
  class ComputerConfig(BaseModel):
      cluster: str | None = None  # cluster affiliation identifier
  ```
- [ ] Add autonomy config section:
  ```python
  class AutonomyConfig(BaseModel):
      cartridge_install: Literal["L1", "L2", "L3"] = "L1"
  ```
- [ ] Wire `AutonomyConfig` into the root config model if not already present
- [ ] Verify: `config.computer.cluster` and `config.autonomy.cartridge_install` are readable

---

## Phase 2: Outbound — Mesh Publishing Cartridge

### Task 2.1: Mesh publishing cartridge

**File(s):** `teleclaude_events/cartridges/mesh_publisher.py`

- [ ] Define `MeshPublishingCartridge`:
  - Constructor: `transport: RedisTransport`, `local_cluster: str | None`,
    `stream_maxlen: int = 10000`
  - `name = "mesh-publisher"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. If `event.visibility == EventVisibility.LOCAL`: return event unchanged (no-op)
    2. If `event.visibility == EventVisibility.CLUSTER`:
       - `peers = await get_cluster_peers(self.transport, self.local_cluster)`
    3. If `event.visibility == EventVisibility.PUBLIC`:
       - `peers = await get_all_peers(self.transport)`
    4. For each peer:
       - Serialize event: `payload = event.model_dump_json()`
       - XADD `messages:{peer.name}` with `{"type": "mesh_event", "payload": payload,
"source_computer": transport.computer_name}`
    5. On `RedisError`: log warning, continue (degrade gracefully — do not drop event)
    6. Return event unchanged (forwarding is side-effect, not transformation)
- [ ] Handle case where `transport` is None or not connected: log warning, skip forwarding

---

## Phase 3: Inbound — Mesh Ingress

### Task 3.1: Trust stub

**File(s):** `teleclaude_events/mesh/trust_stub.py`

- [ ] Define `MeshTrustStub`:
  - Constructor: `known_cluster_peers: Callable[[], list[str]]` (list of peer computer names)
  - `async def evaluate(self, envelope: EventEnvelope, source_computer: str) -> bool`:
    - Returns `True` if `source_computer` is in known cluster peers
    - Returns `False` otherwise
  - Add `# TODO: replace with TrustEvaluatorCartridge from event-system-cartridges` comment
    at module level

### Task 3.2: Mesh ingress handler

**File(s):** `teleclaude_events/mesh/ingress.py`

- [ ] Define `MeshIngressHandler`:
  - Constructor: `processor: EventProcessor`, `trust: MeshTrustStub`,
    `local_producer: EventProducer`
  - `async def handle(self, raw_message: dict) -> None`:
    1. Check `raw_message.get("type") == "mesh_event"` — ignore if not
    2. Deserialize: `envelope = EventEnvelope.model_validate_json(raw_message["payload"])`
    3. Extract `source_computer = raw_message.get("source_computer", "unknown")`
    4. Stamp `envelope` with `source_computer` in payload (add `_mesh_source` key)
    5. Trust evaluation: `trusted = await self.trust.evaluate(envelope, source_computer)`
    6. If not trusted:
       - Emit local `mesh.event.rejected` via `local_producer`
       - Return (do not pass to pipeline)
    7. If trusted: submit envelope directly to pipeline via `processor.submit(envelope)`
       (add `submit()` method to `EventProcessor` for direct injection without Redis)
- [ ] Add `submit(envelope: EventEnvelope) -> None` to `EventProcessor` in
      `teleclaude_events/processor.py`: enqueues envelope directly into the processing queue,
      bypassing Redis Streams ingestion

---

## Phase 4: Cartridge Publishing & Sovereignty Gate

### Task 4.1: Cartridge event schemas

**File(s):** `teleclaude_events/schemas/cartridges.py`

- [ ] Define schemas and register with `EventCatalog`:
  - `cartridge.published`: level WORKFLOW, visibility PUBLIC,
    idempotency: `[author, event_type, version]`,
    lifecycle: creates notification, actionable: true
  - `cartridge.install_pending`: level WORKFLOW, visibility LOCAL,
    lifecycle: creates notification, actionable: true
  - `cartridge.install_notified`: level OPERATIONAL, visibility LOCAL,
    lifecycle: creates notification (informational)
  - `cartridge.installed`: level WORKFLOW, visibility LOCAL,
    lifecycle: creates notification
  - `cartridge.invoked`: level INFRASTRUCTURE, visibility LOCAL,
    no lifecycle (stats only)
  - `cartridge.promotion_suggested`: level WORKFLOW, visibility LOCAL,
    lifecycle: creates notification, actionable: true
  - `mesh.event.rejected`: level OPERATIONAL, visibility LOCAL,
    lifecycle: creates notification
- [ ] Add `register_cartridge_schemas(catalog: EventCatalog)` function
- [ ] Wire into `build_default_catalog()` in `teleclaude_events/catalog.py`

### Task 4.2: Cartridge stats DB table

**File(s):** `teleclaude_events/db.py`

- [ ] Add `cartridge_stats` table creation in `EventDB.init()`:
  ```sql
  CREATE TABLE IF NOT EXISTS cartridge_stats (
    cartridge_name TEXT PRIMARY KEY,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    last_invoked_at TEXT
  );
  ```
- [ ] Add methods:
  - `async increment_cartridge_invocation(name: str) -> int` — upsert, return new count
  - `async get_cartridge_stats(name: str) -> dict | None`
  - `async list_cartridge_stats() -> list[dict]`

### Task 4.3: Sovereignty-gated installer

**File(s):** `teleclaude_events/mesh/installer.py`

- [ ] Define `CartridgeInstaller`:
  - Constructor: `autonomy_level: str`, `install_dir: Path`,
    `producer: EventProducer`, `db: EventDB`
  - `async def on_cartridge_published(self, notification_id: int, event_type: str,
was_created: bool, is_meaningful: bool) -> None`:
    - Only act when `event_type == "cartridge.published"` and `was_created`
    - Fetch notification row from DB to get payload
    - Dispatch to `_handle_l1()`, `_handle_l2()`, or `_handle_l3()` based on autonomy level
  - `async def _handle_l1(self, payload: dict) -> None`:
    - Create actionable `cartridge.install_pending` notification via `emit_event()`
    - Write cartridge source to `install_dir/{name}.py` (pending, not active)
  - `async def _handle_l2(self, payload: dict) -> None`:
    - TODO stub: emit `cartridge.install_notified`, then call `_do_install()`
    - Guardian AI evaluation deferred to `event-domain-infrastructure`
  - `async def _handle_l3(self, payload: dict) -> None`:
    - `await self._do_install(payload)`
  - `async def _do_install(self, payload: dict) -> None`:
    - Decode base64 source, write to `install_dir/{name}.py`
    - Emit `cartridge.installed` event

---

## Phase 5: Promotion Tracking

### Task 5.1: Pipeline executor instrumentation

**File(s):** `teleclaude_events/pipeline.py`

- [ ] After each successful cartridge `process()` call (returns non-None), emit
      `cartridge.invoked` event:
  ```python
  await context.emit_event(
      event="cartridge.invoked",
      source="pipeline",
      level=EventLevel.INFRASTRUCTURE,
      domain="system",
      visibility=EventVisibility.LOCAL,
      payload={"cartridge_name": cartridge.name, "event_type": event.event},
  )
  ```
- [ ] Add `emit_event` callable to `PipelineContext`:
  ```python
  @dataclass
  class PipelineContext:
      ...
      emit_event: Callable[..., Awaitable[str]] | None = None
  ```
  (None in tests; wired to `EventProducer.emit_event` in daemon)

### Task 5.2: Promotion tracker cartridge

**File(s):** `teleclaude_events/mesh/promotion.py`

- [ ] Define `CartridgePromotionTracker`:
  - `name = "cartridge-promotion-tracker"`
  - Constructor: `threshold: int = 10`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. If `event.event != "cartridge.invoked"`: return event unchanged
    2. `cartridge_name = event.payload.get("cartridge_name")`
    3. `new_count = await context.db.increment_cartridge_invocation(cartridge_name)`
    4. If `new_count == self.threshold` (exactly, not >=):
       - Emit `cartridge.promotion_suggested` with payload `{"cartridge_name": cartridge_name,
"invocation_count": new_count}`
    5. Return event unchanged

---

## Phase 6: CLI

### Task 6.1: `telec cartridges` subcommand

**File(s):** `teleclaude/cli/` (new `cartridges.py` subcommand, registered in CLI router)

- [ ] `telec cartridges list`:
  - Query `EventDB.list_cartridge_stats()`
  - Also list files in `~/.teleclaude/cartridges/incoming/` as pending
  - Table output: `name`, `status` (pending/active), `invocation_count`, `last_invoked_at`
- [ ] `telec cartridges activate {name}`:
  - Move `~/.teleclaude/cartridges/incoming/{name}.py` to `~/.teleclaude/cartridges/{name}.py`
  - Emit `cartridge.installed` event confirming activation
  - Print confirmation
- [ ] `telec cartridges reject {name}`:
  - Delete `~/.teleclaude/cartridges/incoming/{name}.py`
  - Print confirmation

---

## Phase 7: Daemon Wiring

### Task 7.1: Wire mesh components into daemon

**File(s):** `teleclaude/daemon.py`

- [ ] Import new components:
  ```python
  from teleclaude_events.cartridges.mesh_publisher import MeshPublishingCartridge
  from teleclaude_events.mesh.ingress import MeshIngressHandler
  from teleclaude_events.mesh.trust_stub import MeshTrustStub
  from teleclaude_events.mesh.installer import CartridgeInstaller
  from teleclaude_events.mesh.promotion import CartridgePromotionTracker
  ```
- [ ] After existing pipeline setup (after `NotificationProjectorCartridge`), extend cartridge list:
  ```python
  cartridges = [
      DeduplicationCartridge(),
      NotificationProjectorCartridge(),
      MeshPublishingCartridge(transport=self._transport, local_cluster=config.computer.cluster),
      CartridgePromotionTracker(threshold=10),
  ]
  ```
- [ ] Create `MeshTrustStub` with peer list sourced from `get_cluster_peers()`
- [ ] Create `MeshIngressHandler(processor=self._event_processor, trust=trust_stub,
local_producer=self._event_producer)`
- [ ] Register `MeshIngressHandler.handle` as a message type handler in `RedisTransport`
      for `type: mesh_event` messages
- [ ] Create `CartridgeInstaller` and add `installer.on_cartridge_published` to
      `pipeline_context.push_callbacks`
- [ ] Emit `cartridge.invoked` support: wire `emit_event` into `PipelineContext`

---

## Phase 8: Tests & Quality

### Task 8.1: Unit tests

**File(s):** `tests/test_events/test_mesh/`

- [ ] `test_cluster.py`: `get_cluster_peers` filters by cluster, excludes self;
      `get_all_peers` excludes self; empty list when cluster is None
- [ ] `test_mesh_publisher.py`: local events not forwarded; cluster events forwarded to
      cluster peers only; public events forwarded to all peers; Redis error degrades gracefully
- [ ] `test_ingress.py`: trusted source events enter pipeline; unknown source events
      trigger `mesh.event.rejected`; non-mesh messages ignored
- [ ] `test_installer.py`: L1 creates pending notification, does not install; L3 installs
      immediately; base64 decode + file write
- [ ] `test_promotion.py`: invocation count increments; promotion event emitted at threshold
      exactly; non-invoked events pass through unchanged
- [ ] `test_cartridge_schemas.py`: all new schemas register without error; `build_default_catalog()`
      includes cartridge and mesh schemas

### Task 8.2: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify: no `cartridge.invoked` events have visibility other than `local`
- [ ] Verify: `MeshPublishingCartridge` never forwards to own computer
- [ ] Confirm all requirements reflected in code; all tasks marked `[x]`

---

## Phase 9: Review Readiness

- [ ] Confirm all requirements in `requirements.md` are addressed
- [ ] Confirm all tasks above marked `[x]`
- [ ] Run `telec todo demo validate event-mesh-distribution`
- [ ] Document any deferrals in `deferrals.md` (L2 guardian AI evaluation is a known deferral)
