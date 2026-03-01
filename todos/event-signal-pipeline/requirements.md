# Requirements: event-signal-pipeline

## Goal

Build a three-stage feed aggregation pipeline as domain-agnostic utility cartridges within
the `teleclaude_events/` package. The pipeline pulls raw content from external sources,
normalises each item into an event envelope, clusters related items, then synthesises
clusters into structured artifacts. Domain pipelines subscribe to synthesis output —
they never touch raw feeds directly.

AI is embedded at two stages: one-line summary + tag extraction at ingest, semantic
clustering + synthesis at the later stages.

## Scope

### In scope

1. **`signal-ingest` utility cartridge** (`teleclaude_events/cartridges/signal_ingest.py`):
   - Source types: YouTube channel feed (RSS), generic RSS, OPML bundle, X/Twitter account
   - Source configuration: inline list in cartridge config and file-reference formats (CSV, OPML)
   - Per-item normalisation into `EventEnvelope` with `event: "signal.ingest.received"`
   - AI enrichment per item: one-line summary (`description`) and comma-separated tag string
     stored in `payload.tags`
   - Deduplication: skip items already ingested (URL + source hash as idempotency key)
   - Configurable pull schedule (cron or interval)
   - Emits `signal.ingest.received` for each new item passing deduplication

2. **`signal-cluster` utility cartridge** (`teleclaude_events/cartridges/signal_cluster.py`):
   - Periodic trigger (configurable window, default 15 min) or on-demand after ingest batch
   - Groups `signal.ingest.received` events by tag overlap and semantic similarity (AI embedding)
   - Burst detection: cluster is a burst when item count exceeds threshold within window
   - Novelty detection: cluster is novel when it has no overlap with recent clusters
   - Each cluster becomes a `signal.cluster.formed` event with member envelope IDs, tags,
     burst flag, novelty flag, cluster summary, and item count
   - Minimum cluster size configurable (default 2); singletons can be promoted after timeout

3. **`signal-synthesize` utility cartridge** (`teleclaude_events/cartridges/signal_synthesize.py`):
   - Triggered by each `signal.cluster.formed` event
   - Deep read: fetches full content for each member item where available
   - Cross-source deduplication: collapses near-duplicate content from different sources
   - AI synthesis: produces a structured artifact (summary, key points, source attribution,
     confidence score, recommended action)
   - Emits `signal.synthesis.ready` with the artifact in `payload.synthesis`
   - Artifact format: Pydantic model serialised to JSON in the payload

4. **Signal taxonomy event schemas** in `teleclaude_events/schemas/signal.py`:
   - `signal.ingest.received` — level: OPERATIONAL, domain: "signal", visibility: LOCAL
   - `signal.cluster.formed` — level: OPERATIONAL, domain: "signal", visibility: LOCAL
   - `signal.synthesis.ready` — level: WORKFLOW, domain: "signal", visibility: LOCAL;
     lifecycle: creates notification, actionable: true

5. **Source configuration model** (`teleclaude_events/signal/sources.py`):
   - Inline list: `[{type: "rss", url: "...", label: "..."}, ...]`
   - File reference: `{type: "opml", path: "~/feeds.opml"}`, `{type: "csv", path: "~/channels.csv"}`
   - Config loaded and validated at cartridge init; reloaded on SIGHUP

6. **Signal storage** (`teleclaude_events/signal/db.py` or extension to `EventDB`):
   - `signal_items` table: item_id (idempotency key), source, url, raw_title, summary, tags,
     fetched_at, cluster_id (nullable)
   - `signal_clusters` table: cluster_id, tags, burst, novel, summary, member_count, formed_at
   - `signal_syntheses` table: synthesis_id, cluster_id, artifact (JSON), produced_at

7. **Utility cartridges location**: `company/cartridges/` (in-repo source code path)
   — these are the first cartridges shipped under that path, serving as the reference
   implementation for the cartridge authoring pattern. When `event-domain-infrastructure`
   ships, these cartridges will be discoverable via its runtime loader at
   `~/.teleclaude/company/domains/signal/cartridges/`; until then they are registered
   directly with the `Pipeline` instance.

8. **`telec signals` CLI stub** (optional, low priority):
   - `telec signals status` — show last ingest time, pending clusters, and synthesis count

### Out of scope

- Domain-specific routing of synthesis output (→ `event-domain-pillars`)
- Mesh distribution of `signal.synthesis.ready` to other nodes (→ `event-mesh-distribution`)
- UI for configuring sources via TUI (→ future)
- Real-time streaming ingest (WebSocket, webhooks) — pull-only in this phase
- X/Twitter live streaming API (pull via official API or scrape only)
- Paid content / paywalled sources
- Binary/video content extraction — URL and metadata only

## Success Criteria

- [ ] `signal-ingest` pulls an RSS feed, creates `signal.ingest.received` events in the pipeline
- [ ] Duplicate items (same URL + source) are skipped on re-pull
- [ ] Each ingested item carries a one-line AI summary in `description` and tags in `payload.tags`
- [ ] `signal-cluster` groups a batch of ingested items into at least one cluster
- [ ] `signal.cluster.formed` event is emitted with burst and novelty flags correctly set
- [ ] `signal-synthesize` reads a cluster, deduplicates content, and produces a synthesis artifact
- [ ] `signal.synthesis.ready` event is emitted and creates a notification
- [ ] Source config can be loaded from OPML and CSV file references
- [ ] All three cartridges are loadable via direct `Pipeline` registration (domain-infrastructure
      loader integration deferred until that todo ships)
- [ ] `make test` passes with coverage for ingest, cluster, synthesize, and source config
- [ ] `make lint` passes
- [ ] No imports from `teleclaude.*` in the signal cartridge code

## Constraints

- Cartridge interface: `async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`
- AI calls: use the existing AI client available in `PipelineContext` (added by domain-infrastructure)
- Storage: signal tables extend or co-locate with `~/.teleclaude/events.db`; no new DB files
- Source pulls are HTTP-only (requests/aiohttp); no browser automation
- All I/O async; no blocking calls in cartridge `process()`
- OPML parsing: standard library or lightweight parser only (no full feed framework)
- Cartridge config is passed at instantiation; no global mutable config state

## Risks

- **AI call latency at ingest time**: one-line summary per item could slow large batch pulls.
  Mitigate with concurrent AI calls (asyncio.gather with concurrency limit).
- **Embedding model availability**: semantic clustering requires an embedding API. If unavailable,
  fall back to tag-overlap-only clustering (degrade gracefully, log warning).
- **X/Twitter API constraints**: rate limits and auth complexity. Treat as lower priority;
  stub the source type and skip if credentials absent.
- **Synthesis quality variance**: synthesis artifact confidence score is self-reported by the AI.
  No automated validation — human review via the notification is the gate.
- **`PipelineContext` AI client dependency**: `event-domain-infrastructure` must wire an AI
  client into `PipelineContext` before these cartridges can run. Builder must verify the
  context extension is available or add it as a prerequisite task.
- **Scope creep at synthesis**: full content fetching can be expensive. Cap at N items per
  cluster (default 10) and truncate content before synthesis prompt.
