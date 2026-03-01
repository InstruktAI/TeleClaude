# Implementation Plan: event-signal-pipeline

## Overview

Build three utility cartridges — ingest, cluster, synthesize — as the first cartridges
under `company/cartridges/`. Each stage is independently testable and emits a signal
taxonomy event. Ordering: schema first, then storage, then ingest, then cluster, then
synthesize, then wiring + config, then tests. Builder commits after each phase.

Dependencies to verify before starting:

- `teleclaude_events/` package exists (`event-platform-core` delivered)
- `PipelineContext` is extensible with an AI client (`event-domain-infrastructure` delivered)
- `company/cartridges/` loader is operational

Codebase patterns to follow:

| Pattern                 | Evidence                                                        |
| ----------------------- | --------------------------------------------------------------- |
| Cartridge interface     | `teleclaude_events/pipeline.py` — `Cartridge` Protocol          |
| PipelineContext         | `teleclaude_events/pipeline.py` — `PipelineContext` dataclass   |
| EventEnvelope           | `teleclaude_events/envelope.py` — five-layer Pydantic model     |
| EventCatalog / schemas  | `teleclaude_events/schemas/` — `EventSchema` + `register_all()` |
| aiosqlite storage       | `teleclaude_events/db.py` — `EventDB` init/WAL pattern          |
| Background task hosting | `teleclaude/daemon.py` — `asyncio.create_task` + done callback  |
| Idempotency key         | `teleclaude_events/catalog.py` — `build_idempotency_key()`      |

---

## Phase 1: Signal Schema & Package Structure

### Task 1.1: Create package scaffolding

**File(s):** `company/cartridges/__init__.py`, `company/cartridges/signal/__init__.py`,
`teleclaude_events/signal/__init__.py`

- [ ] Create `company/` at monorepo root with `__init__.py` if not already present
- [ ] Create `company/cartridges/__init__.py` (empty — loader discovers submodules)
- [ ] Create `company/cartridges/signal/__init__.py` with public exports:
  ```python
  from .ingest import SignalIngestCartridge
  from .cluster import SignalClusterCartridge
  from .synthesize import SignalSynthesizeCartridge
  ```
- [ ] Create `teleclaude_events/signal/__init__.py` (shared models used by all three cartridges)
- [ ] Verify: `python -c "from company.cartridges.signal import SignalIngestCartridge"` succeeds
      after stubs are in place

### Task 1.2: Define signal taxonomy event schemas

**File(s):** `teleclaude_events/schemas/signal.py`

- [ ] Define `signal.ingest.received` schema:
  ```python
  EventSchema(
      event_type="signal.ingest.received",
      description="A single feed item was ingested and normalised.",
      default_level=EventLevel.OPERATIONAL,
      domain="signal",
      default_visibility=EventVisibility.LOCAL,
      idempotency_fields=["source_id", "item_url"],
      lifecycle=None,  # not notification-worthy; feeds cluster cartridge
      actionable=False,
  )
  ```
- [ ] Define `signal.cluster.formed` schema:
  ```python
  EventSchema(
      event_type="signal.cluster.formed",
      description="A group of related ingested signals formed a cluster.",
      default_level=EventLevel.OPERATIONAL,
      domain="signal",
      default_visibility=EventVisibility.LOCAL,
      idempotency_fields=["cluster_id"],
      lifecycle=None,
      actionable=False,
  )
  ```
- [ ] Define `signal.synthesis.ready` schema:
  ```python
  EventSchema(
      event_type="signal.synthesis.ready",
      description="A cluster has been synthesised into a structured artifact.",
      default_level=EventLevel.WORKFLOW,
      domain="signal",
      default_visibility=EventVisibility.LOCAL,
      idempotency_fields=["cluster_id"],
      lifecycle=NotificationLifecycle(
          creates=True,
          meaningful_fields=["synthesis"],
      ),
      actionable=True,
  )
  ```
- [ ] Wire into `teleclaude_events/schemas/__init__.py` → `register_all()`
- [ ] Verify: `telec events list` shows all three signal event types

---

## Phase 2: Source Configuration

### Task 2.1: Source model and loaders

**File(s):** `teleclaude_events/signal/sources.py`

- [ ] Define `SourceType` string enum: `RSS`, `OPML`, `CSV`, `YOUTUBE`, `TWITTER`
- [ ] Define `SourceConfig` Pydantic model:
  ```python
  class SourceConfig(BaseModel):
      type: SourceType
      label: str = ""
      url: str | None = None       # RSS, YOUTUBE, TWITTER
      path: str | None = None      # OPML, CSV file reference
  ```
