# Implementation Plan: event-platform

## Reality Baseline

**As of 2026-03-01, `teleclaude_events/` already exists with substantial implementation.
Phase 1 scope below was written as if from scratch. This section documents what exists,
what needs refinement, and what explicit wiring tasks remain unscheduled.**

### What already exists

| File / Component | Status |
|---|---|
| `teleclaude_events/envelope.py` | Exists. `EventEnvelope`, `EventVisibility`, `EventLevel` defined. |
| `teleclaude_events/pipeline.py` | Exists. `Pipeline`, `PipelineContext`, `Cartridge` protocol defined. |
| `teleclaude_events/catalog.py` | Exists. `EventCatalog`, `EventSchema`, `NotificationLifecycle` defined. |
| `teleclaude_events/db.py` | Exists. `EventDB` with aiosqlite. |
| `teleclaude_events/producer.py` | Exists. `EventProducer` / `emit_event()`. |
| `teleclaude_events/cartridges/dedup.py` | Exists. `DeduplicationCartridge` implemented. |
| `teleclaude_events/cartridges/notification.py` | Exists. `NotificationProjectorCartridge` implemented. |
| `teleclaude_events/schemas/system.py` | Exists. Schemas for `system.*` domain events. |
| `teleclaude_events/schemas/software_development.py` | Exists. Schemas for `domain.software-development.*`. |
| `teleclaude_events/delivery/telegram.py` | Exists. Telegram delivery adapter implemented. |
| `teleclaude_events/processor.py` | Exists. `EventProcessor` (pipeline host). |

### What needs to be refactored vs. built from scratch

**Refactor (exists, needs extension or correction):**

- `PipelineContext` — currently lacks `ai_client`. Phase 3 signal cartridges assume it.
  Must be added before `event-domain-infrastructure` ships, not before Phase 1.
- `EventSchema` — `idempotency_fields` field may be missing or incomplete.
  Verify against the deduplication cartridge's key derivation logic before Phase 1 closes.
- `NotificationLifecycle` — `meaningful_fields` field is defined in `catalog.py` but may
  not be wired into the notification projector's transition logic. Verify and fix.
- `envelope.py` — `source` field is currently a free string. Once `mesh-architecture`
  defines the canonical `node_id` format, this field's validation and derivation must
  be updated. Not blocking for Phase 1 local delivery.
- `teleclaude_events/schemas/` — existing schema registration in `build_default_catalog()`
  needs audit: confirm `idempotency_fields` and `lifecycle` are set on all registered types.

**Build from scratch (Phase 1 tasks that do not yet exist):**

- HTTP API endpoints: list, get, mark seen, claim, resolve notifications.
- WebSocket push adapter for the event DB.
- Daemon startup/shutdown wiring for `EventProcessor`.
- `telec events list` CLI command.
- Old `teleclaude/notifications/` package removal and `notification_outbox` table cutover.

### What needs to be integrated with existing adapters / daemon code

- **Daemon hosting:** `EventProcessor` must be started as a background task in
  `teleclaude/daemon.py`. The existing `NotificationOutboxWorker` pattern is the
  reference (see `daemon.py:1857`). No such wiring exists today.
- **Telegram delivery:** `teleclaude_events/delivery/telegram.py` exists but is not
  wired into the pipeline. The notification projector must call it after projecting
  state. Wiring task required.
- **Redis Stream reader:** `EventProcessor` needs to consume from `teleclaude:events`
  via `XREADGROUP`. Current code uses `XREAD` patterns only. Consumer group setup
  is a new pattern for this codebase.

### Explicit wiring tasks (currently unscheduled — must be added to Phase 1)

These were described in Phase 1 scope but no tasks were written for them:

1. **Daemon restart event emission:** Wire `system.daemon.restarted` emission into
   `teleclaude/daemon.py` startup path. Requires `EventProducer` to be initialized
   before the daemon emits its first event. Task: add to Phase 1 build checklist.

2. **`todo.dor_assessed` event emission:** Wire emission into the `telec todo prepare`
   state machine at the point where DOR scoring completes. The producer call site is in
   the prepare command flow (`teleclaude/cli/` or orchestration layer). Task: identify
   exact call site, add `emit_event()` call, register schema in `software_development.py`.

