# Implementation Plan: event-system-cartridges

## Overview

Slot four intelligence cartridges into the existing system pipeline from `event-platform-core`.
No changes to the pipeline runtime — only new cartridge files, schema additions, a DB table,
`PipelineContext` field extensions, and updated pipeline construction in `daemon.py`.

Plan ordered for incremental testability: each cartridge is written and tested before the next.
Final phase wires them all together, updates the daemon, and verifies the integrated order.
Builder commits after each phase.

Codebase patterns to follow:

| Pattern                  | Evidence                                                                         |
| ------------------------ | -------------------------------------------------------------------------------- |
| Cartridge interface      | `teleclaude_events/cartridges/dedup.py` — `async def process(event, ctx)`        |
| PipelineContext          | `teleclaude_events/pipeline.py` — dataclass with catalog, db, push_callbacks     |
| EventDB aiosqlite        | `teleclaude_events/db.py` — WAL mode, async CRUD                                 |
| EventProducer emit       | `teleclaude_events/producer.py` — `await producer.emit(envelope)`                |
| EventCatalog lookup      | `teleclaude_events/catalog.py` — `catalog.get(event_type)`                       |
| Schema registration      | `teleclaude_events/schemas/system.py` — `EventSchema(...)` registered in catalog |
| Daemon pipeline assembly | `teleclaude/daemon.py` — `Pipeline([...cartridges...], context)`                 |

---

## Phase 1: Context Extensions & Trust Cartridge

### Task 1.1: Extend PipelineContext

**File(s):** `teleclaude_events/pipeline.py`

- [ ] Add `TrustConfig` import (created in 1.2)
- [ ] Add `CorrelationConfig` import (created in 3.1)
- [ ] Add optional fields to `PipelineContext` dataclass:
  ```python
  trust_config: TrustConfig = field(default_factory=TrustConfig)
  correlation_config: CorrelationConfig = field(default_factory=CorrelationConfig)
  producer: EventProducer | None = None   # required by correlation; optional for others
  ```
- [ ] Verify all existing `PipelineContext(...)` construction sites use keyword args (grep
      `teleclaude/daemon.py` and `tests/`). Fix any positional-arg callsites.

### Task 1.2: Implement trust cartridge

**File(s):** `teleclaude_events/cartridges/trust.py`

- [ ] Define `TrustConfig` dataclass:
  ```python
  @dataclass
  class TrustConfig:
      strictness: Literal["permissive", "standard", "strict"] = "standard"
      known_sources: frozenset[str] = field(default_factory=frozenset)
  ```
- [ ] Define `TrustOutcome` string enum: `ACCEPT`, `FLAG`, `QUARANTINE`, `REJECT`
- [ ] Define `TrustCartridge`:
  - `name = "trust"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. `config = context.trust_config`
    2. Evaluate: run `_evaluate(event, config) -> TrustOutcome`
    3. `ACCEPT`: return event unchanged
    4. `FLAG`: set `event.payload["_trust_flags"] = [...]`, return event
    5. `QUARANTINE`: `await context.db.quarantine_event(event, flags)`, return None
    6. `REJECT`: return None (log at WARNING level)
  - `def _evaluate(self, event, config) -> tuple[TrustOutcome, list[str]]`:
    - `permissive`: always ACCEPT
    - `standard`: unknown source → FLAG with `["unknown_source"]`; malformed level → QUARANTINE
    - `strict`: unknown source → QUARANTINE with `["unknown_source"]`; missing domain on
      non-system event → FLAG with `["missing_domain"]`; unknown level → REJECT
    - Source is "known" if `event.source in config.known_sources`

### Task 1.3: Add quarantine table to EventDB

**File(s):** `teleclaude_events/db.py`

- [ ] Add `quarantined_events` table creation in `EventDB.init()`:
  ```sql
  CREATE TABLE IF NOT EXISTS quarantined_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    trust_flags TEXT NOT NULL DEFAULT '[]',
    reviewed INTEGER NOT NULL DEFAULT 0
  );
  ```
- [ ] Add index: `(reviewed, received_at DESC)`
- [ ] Implement `async quarantine_event(self, envelope: EventEnvelope, flags: list[str]) -> int`:
      INSERT and return rowid
- [ ] Implement `async list_quarantined(reviewed: bool | None = None, limit: int = 50) -> list[dict]`

---

## Phase 2: Enrichment Cartridge

### Task 2.1: Implement enrichment cartridge

**File(s):** `teleclaude_events/cartridges/enrichment.py`

- [ ] Define `EnrichmentCartridge`:
  - `name = "enrichment"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. If `event.entity` is None: return event (no-op)
    2. Parse entity URI: `telec://{type}/{id}`
    3. Dispatch to entity-type handler (returns `dict | None`)
    4. If enrichment is not None: `event.payload["_enrichment"] = enrichment`
    5. Return event
  - `async def _enrich_todo(self, entity_id: str, db: EventDB) -> dict | None`:
    Query `notifications` table for events with `entity = "telec://todo/{entity_id}"`:
    - `failure_count`: count of `domain.software-development.build.completed` events where
      payload contains `success: false` for this entity
    - `last_dor_score`: most recent payload `score` from `dor_assessed` events for this entity
    - `current_phase`: payload `phase` from most recent `todo_activated` event
      Return None if no history rows found (avoids polluting new-entity events)
  - `async def _enrich_worker(self, entity_id: str, db: EventDB) -> dict | None`:
    - `crash_count`: count of `system.worker.crashed` events in last 24h for this entity
    - `last_crash_at`: timestamp of most recent crash event
      Return None if no crash history