- [ ] Define `SignalSourceConfig` Pydantic model (top-level cartridge config):
  ```python
  class SignalSourceConfig(BaseModel):
      sources: list[SourceConfig] = []
      pull_interval_seconds: int = 900   # 15 min default
      max_items_per_pull: int = 50
      ai_concurrency: int = 5
  ```
- [ ] Implement `load_sources(config: SignalSourceConfig) -> list[SourceConfig]`:
  - For inline `sources`: return as-is
  - For OPML file reference: parse XML, extract `<outline xmlUrl="...">` entries,
    return as `SourceConfig(type=RSS, url=..., label=text_attr)`
  - For CSV file reference: read rows as `[label, url, type]`, return list
- [ ] Validate: paths are expanded (`~`), files exist at init time
- [ ] Unit test: load from inline list, from OPML string, from CSV string

### Task 2.2: HTTP fetch utility

**File(s):** `teleclaude_events/signal/fetch.py`

- [ ] Define `FetchResult` dataclass: `url`, `status`, `content_type`, `body: str | None`,
      `error: str | None`
- [ ] Implement `async fetch_url(url: str, timeout: int = 10) -> FetchResult`:
  - aiohttp GET with timeout; return body as text on 200, error string otherwise
- [ ] Implement `async fetch_full_content(url: str, max_chars: int = 8000) -> str | None`:
  - Fetch HTML, strip tags (regex or html.parser), truncate to `max_chars`
  - Returns None on error; caller treats None as unavailable
- [ ] Implement `parse_rss_feed(xml: str) -> list[dict]`:
  - Uses `xml.etree.ElementTree` (stdlib)
  - Returns list of `{title, url, published, description}` dicts
  - Handles both RSS 2.0 and Atom formats
- [ ] Unit tests with fixture XML strings

---

## Phase 3: Signal Ingest Cartridge

### Task 3.1: AI enrichment helper

**File(s):** `teleclaude_events/signal/ai.py`

- [ ] Define `SignalAIClient` protocol:
  ```python
  class SignalAIClient(Protocol):
      async def summarise(self, title: str, body: str) -> str: ...
      async def extract_tags(self, title: str, summary: str) -> list[str]: ...
      async def embed(self, text: str) -> list[float]: ...
      async def synthesise_cluster(self, items: list[dict]) -> SynthesisArtifact: ...
  ```
- [ ] Define `SynthesisArtifact` Pydantic model:
  ```python
  class SynthesisArtifact(BaseModel):
      summary: str
      key_points: list[str]
      sources: list[str]           # canonical URLs
      confidence: float            # 0.0–1.0
      recommended_action: str | None = None
  ```
- [ ] Implement `DefaultSignalAIClient(ai_client)` that wraps `PipelineContext.ai_client`:
  - `summarise`: single-sentence summary prompt (< 20 words)
  - `extract_tags`: return 3–7 lowercase hyphenated tags
  - `embed`: delegate to embedding endpoint; return float list
  - `synthesise_cluster`: structured synthesis prompt with JSON output mode

### Task 3.2: Ingest cartridge

**File(s):** `company/cartridges/signal/ingest.py`