3. **Consolidation cutover tasks:** Phase 1 lists removal of old `notification_outbox`
   but does not schedule individual migration tasks per call site. At least 7 call sites
   need rewiring before the old table can be dropped. These must be enumerated and tracked
   explicitly in the Phase 1 task list before build begins.

---

## Overview

The event processing platform is delivered through a phased breakdown of sub-todos. Each phase
is an independent, committable deliverable with its own requirements and implementation plan.
Phases are ordered by dependency — later phases build on earlier ones.

The holder todo (`event-platform`) tracks the full vision. Each sub-todo is a buildable unit.

## Phase Breakdown

### Phase 1: Core Platform — `event-platform-core`

**Delivers:** The foundation everything else builds on.

**Scope:**

- Package scaffolding: `teleclaude_events/` at monorepo root, `pyproject.toml` updated
- Envelope schema (5-layer Pydantic model) with `visibility` field (`local`/`cluster`/`public`)
- Event catalog: type registry with schema declarations, idempotency key derivation
- Redis Streams producer: `emit()` → XADD to `teleclaude:events` stream
- Pipeline runtime: sequential cartridge executor (system pipeline only)
- Basic system cartridges: deduplication + notification projector
- SQLite notification state: separate DB (`~/.teleclaude/events.db`), notification table,
  state machine (human awareness + agent handling)
- HTTP API on existing daemon API server: list, get, mark seen, claim, resolve
- WebSocket push via existing WS infrastructure
- Daemon hosting: start pipeline processor on startup, stop on shutdown
- Initial event schemas: `system.*` (daemon restart, worker crash) and
  `domain.software-development.planning.*` (todo lifecycle basics)
- First producers wired: daemon restart event, `todo.dor_assessed`
- Telegram delivery adapter (reuses existing `send_telegram_dm`)
- `telec events list` CLI command
- Consolidation: remove old `teleclaude/notifications/` package and `notification_outbox` table

**Depends on:** nothing
**Unblocks:** all other phases and all external dependents

**Codebase patterns to follow:**

| Pattern                 | Evidence                                                       |
| ----------------------- | -------------------------------------------------------------- |
| Redis Streams XADD      | `teleclaude/transport/redis_transport.py:1731`                 |
| Redis Streams XREAD     | `teleclaude/transport/redis_transport.py:975`                  |
| aiosqlite DB            | `teleclaude/core/db.py`                                        |
| Pydantic models         | established pattern                                            |
| FastAPI endpoints       | `teleclaude/api_server.py`                                     |
| WebSocket push          | `teleclaude/api_server.py:1878` (subscription system)          |
| Background task hosting | `teleclaude/daemon.py:1857` (NotificationOutboxWorker pattern) |

**Estimated size:** ~22 tasks across 8 build phases. Large but incrementally testable —
builder commits after each phase.

---

### Phase 2: System Cartridges — `event-system-cartridges`

**Delivers:** The intelligence layer of the system pipeline.

**Scope:**

- Trust evaluator cartridge: per-event content evaluation, configurable strictness,
  accept/flag/quarantine/reject outcomes