### Task 2.2: Add enrichment query helpers to EventDB

**File(s):** `teleclaude_events/db.py`

- [ ] Add `async count_events_by_entity(entity: str, event_type: str, since: datetime | None = None) -> int`
- [ ] Add `async get_latest_event_payload(entity: str, event_type: str) -> dict | None`
      — returns payload dict of the most recent matching notification row, or None

---

## Phase 3: Correlation Cartridge

### Task 3.1: Implement correlation cartridge

**File(s):** `teleclaude_events/cartridges/correlation.py`

- [ ] Define `CorrelationConfig` dataclass:
  ```python
  @dataclass
  class CorrelationConfig:
      window_seconds: int = 300
      burst_threshold: int = 10
      crash_cascade_threshold: int = 3
      entity_failure_threshold: int = 3
      clock: Callable[[], datetime] = field(default_factory=lambda: datetime.utcnow)
  ```
- [ ] Define `CorrelationCartridge`:
  - `name = "correlation"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. If `event.source == "correlation"`: return event (skip — prevents re-entry loops)
    2. `config = context.correlation_config`
    3. `now = config.clock()`
    4. Prune stale windows: `await context.db.prune_correlation_windows(older_than=now - 2*window)`
    5. Record event: `await context.db.increment_correlation_window(event.event, event.entity, now)`
    6. Count for burst: `count = await context.db.get_correlation_count(event.event, None, window_start)`
    7. If `count >= burst_threshold`: emit `system.burst.detected` via `context.producer`
    8. If `event.event == "system.worker.crashed"`:
       count crashes in window; if `>= crash_cascade_threshold`: emit `system.failure_cascade.detected`
    9. If entity is not None and event type is a failure type:
       count entity failures in window; if `>= entity_failure_threshold`: emit `system.entity.degraded`
    10. Return event (correlation never drops events)
  - `async def _emit_synthetic(self, event_type, payload, context) -> None`:
    Build `EventEnvelope(event=event_type, source="correlation", ...)` and call
    `await context.producer.emit(envelope)`; guard: if `context.producer is None`, log WARNING and skip

### Task 3.2: Add correlation window table to EventDB

**File(s):** `teleclaude_events/db.py`

- [ ] Add `correlation_windows` table in `EventDB.init()`:
  ```sql
  CREATE TABLE IF NOT EXISTS correlation_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity TEXT,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1
  );
  ```
- [ ] Add index: `(event_type, entity, window_start)`
- [ ] Implement `async increment_correlation_window(event_type: str, entity: str | None, ts: datetime) -> None`:
      INSERT or update (upsert by event_type + entity + window_start bucket)
      Window bucket = floor(ts to window_seconds granularity)
- [ ] Implement `async get_correlation_count(event_type: str, entity: str | None, since: datetime) -> int`
- [ ] Implement `async prune_correlation_windows(older_than: datetime) -> None`

---

## Phase 4: Classification Cartridge

### Task 4.1: Implement classification cartridge

**File(s):** `teleclaude_events/cartridges/classification.py`

- [ ] Define `ClassificationCartridge`:
  - `name = "classification"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. `schema = context.catalog.get(event.event)`
    2. If schema is None:
       - treatment = `"signal-only"`, actionable = False (unknown type → no lifecycle)
    3. Else:
       - treatment = `"notification-worthy"` if `schema.lifecycle is not None` else `"signal-only"`
       - actionable = `schema.actionable`
    4. `event.payload["_classification"] = {"treatment": treatment, "actionable": actionable}`
    5. Return event
  - Always passes through (never drops events)