- [ ] Define `SignalIngestCartridge`:
  - Constructor: `config: SignalSourceConfig`, `ai: SignalAIClient`
  - `name = "signal-ingest"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    - Only acts on a synthetic `signal.pull.triggered` scheduler event (or on startup trigger)
    - For each source: fetch feed, parse items, filter already-seen by idempotency key lookup
    - For each new item (up to `max_items_per_pull`): run AI enrichment concurrently
      (asyncio.gather with semaphore at `ai_concurrency`)
    - Emit one `signal.ingest.received` envelope per new item via `context.emit()`
      (store to signal_items table, then emit; cartridge returns None — the trigger is consumed)
    - Returns None (pull trigger event is consumed, not forwarded)
  - `async def pull(self, context: PipelineContext) -> int`: explicit pull call, returns
    item count ingested; used by scheduler and tests
- [ ] `signal.ingest.received` envelope fields:
  - `event`: `"signal.ingest.received"`
  - `source`: cartridge label
  - `description`: AI one-line summary
  - `payload`:
    ```json
    {
      "source_id": "<label>",
      "item_url": "<url>",
      "raw_title": "<title>",
      "tags": ["tag1", "tag2"],
      "published_at": "<ISO8601>",
      "fetched_at": "<ISO8601>"
    }
    ```
  - `idempotency_key`: built from `[source_id, item_url]` via catalog
- [ ] On duplicate idempotency key: skip item silently (do not emit)

### Task 3.3: Ingest scheduler

**File(s):** `teleclaude_events/signal/scheduler.py`

- [ ] Define `IngestScheduler`:
  - Constructor: `cartridge: SignalIngestCartridge`, `interval_seconds: int`
  - `async def run(self, shutdown_event: asyncio.Event) -> None`:
    Loop: sleep interval, call `cartridge.pull(context)`, repeat until shutdown
  - Hosting: started as a daemon background task alongside the pipeline processor
    (wired in Phase 6)

---

## Phase 4: Signal Cluster Cartridge

### Task 4.1: Cluster storage

**File(s):** `teleclaude_events/signal/db.py`

- [ ] Define `SignalDB` class (or extend `EventDB`):
  - `signal_items` table:
    ```sql
    CREATE TABLE IF NOT EXISTS signal_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      idempotency_key TEXT UNIQUE NOT NULL,
      source_id TEXT NOT NULL,
      item_url TEXT NOT NULL,
      raw_title TEXT,
      summary TEXT,
      tags TEXT,          -- comma-separated
      embedding TEXT,     -- JSON float array, nullable
      fetched_at TEXT NOT NULL,
      cluster_id INTEGER,
      FOREIGN KEY (cluster_id) REFERENCES signal_clusters(id)
    );
    ```
  - `signal_clusters` table:
    ```sql
    CREATE TABLE IF NOT EXISTS signal_clusters (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cluster_key TEXT UNIQUE NOT NULL,  -- hash of member idempotency keys
      tags TEXT,                          -- union tags
      is_burst INTEGER NOT NULL DEFAULT 0,
      is_novel INTEGER NOT NULL DEFAULT 0,
      summary TEXT,
      member_count INTEGER NOT NULL DEFAULT 0,
      formed_at TEXT NOT NULL
    );
    ```
  - `signal_syntheses` table:
    ```sql
    CREATE TABLE IF NOT EXISTS signal_syntheses (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cluster_id INTEGER NOT NULL,
      artifact TEXT NOT NULL,   -- JSON SynthesisArtifact
      produced_at TEXT NOT NULL,
      FOREIGN KEY (cluster_id) REFERENCES signal_clusters(id)
    );
    ```
  - CRUD methods:
    - `async insert_signal_item(payload: dict) -> int`
    - `async get_unclustered_items(since: datetime, limit: int) -> list[dict]`
    - `async insert_cluster(tags, is_burst, is_novel, summary, member_ids) -> int`
    - `async assign_items_to_cluster(item_ids: list[int], cluster_id: int) -> None`
    - `async get_cluster(cluster_id: int) -> dict | None`
    - `async insert_synthesis(cluster_id: int, artifact: dict) -> int`
    - `async get_recent_cluster_tags(hours: int = 24) -> list[str]`

### Task 4.2: Cluster algorithm

**File(s):** `teleclaude_events/signal/clustering.py`

- [ ] Define `ClusteringConfig` Pydantic model:
  ```python
  class ClusteringConfig(BaseModel):
      window_seconds: int = 900         # 15 min
      min_cluster_size: int = 2
      burst_threshold: int = 5          # items in window to flag burst
      novelty_overlap_hours: int = 24   # look-back for novelty detection
      tag_overlap_min: int = 1          # minimum shared tags to consider grouping
      embedding_similarity_threshold: float = 0.80  # cosine sim threshold
      singleton_promote_after_seconds: int = 3600
  ```
- [ ] Implement `group_by_tags(items: list[dict]) -> list[list[dict]]`:
  - Build tag→items inverted index
  - Union-find / greedy grouping: two items share a group if they share >= `tag_overlap_min` tags
  - Returns list of groups (each group is a list of item dicts)
- [ ] Implement `refine_by_embeddings(group: list[dict], threshold: float) -> list[list[dict]]`:
  - Compute pairwise cosine similarity on `item["embedding"]` float arrays
  - Split group if similarity < threshold (hierarchical single-linkage)
  - Falls back to tag-only grouping if embeddings are None (degraded mode)
- [ ] Implement `detect_burst(group: list[dict], threshold: int) -> bool`:
  - True if `len(group) >= threshold`
- [ ] Implement `detect_novelty(group_tags: list[str], recent_tags: list[str]) -> bool`:
  - True if overlap between group_tags and recent_tags is zero
- [ ] Implement `build_cluster_key(item_ids: list[int]) -> str`:
  - SHA-256 of sorted joined item idempotency keys → hex[:16]

### Task 4.3: Cluster cartridge

**File(s):** `company/cartridges/signal/cluster.py`

- [ ] Define `SignalClusterCartridge`:
  - Constructor: `config: ClusteringConfig`, `ai: SignalAIClient`, `signal_db: SignalDB`
  - `name = "signal-cluster"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    - Triggers on `signal.ingest.received` events
    - Accumulates received items; runs clustering pass when window expires or batch threshold hit
    - Clustering pass: `get_unclustered_items()`, group by tags, refine by embeddings,
      detect burst + novelty, AI-generate cluster summary
    - For each formed cluster: `insert_cluster()`, `assign_items_to_cluster()`,
      emit `signal.cluster.formed` via `context.emit()`
    - Returns the original `signal.ingest.received` event unchanged (pass-through)
  - `async def cluster_pass(self, context: PipelineContext) -> int`:
    Explicit trigger; returns cluster count formed. Used by scheduler and tests.