- Enrichment cartridge: add local context from platform state ("this entity has failed
  three times before")
- Correlation cartridge: detect patterns across events, synthesize higher-order events
  (e.g., burst detection, failure cascades)
- Classification cartridge: determine event treatment (notification-worthy, index entry,
  signal-only) based on schema declarations
- Pipeline ordering: trust → dedup → enrichment → correlation → classification → projection
- Tests for each cartridge in isolation and integrated pipeline order

**Depends on:** `event-platform-core` (pipeline runtime, envelope schema)
**Unblocks:** `event-domain-infrastructure` (domain pipeline needs classification)

**Estimated size:** medium (~12 tasks). Each cartridge is self-contained.

---

### Phase 3: Domain Infrastructure — `event-domain-infrastructure`

**Delivers:** Multi-domain event processing with domain-scoped cartridge management.

**Scope:**

- Domain pipeline: parallel execution per domain after system pipeline completes
- Domain cartridge loading: read cartridges from `company/domains/{name}/cartridges/`
- Domain guardian AI configuration: agent config per domain that evaluates cartridge
  submissions, detects patterns, validates compositions
- Folder hierarchy: `~/.teleclaude/company/`, `~/.teleclaude/personal/`, `~/.teleclaude/helpdesk/`
- Personal subscription pipeline: per-member micro-cartridges (leaf nodes)
- Cartridge dependency DAG: topological sort on startup, parallel execution at same level
- Pipeline validation: scope matching, dependency satisfaction, conflict detection
- Cartridge lifecycle: install, remove, promote (personal → domain → platform)
- Autonomy matrix: configurable per `event_type > cartridge > domain > global`
- `telec config` integration for autonomy level management
- Roles/permissions: admin vs member scope enforcement

**Depends on:** `event-system-cartridges` (classification determines domain routing)
**Unblocks:** `event-domain-pillars`, `event-signal-pipeline`

**Estimated size:** large (~20 tasks). Significant new infrastructure.

---

### Phase 4: Signal Processing Pipeline — `event-signal-pipeline`

**Delivers:** Three-stage feed aggregation as domain-agnostic utility cartridges.

**Scope:**

- `signal-ingest` utility cartridge: configurable source pulling (YouTube channels, RSS/OPML,
  X accounts), normalization to event envelope with one-line AI summary and tags
- `signal-cluster` utility cartridge: periodic grouping by tag overlap and semantic similarity,
  burst and novelty detection
- `signal-synthesize` utility cartridge: deep read per cluster, deduplication across sources,
  synthesis artifact production
- Source configuration: inline and file-reference formats (CSV, OPML)
- Signal taxonomy events: `signal.ingest.received`, `signal.cluster.formed`,
  `signal.synthesis.ready`
- Quality through synthesis: low-quality signals absorbed naturally

**Depends on:** `event-domain-infrastructure` (domain cartridges subscribe to synthesis output)
**Unblocks:** domain pillars that use feed monitoring (marketing, engineering)

**Estimated size:** large (~18 tasks). AI integration for summary/clustering/synthesis.

---

### Phase 5: Alpha Container — `event-alpha-container`

**Delivers:** Sandboxed execution for experimental cartridges.

**Scope:**

- Long-running Docker sidecar container: read-only, no-network, capped resources
- Three read-only mounts: codebase, AI credentials, alpha cartridge code
- Unix socket communication between daemon and container
- Alpha cartridges run AFTER approved ones (additive, never blocking)
- Timeout and failure isolation: daemon continues with approved pipeline output
- Promotion path: alpha → approved (moves from mount into codebase, runs in-process)
- Zero overhead when no alpha cartridges exist (container not started)

**Depends on:** `event-platform-core` (pipeline runtime)
**Unblocks:** experimental cartridge development, community contributions

**Estimated size:** medium (~10 tasks). Docker + IPC focus.

---

### Phase 6: Mesh Distribution — `event-mesh-distribution`

**Delivers:** Cross-node event distribution based on visibility levels.

**Scope:**

- Mesh publishing cartridge: watches for `visibility: public` events, forwards to peers
- Cluster distribution: `visibility: cluster` events forwarded via Redis transport to
  all computers in the owner's cluster
- Receiving pipeline: incoming mesh events enter the local trust evaluator first
- Cartridge publishing: `cartridge.published` event with code-as-data payload
- Sovereignty-based installation: L1 (human approves), L2 (AI decides, human notified),
  L3 (fully autonomous)
- Organic promotion: `cartridge.invoked` meta-events → `cartridge.promotion_suggested`
  when critical mass reached

**Depends on:** `event-platform-core`, `mesh-architecture` (P2P transport)
**Unblocks:** `community-governance`, `community-manager-agent`

**Estimated size:** medium (~12 tasks). Requires mesh transport to be available.

---

### Phase 7: Domain Pillars — `event-domain-pillars`

**Delivers:** Out-of-box domain configurations for the four pillars.

**Scope per pillar:**

- **Software Development**: todo lifecycle, build/review, deployment, operations, maintenance.
  Event schemas, starter cartridges, guardian AI config. (Mostly formalizing what exists.)
- **Marketing**: content lifecycle, campaign tracking, feed monitoring (composes signal pipeline).
  Starter cartridges for content publication pipeline, campaign budget monitor.
- **Creative Production**: asset lifecycle (brief → draft → review → approval → delivery).
  Multi-format support.
- **Customer Relations**: help desk events, escalation, satisfaction tracking. Jailed agent
  territory for external-facing input.

Each pillar: guardian AI config, starter cartridges, event schemas, documentation for
`telec init` discovery.

**Depends on:** `event-domain-infrastructure`, `event-signal-pipeline` (for marketing feeds)
**Unblocks:** end-user domain experience

**Estimated size:** large (~20 tasks). Breadth across four domains.

---

## Dependency Graph

```
event-platform-core
  ├── event-system-cartridges
  │   └── event-domain-infrastructure
  │       ├── event-signal-pipeline
  │       │   └── event-domain-pillars (marketing needs signals)
  │       └── event-domain-pillars
  ├── event-alpha-container
  └── event-mesh-distribution (also needs mesh-architecture)
      └── community-governance, community-manager-agent
```

## Discovery Blockers (from 2026-03-01 peer research)

The discovery brief (`discovery-brief.md`) identified 10 blockers across the event-platform
group. This section tracks their resolution status. Blockers are owned by sub-todos unless
they affect the container's breakdown or vision.

### Resolved

- **Phase 1 reality mismatch** — implementation plan updated with Reality Baseline section
  (2026-03-01). Existing code documented, refactor vs. build-from-scratch separated.
- **`integration-events-model` delivered** — empty directory cleaned up, marked delivered in
  roadmap.

### Owned by sub-todos (tracked in their artifacts)

- **Trust truth table missing** → `event-system-cartridges` requirements
- **Correlation re-entry loop risk** → `event-system-cartridges` requirements (source tag guard)
- **Member slug undefined** → `event-domain-infrastructure` requirements (uses `PersonEntry.email`)
- **DAG cache absent** → `event-domain-infrastructure` risks section
- **PipelineContext.ai_client uncontracted** → `event-signal-pipeline` (add before domain-infrastructure ships)
- **`cartridge.invoked` emission cascade** → `event-mesh-distribution` (self-invocation guard)
- **CLI collision (`telec cartridges list`)** → `event-alpha-container` / `event-mesh-distribution` (reconcile)

### Unresolved (blocking sub-todo readiness)

- **`mesh-architecture` entirely empty** — requirements.md and implementation-plan.md are blank
  templates. Blocks: `event-mesh-distribution`, `mesh-trust-model`, `community-governance`.
  Resolution: mesh-architecture must be prepared independently before these sub-todos can build.
- **Consolidation cutover void** — 7 old notification paths need migration tasks enumerated.
  Owned by Phase 1 (delivered), but cutover may still be incomplete. Verify against live code.
- **`branch_pushed` contradiction in integrator-wiring** — FR2 folds into `deployment.started`
  payload; readiness predicate requires separate event; FR1 forbids modifying integration
  internals. Owned by `integrator-wiring` todo, not event-platform. Track as external dependency.

### Cross-cutting patterns (require formal specification)

- **`PipelineContext` contract surface** — every cartridge todo assumes fields not yet in the
  dataclass. Needs a formal spec: which fields exist, which todo adds them, in what order.
  Recommendation: create a `PipelineContext` spec as a doc snippet or add to
  `event-platform-core` as a contract addendum.
- **"Cluster" definition** — appears in 4+ contexts with no authoritative definition.
  Blocked until `mesh-architecture` defines it.

### Design confirmations (from prepare session 2026-03-03)

- **Cartridge ordering primitives are sufficient.** `depends_on` scoped to same-domain IDs
  is correct. Cross-scope composition is event-based (utility cartridges emit events, domain
  cartridges subscribe). No cross-domain dependency mechanism needed.
- **Agent decides cartridge positioning.** The domain guardian AI inspects existing manifests,
  understands the DAG, and writes `depends_on` for new cartridges. No "default trunk" or
  "main branch" primitive needed — the AI is the positioning intelligence. Humans never
  interact with the DAG directly.

## External Dependents

These existing todos depend on `event-platform` (the holder):

- `integrator-wiring` — wire integration module into event emission
- `history-search-upgrade` — notification-driven search indexing
- `prepare-quality-runner` — subscribes to `todo.dor_assessed` events
- `todo-dump-command` — emits `todo.dumped` events
- `content-dump-command` — emits content dump events
- `mesh-architecture` — carries events between nodes
- `event-envelope-schema` — formalizes the five-layer envelope
- `community-manager-agent` — GitHub event handlers
- `telec-init-enrichment` — bootstraps domain awareness

Most external dependents need only Phase 1 (core platform) to unblock. The holder todo
is considered delivered when all phases are complete, but external work can begin after
the core is operational.
