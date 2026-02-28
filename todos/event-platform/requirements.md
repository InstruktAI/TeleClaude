# Requirements: event-platform

## Goal

Build an **event processing platform** — a pipeline runtime with pluggable cartridges that is
the single source of truth for all autonomous platform events. Events are the primary concept.
Notifications are one projection pattern that certain event groups opt into.

The package is `teleclaude_events/`, not `teleclaude_notifications/`. Events are first-class.
Notifications are derived.

This is the nervous system of TeleClaude: sensory input (events via Redis Streams), processing
(cartridge pipeline), motor output (agent responses + delivery), awareness (multi-surface
projections of the same truth via API, WebSocket, Discord, Telegram).

## Core Architecture

### Events are primary, notifications are projections

An event is an immutable fact: "this thing happened." It flows through the Redis Stream, gets
processed by the cartridge pipeline, and produces effects. Events are never modified after
emission. The Redis Stream is the canonical event log. The notification table is one projection
of that log — a view shaped by lifecycle declarations, not the source of truth.

Not all events become notifications. The schema determines treatment:

- **Notification-worthy**: creates/updates rows in SQLite with human awareness + agent handling
  state. What humans and agents see in their inbox.
- **Index entry**: stored for lookup but not surfaced as a notification. Service descriptors,
  node registrations.
- **Signal only**: routed to subscribed handlers but not persisted in notification state.
  Pure event-driven triggering.

### Cartridge pipeline

The cartridges ARE the processing. Lined up in sequence, each one does its job, passes the
event along (or drops it). The core is tiny — just the pipeline executor and the stream reader.

Cartridge interface:

```python
async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    return event  # or None to drop
```

Pipeline phases with scopes:

1. **System pipeline** — Linear, sequential, admin-only. Core cartridges: trust evaluator,
   deduplication, enrichment, correlation, classification, notification projector.
2. **Domain pipeline** — Parallel per domain. Domain-specific processing managed by domain
   guardian AIs. Branches after system pipeline.
3. **Personal subscriptions** — Parallel per member. Leaf nodes. Micro-cartridges expressing
   individual preferences, created by the member's AI.

### Three-tier event visibility

Events declare their distribution scope:

- **`local`** — stays on this computer only. Internal state, debug events.
- **`cluster`** — distributed across all computers in the owner's cluster. Operational events,
  cross-machine coordination.
- **`public`** — published to the mesh for peer consumption. Community events, shared signals,
  cartridge publications.

Visibility is declared per event type in the schema. The system pipeline respects visibility
when routing to delivery adapters. Cluster distribution uses the existing Redis transport
between computers. Public distribution uses the mesh transport (depends on `mesh-architecture`).

### Trust and autonomy are orthogonal

**Trust** is about data integrity — "should I accept this event at all?" Per-event, per-content
evaluation in the system pipeline. Applied to ALL events, local and remote.

**Autonomy** is about delegation — "how much does my AI handle without me?" Applied AFTER
trust. Configurable at multiple scopes: `event_type > cartridge > domain > global`.

- **L3 (default)**: Full autonomy. AI handles everything. Human sees a dashboard.
- **L2**: Guided. AI handles routine, surfaces novel/high-impact for review.
- **L1**: Supervised. Everything surfaces for human review.

### Five-layer envelope schema

1. **Identity**: event type, version, source, timestamp, idempotency key
2. **Semantic**: level, domain, entity ref, description, visibility (`local`/`cluster`/`public`)
3. **Data**: payload (arbitrary JSON)
4. **Affordances**: action descriptors (structurally present, describe possibilities)
5. **Resolution**: terminal conditions and resolution shape

### Notification mechanics

A notification is a living object with a state machine. Two orthogonal dimensions:

- **Human awareness**: `unseen` → `seen`
- **Agent handling**: `none` → `claimed` → `in_progress` → `resolved`

Notification lifecycles are declared by cartridges. A group of related events (e.g.,
`deployment.started`, `.completed`, `.failed`) declares how they map to notification state
transitions. The notification projector reads these declarations — it doesn't know about
specific domains.

Lifecycle stages: Active → Resolved → Archived → Purged.

### Two kinds of cartridges

**Utility cartridges** — domain-agnostic building blocks. Signal ingest, summarizer, scheduler,
threshold monitor, content formatter. Live in `company/cartridges/`.

**Domain cartridges** — compose utility cartridges with domain knowledge. Campaign monitor,
deployment tracker, asset production tracker. Live in `company/domains/{domain}/cartridges/`.

### Signal processing pipeline (utility cartridges)

Three-stage domain-agnostic feed processing:

