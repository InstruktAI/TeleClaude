# Requirements: event-system-cartridges

## Goal

Extend the system pipeline (built in `event-platform-core`) with four intelligence cartridges:
trust evaluator, enrichment, correlation, and classification. These cartridges slot into the
pipeline runtime without changing it. After this phase, every event flowing through the system
pipeline is evaluated for trust, enriched with platform context, correlated against prior events,
and classified for downstream treatment before reaching the notification projector.

## Scope

### In scope

1. **Trust evaluator cartridge** (`teleclaude_events/cartridges/trust.py`):
   - Configurable strictness levels: `permissive`, `standard`, `strict`
   - Evaluates envelope fields: source, level, domain, payload shape
   - Outcomes: `accept`, `flag`, `quarantine`, `reject`
   - `reject`: return None (drop from pipeline — never reaches downstream cartridges)
   - `quarantine`: store to `quarantined_events` table, return None (held for review)
   - `flag`: annotate envelope metadata field `trust_flags: list[str]`, pass through
   - `accept`: pass through unchanged
   - Strictness configuration sourced from `PipelineContext` (e.g., per-domain override)
   - Default: `standard`
   - First cartridge in the chain (before dedup)

2. **Enrichment cartridge** (`teleclaude_events/cartridges/enrichment.py`):
   - Reads `event.entity` URI (e.g., `telec://todo/event-platform-core`)
   - Queries platform state for context about the referenced entity:
     - For `telec://todo/*`: recent DOR score, failure count, current phase from `events.db`
     - For `telec://worker/*`: last crash timestamp, crash count in rolling window
   - Appends enrichment to `event.payload` under key `_enrichment: dict`
   - No-op if `entity` is None or entity type is unrecognized
   - Runs after dedup (enrichment only happens for new events)

3. **Correlation cartridge** (`teleclaude_events/cartridges/correlation.py`):
   - Detects patterns across recent events in a sliding window (configurable: default 5 minutes)
   - **Burst detection**: N events of the same `event_type` within the window → emit a
     synthetic `system.burst.detected` event back into the pipeline via the producer
   - **Failure cascade detection**: N `system.worker.crashed` events within window →
     emit `system.failure_cascade.detected`
   - **Repeated entity failure**: same `entity` referenced in N failure events →
     emit `system.entity.degraded`
   - Synthetic events use `EventProducer` (injected via `PipelineContext`) to re-enter pipeline
   - Correlation state stored in `events.db` (`correlation_windows` table: event_type,
     entity, window_start, count)
   - Pruning: delete windows older than 2x the configured window duration
   - Runs after enrichment

4. **Classification cartridge** (`teleclaude_events/cartridges/classification.py`):
   - Reads `EventSchema.lifecycle` to determine treatment:
     - `lifecycle is not None` → `notification-worthy`
     - `schema.actionable is True` → also mark `actionable`
     - No lifecycle → `signal-only` (index entry, no notification)
   - Annotates envelope with `_classification: dict` under payload:
     ```python
     {"treatment": "notification-worthy" | "signal-only", "actionable": bool}
     ```
   - The notification projector downstream uses `_classification` to fast-path its lookup
     (avoids re-querying the catalog)
   - Runs after correlation, before notification projector

5. **Updated pipeline order**: `trust → dedup → enrichment → correlation → classification → projection`
   - `teleclaude/daemon.py` updated to construct the full 6-cartridge chain
   - `teleclaude_events/cartridges/__init__.py` exports all six cartridges

6. **Synthetic event schemas** for correlation outputs:
   - `system.burst.detected` — level: OPERATIONAL, lifecycle: creates
   - `system.failure_cascade.detected` — level: BUSINESS, lifecycle: creates, actionable: true
   - `system.entity.degraded` — level: WORKFLOW, lifecycle: creates/updates, actionable: true
   - Registered in `teleclaude_events/schemas/system.py`

7. **`quarantined_events` table** in `events.db`:
   - `id`, `event_type`, `source`, `received_at`, `envelope_json`, `trust_flags`, `reviewed` (bool)