---

## Phase 5: Schema Additions & Pipeline Wiring

### Task 5.1: Register synthetic event schemas

**File(s):** `teleclaude_events/schemas/system.py`

- [ ] Add `system.burst.detected`:
  - `level: OPERATIONAL`, `domain: "system"`, `visibility: LOCAL`
  - `idempotency_fields: ["event_type", "window_start"]`
  - `lifecycle: NotificationLifecycle(creates=True)`
  - `actionable: False`
  - Payload shape (documented in description): `event_type: str, window_start: str, count: int`
- [ ] Add `system.failure_cascade.detected`:
  - `level: BUSINESS`, `domain: "system"`, `visibility: CLUSTER`
  - `idempotency_fields: ["window_start"]`
  - `lifecycle: NotificationLifecycle(creates=True)`
  - `actionable: True`
  - Payload shape: `crash_count: int, window_start: str, workers: list[str]`
- [ ] Add `system.entity.degraded`:
  - `level: WORKFLOW`, `domain: "system"`, `visibility: LOCAL`
  - `idempotency_fields: ["entity"]`
  - `lifecycle: NotificationLifecycle(creates=True, updates=True, group_key="entity", meaningful_fields=["failure_count"])`
  - `actionable: True`
  - Payload shape: `entity: str, failure_count: int, window_start: str`

### Task 5.2: Wire full pipeline in daemon

**File(s):** `teleclaude/daemon.py`

- [ ] Import new cartridges:
  ```python
  from teleclaude_events.cartridges import (
      TrustCartridge, DeduplicationCartridge, EnrichmentCartridge,
      CorrelationCartridge, ClassificationCartridge, NotificationProjectorCartridge,
  )
  from teleclaude_events.cartridges.trust import TrustConfig
  from teleclaude_events.cartridges.correlation import CorrelationConfig
  ```
- [ ] Build `TrustConfig` with known sources from daemon config (e.g., `frozenset({"daemon", "prepare-worker", "review-worker", "correlation"})`)
- [ ] Pass `trust_config`, `correlation_config`, and `producer=self._event_producer` when
      constructing `PipelineContext`
- [ ] Construct pipeline with 6-cartridge chain:
  ```python
  Pipeline([
      TrustCartridge(),
      DeduplicationCartridge(),
      EnrichmentCartridge(),
      CorrelationCartridge(),
      ClassificationCartridge(),
      NotificationProjectorCartridge(),
  ], context)
  ```

### Task 5.3: Update cartridges package exports

**File(s):** `teleclaude_events/cartridges/__init__.py`

- [ ] Export all six cartridges:
  ```python
  from teleclaude_events.cartridges.trust import TrustCartridge
  from teleclaude_events.cartridges.dedup import DeduplicationCartridge
  from teleclaude_events.cartridges.enrichment import EnrichmentCartridge
  from teleclaude_events.cartridges.correlation import CorrelationCartridge
  from teleclaude_events.cartridges.classification import ClassificationCartridge
  from teleclaude_events.cartridges.notification import NotificationProjectorCartridge
  ```

---

## Phase 6: Tests

### Task 6.1: Unit tests — trust cartridge

**File(s):** `tests/test_events/test_cartridge_trust.py`