- [ ] `signal.cluster.formed` envelope fields:
  - `payload`:
    ```json
    {
      "cluster_id": 42,
      "member_count": 7,
      "tags": ["ai-safety", "regulation"],
      "is_burst": true,
      "is_novel": false,
      "summary": "Three outlets report new EU AI regulation draft."
    }
    ```

---

## Phase 5: Signal Synthesize Cartridge

### Task 5.1: Synthesize cartridge

**File(s):** `company/cartridges/signal/synthesize.py`

- [ ] Define `SynthesizeConfig` Pydantic model:
  ```python
  class SynthesizeConfig(BaseModel):
      max_items_per_cluster: int = 10
      max_content_chars_per_item: int = 8000
      fetch_full_content: bool = True
  ```
- [ ] Define `SignalSynthesizeCartridge`:
  - Constructor: `config: SynthesizeConfig`, `ai: SignalAIClient`, `signal_db: SignalDB`
  - `name = "signal-synthesize"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    - Only acts on `signal.cluster.formed` events; passes all others through unchanged
    - Extract `cluster_id` from `event.payload`
    - Fetch cluster members from `signal_db` (up to `max_items_per_cluster`)
    - Optionally fetch full page content for each member URL (capped at `max_content_chars`)
    - Cross-source dedup: remove items with near-identical summaries (>90% overlap heuristic)
    - Call `ai.synthesise_cluster(items)` → `SynthesisArtifact`
    - `signal_db.insert_synthesis(cluster_id, artifact.model_dump())`
    - Return new `EventEnvelope` with `event="signal.synthesis.ready"` and `payload.synthesis`
      set to the serialised artifact, `payload.cluster_id` set
- [ ] `signal.synthesis.ready` envelope fields:
  - `description`: `artifact.summary` (first 200 chars)
  - `payload`:
    ```json
    {
      "cluster_id": 42,
      "synthesis": {
        "summary": "...",
        "key_points": ["...", "..."],
        "sources": ["https://..."],
        "confidence": 0.87,
        "recommended_action": null
      }
    }
    ```

---

## Phase 6: Wiring & Configuration

### Task 6.1: Extend PipelineContext with AI client

**File(s):** `teleclaude_events/pipeline.py`

- [ ] Add `ai_client: SignalAIClient | None = None` field to `PipelineContext` dataclass
- [ ] Add `emit: Callable[[EventEnvelope], Awaitable[None]] | None = None` field to
      `PipelineContext` (for cartridges that need to emit new events mid-pipeline)
- [ ] Verify existing cartridges (dedup, notification projector) are unaffected by new fields

### Task 6.2: SignalDB integration into EventDB

**File(s):** `teleclaude_events/db.py`, `teleclaude_events/signal/db.py`

- [ ] Decide: extend `EventDB` with signal tables or keep `SignalDB` as a mixin/wrapper
- [ ] Ensure `signal_items`, `signal_clusters`, `signal_syntheses` tables are created on
      `EventDB.init()` alongside existing notification tables
- [ ] Expose `SignalDB` methods through a `db.signal` namespace or directly on `EventDB`
- [ ] WAL mode applies (inherited from `EventDB`)

### Task 6.3: Daemon wiring

**File(s):** `teleclaude/daemon.py`

- [ ] Import `SignalIngestCartridge`, `SignalClusterCartridge`, `SignalSynthesizeCartridge`
      from `company.cartridges.signal`
- [ ] Import `IngestScheduler` from `teleclaude_events.signal.scheduler`
- [ ] Import `DefaultSignalAIClient` from `teleclaude_events.signal.ai`
- [ ] In daemon startup (after event processor ready):
  1. Build `SignalSourceConfig` from daemon config (read `config.signal.sources` section)
  2. Instantiate `DefaultSignalAIClient(self._ai_client)`
  3. Instantiate `SignalDB` (or extend `EventDB`)
  4. Instantiate the three signal cartridges
  5. Register directly with `Pipeline(cartridges=[..., ingest, cluster, synthesize], context=...)`
     (domain-infrastructure loader integration deferred — when it ships, registration migrates
     to its discovery mechanism)
  6. Start `IngestScheduler` as a background task:
     ```python
     self._ingest_scheduler_task = asyncio.create_task(
         IngestScheduler(ingest_cartridge, config.pull_interval_seconds).run(self.shutdown_event)
     )
     self._ingest_scheduler_task.add_done_callback(
         self._log_background_task_exception("ingest_scheduler")
     )
     ```
  7. On shutdown: signal scheduler stop, await task
- [ ] Add `signal` section to config schema (or extend existing config model):
  ```yaml
  signal:
    sources:
      - type: rss
        url: https://...
        label: example
    pull_interval_seconds: 900
  ```

### Task 6.4: CLI stub (optional)

**File(s):** `teleclaude/cli/signals.py`

- [ ] `telec signals status` — query `signal_items`, `signal_clusters`, `signal_syntheses`
      counts; show last ingest time and pending cluster count
- [ ] Register subcommand in `teleclaude/cli/__init__.py`

---

## Phase 7: Tests

### Task 7.1: Unit tests — source config and fetch

**File(s):** `tests/test_signal/test_sources.py`, `tests/test_signal/test_fetch.py`

- [ ] `test_sources.py`:
  - Inline source list loads correctly
  - OPML string parses into `SourceConfig` list
  - CSV string parses into `SourceConfig` list
  - Missing file path raises at init
- [ ] `test_fetch.py`:
  - `parse_rss_feed()` handles RSS 2.0 fixture
  - `parse_rss_feed()` handles Atom fixture
  - `fetch_full_content()` strips HTML tags (mock aiohttp)

### Task 7.2: Unit tests — ingest cartridge

**File(s):** `tests/test_signal/test_ingest.py`

- [ ] Pulls feed (mocked HTTP), produces correct number of `signal.ingest.received` events
- [ ] Duplicate item (same idempotency key) is skipped
- [ ] Each emitted envelope has `description` (AI summary) and `payload.tags`
- [ ] Concurrent AI calls respect `ai_concurrency` semaphore limit

### Task 7.3: Unit tests — cluster cartridge

**File(s):** `tests/test_signal/test_cluster.py`

- [ ] `group_by_tags()` groups items sharing at least one tag
- [ ] `detect_burst()` fires at threshold
- [ ] `detect_novelty()` returns True when no overlap with recent tags
- [ ] Cluster cartridge emits `signal.cluster.formed` for each formed cluster
- [ ] Items with no tag overlap remain unclustered until singleton timeout

### Task 7.4: Unit tests — synthesize cartridge

**File(s):** `tests/test_signal/test_synthesize.py`

- [ ] `signal.cluster.formed` event triggers synthesis
- [ ] Near-duplicate items are collapsed before synthesis AI call
- [ ] `signal.synthesis.ready` envelope contains `SynthesisArtifact` in `payload.synthesis`
- [ ] Non-`signal.cluster.formed` events pass through unchanged

### Task 7.5: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify: `grep -r "from teleclaude\." company/cartridges/signal/` returns nothing
- [ ] Verify: `grep -r "from teleclaude\." teleclaude_events/signal/` returns nothing
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 8: Review Readiness

- [ ] Confirm all requirements reflected in code
- [ ] Confirm all tasks marked `[x]`
- [ ] Run `telec todo demo validate event-signal-pipeline`
- [ ] Document any deferrals in `deferrals.md`