8. **Correlation configuration** (dataclass in `teleclaude_events/cartridges/correlation.py`):
   - `CorrelationConfig`: `window_seconds: int = 300`, `burst_threshold: int = 10`,
     `crash_cascade_threshold: int = 3`, `entity_failure_threshold: int = 3`
   - Injected via `PipelineContext.correlation_config` (add field to context)

9. **Trust configuration** (dataclass in `teleclaude_events/cartridges/trust.py`):
   - `TrustConfig`: `strictness: Literal["permissive", "standard", "strict"] = "standard"`
   - Known sources (those registered in the daemon) always pass at `standard`
   - Unknown source + `strict` mode → quarantine
   - Injected via `PipelineContext.trust_config` (add field to context)

10. **Tests** for each cartridge in isolation and the full 6-cartridge integrated pipeline

### Out of scope

- Per-domain trust or enrichment configuration (→ `event-domain-infrastructure`)
- Domain-scoped cartridges loaded from filesystem (→ `event-domain-infrastructure`)
- Personal subscription pipeline (→ `event-domain-infrastructure`)
- Signal ingest, clustering, synthesis (→ `event-signal-pipeline`)
- Mesh distribution of flagged/quarantined events (→ `event-mesh-distribution`)
- Human review UI for quarantined events (deferred — table is written, review surface is not)
- AI-assisted trust evaluation (→ later; current trust is rule-based)

## Success Criteria

- [ ] Trust evaluator rejects events from unknown sources in `strict` mode (returns None)
- [ ] Trust evaluator quarantines events and writes to `quarantined_events` table
- [ ] Trust evaluator flags events and annotates payload `_trust_flags`; event reaches projector
- [ ] Enrichment cartridge appends `_enrichment` dict to payload when entity is recognized
- [ ] Enrichment cartridge is a no-op when entity is None
- [ ] Correlation cartridge emits `system.burst.detected` when burst threshold is crossed
- [ ] Correlation cartridge prunes stale windows from `events.db`
- [ ] Classification cartridge annotates `_classification` on all passing events
- [ ] Classification cartridge marks `actionable: true` for actionable schemas
- [ ] Full pipeline order is: trust → dedup → enrichment → correlation → classification → projection
- [ ] Event dropped by trust never reaches enrichment, correlation, classification, or projector
- [ ] Synthetic events from correlation re-enter pipeline and are processed end-to-end
- [ ] `make test` passes with coverage for all four new cartridges
- [ ] `make lint` passes
- [ ] `from teleclaude_events.cartridges import TrustCartridge, EnrichmentCartridge, CorrelationCartridge, ClassificationCartridge` works

## Constraints

- Zero changes to the pipeline runtime (`teleclaude_events/pipeline.py`) — cartridges slot in
  via the constructor list only
- Zero imports from `teleclaude.*` in `teleclaude_events/` — one-way dependency direction
- Async-first: all I/O async (aiosqlite, redis-py async)
- Correlation synthetic event emission uses the injected `EventProducer` — never a direct
  pipeline call (avoids recursion)
- `PipelineContext` may gain new fields (`trust_config`, `correlation_config`, `producer`) —
  all optional with defaults to keep existing tests passing

## Risks

- **Correlation re-entry loops**: a synthetic `system.burst.detected` event going through trust
  → could trigger another burst → infinite loop. Mitigate: synthetic events from the correlation
  cartridge are tagged with `source="correlation"`, and burst detection skips events with
  that source tag.
- **Enrichment latency**: querying `events.db` per event on the hot path. Mitigate: read-only
  queries with indexed lookups; enrichment skips entities with no history row.
- **PipelineContext extension**: adding fields to `PipelineContext` is a breaking change if
  callers use positional args. Verify all construction sites use keyword args and add defaults.
- **Test isolation for correlation**: window-based detection needs time control. Use injectable
  `clock` function in `CorrelationConfig` for test determinism.