- [ ] `test_known_source_accepted`: source in known_sources → ACCEPT, payload unchanged
- [ ] `test_unknown_source_standard_flagged`: unknown source + standard → FLAG, `_trust_flags` in payload
- [ ] `test_unknown_source_strict_quarantined`: unknown source + strict → quarantine row written, returns None
- [ ] `test_reject_unknown_level_strict`: unknown level value + strict → returns None (REJECT)
- [ ] `test_permissive_accepts_all`: permissive mode → all events pass through regardless of source
- [ ] `test_quarantine_writes_db_row`: verify `quarantined_events` row created on QUARANTINE outcome

### Task 6.2: Unit tests — enrichment cartridge

**File(s):** `tests/test_events/test_cartridge_enrichment.py`

- [ ] `test_no_entity_passthrough`: event with no entity → no `_enrichment` key, returned unchanged
- [ ] `test_unknown_entity_type_passthrough`: unrecognized URI scheme → no-op
- [ ] `test_todo_entity_enriched`: todo entity with crash history → `_enrichment` dict present in payload
- [ ] `test_todo_no_history_no_enrichment`: todo entity with zero DB rows → no `_enrichment` key
- [ ] `test_worker_entity_enriched`: worker entity with crash rows → `crash_count`, `last_crash_at` present

### Task 6.3: Unit tests — correlation cartridge

**File(s):** `tests/test_events/test_cartridge_correlation.py`

- [ ] `test_passes_all_events_through`: correlation never returns None
- [ ] `test_burst_detected_emits_synthetic`: N same-type events in window → producer receives burst event
- [ ] `test_burst_below_threshold_no_emit`: N-1 events → no synthetic event emitted
- [ ] `test_correlation_source_skipped`: event with `source="correlation"` → no window increment, no loops
- [ ] `test_cascade_detected`: N `system.worker.crashed` in window → `system.failure_cascade.detected` emitted
- [ ] `test_entity_degraded`: N failure events for same entity in window → `system.entity.degraded` emitted
- [ ] `test_stale_window_pruned`: prune_correlation_windows called; old rows removed from DB
- [ ] `test_no_producer_logs_warning`: producer=None, burst crossed → logs WARNING, does not raise

### Task 6.4: Unit tests — classification cartridge

**File(s):** `tests/test_events/test_cartridge_classification.py`

- [ ] `test_known_lifecycle_schema_notification_worthy`: schema with lifecycle → treatment=notification-worthy
- [ ] `test_actionable_schema_flagged`: actionable schema → `_classification.actionable = True`
- [ ] `test_no_lifecycle_schema_signal_only`: schema without lifecycle → treatment=signal-only
- [ ] `test_unknown_event_type_signal_only`: no schema registered → treatment=signal-only, no raise
- [ ] `test_classification_appended_to_payload`: `_classification` key exists after processing

### Task 6.5: Integration test — full 6-cartridge pipeline

**File(s):** `tests/test_events/test_pipeline_integration.py`

- [ ] `test_pipeline_order_trust_drops_before_dedup`: event rejected by trust never increments dedup check
- [ ] `test_pipeline_order_dedup_drops_before_enrichment`: duplicate event never enriched
- [ ] `test_pipeline_full_pass`: clean event flows through all 6 cartridges, ends with `_classification` in payload
- [ ] `test_pipeline_synthetic_event_reenters`: correlation emits synthetic; synthetic re-runs through pipeline
      (use mock producer that captures emitted envelopes)
- [ ] `test_notification_projector_uses_classification`: projector skips catalog lookup if `_classification` present

---

## Phase 7: Quality & Review Readiness

### Task 7.1: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify: `grep -r "from teleclaude\." teleclaude_events/` returns nothing
- [ ] Verify: `from teleclaude_events.cartridges import TrustCartridge, EnrichmentCartridge, CorrelationCartridge, ClassificationCartridge` succeeds
- [ ] Verify: all cartridge unit tests pass in isolation (no daemon startup required)

### Task 7.2: Review readiness

- [ ] Confirm all requirements reflected in code changes
- [ ] Confirm all tasks marked `[x]`
- [ ] Run `telec todo demo validate event-system-cartridges`
- [ ] Document any deferrals in `deferrals.md`