1. **signal-ingest** — Pulls from configured sources (YouTube, RSS, X, etc.). Normalizes to
   minimal envelope with one-line AI summary and tags. Cheap. High volume.
2. **signal-cluster** — Groups signals by tag overlap and semantic similarity. Detects bursts
   and novelty. Works on metadata only.
3. **signal-synthesize** — Deep reads per cluster, not per item. Deduplicates, extracts unique
   perspectives, produces synthesis artifact. Expensive but runs once per cluster.

### Event taxonomy

Namespaced per scope:

```
system.{subsystem}.{event}           — platform core
signal.{stage}.{event}               — domain-agnostic signal processing
domain.{name}.{entity}.{event}       — domain-specific, namespaced
```

Starter taxonomies ship per domain pillar. Taxonomy grows through governance.

### Domain pillars (out-of-box)

Each pillar has a guardian AI config, starter cartridges, event schemas, and documentation:

- **Software Development** — todo lifecycle, build/review, deployment, operations, maintenance
- **Marketing** — content lifecycle, feed monitoring, campaigns
- **Creative Production** — asset lifecycle: brief → draft → review → approval → delivery
- **Customer Relations** — help desk, escalation, satisfaction tracking

### Folder hierarchy

```
~/.teleclaude/
  ├── company/                  # crown jewels — backed up
  │   ├── domains/{name}/cartridges/
  │   └── cartridges/           # domain-agnostic utility cartridges
  ├── personal/{member}/cartridges/
  └── helpdesk/                 # jailed agent territory
```

Progressive promotion: personal → domain → platform.

### Alpha container

Approved cartridges run in-process. Experimental cartridges run in a sandboxed Docker sidecar:
read-only mounts, no network, no privilege escalation. Alpha cartridges run AFTER approved ones.
Additive, never blocking.

### Roles and permissions

| Role   | System cartridges | Domain cartridges             | Personal cartridges |
| ------ | ----------------- | ----------------------------- | ------------------- |
| Admin  | Full control      | Full control                  | Can view all        |
| Member | No access         | Subscribe in assigned domains | Full control of own |

No human domain managers — domain guardian AIs handle cartridge evaluation and promotion.

### Event-driven job execution

Events replace scheduled jobs. Lifecycle transitions are the universal signal source.
`todo.activated` → quality runner. `todo.dumped` → automated preparation.
`deployment.failed` → agent claims incident. Reactive, not polling.

### Consolidation

ALL existing bespoke notification paths collapse: `notification_outbox` table/workers,
session outbox workers, hook outbox paths, job channel reports, direct channel posting,
scheduled maintenance jobs, inline dispatch chains.

## Success Criteria (full platform)

- [ ] `teleclaude_events/` exists as a separate package with no `teleclaude.*` imports.
- [ ] Events flow through a cartridge pipeline: producer → Redis Stream → pipeline → projections.
- [ ] Cartridge interface is stable: `async def process(event, context) -> event | None`.
- [ ] System, domain, and personal pipeline scopes operate correctly.
- [ ] Visibility levels (`local`, `cluster`, `public`) control event distribution.
- [ ] Notification projector creates/updates SQLite state from lifecycle declarations.
- [ ] API returns notifications filterable by level, domain, status, time range.
- [ ] WebSocket push delivers events to connected clients.
- [ ] Trust evaluation runs per-event before any other processing.
- [ ] Autonomy levels (L1/L2/L3) gate post-pipeline behavior, configurable per scope.
- [ ] Signal processing pipeline (ingest → cluster → synthesize) operates for configured feeds.
- [ ] At least one domain pillar (software-development) is fully operational.
- [ ] `telec events list` shows all registered event types.
- [ ] Old `teleclaude/notifications/` package is removed.
- [ ] `make test` and `make lint` pass.

## Constraints

- Redis Streams for event persistence (already running Redis). No additional brokers.
- Separate SQLite file for notification state (not the daemon's DB).
- `teleclaude_events/` has zero imports from `teleclaude.*`. One-way dependency.
- Wire format is JSON. Internal models are Pydantic. Envelope schema is versioned.
- Async-first: all I/O operations must be async.
- Cartridges must be composable — DAG-based dependency ordering, no circular deps.
- `pyproject.toml` package discovery needs updating for `teleclaude_events*` glob.

## Risks

- **Scope**: the full platform is large. Phased delivery via sub-todos mitigates this.
- **Consumer groups**: XREADGROUP is new to this codebase (current code uses XREAD only).
- **Migration from old system**: existing `notification_outbox` call sites need rewiring.
- **Separate DB coordination**: own migration runner, connection management, lifecycle.
- **Cartridge ecosystem complexity**: pipeline validation, dependency resolution, and
  sandboxing are each significant subsystems.
