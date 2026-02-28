# Implementation Plan: event-platform

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
