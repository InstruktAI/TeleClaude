---
id: 'project/spec/domain/event-catalog'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Every domain event the platform emits — producer context, named consumers, payload field set in domain terms. The contract that defines cross-context coordination.'
---

# Domain Event Catalog — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- @docs/project/design/architecture-v2/event-bus-transports.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The exhaustive catalog of domain events emitted by the platform's eight bounded contexts. Each event is named in the producing context's ubiquitous language, carries a payload of domain-meaningful fields, and lists its known consumers.

This catalog is the contract that defines cross-context coordination: when two services interact via events (per the context-map relationships), this document is where the wire shape is fixed. Code that emits events must match the catalog; code that consumes events depends on the catalog. The catalog evolves through PRs that touch both this file and the producing context's domain spec.

Skeleton on first commit: structure + lifecycle/spine context events. Per-context expansion happens as each domain spec is authored.

## Canonical fields

### Naming convention

Every event name follows: `<context>.<noun>.<past-tense-verb>` or `<context>.<past-tense-verb>` when no sub-noun is meaningful.

- `<context>` — one of the eight services (`workflow`, `identity`, `config`, `knowledge`, `agent_runtime`, `session_mirrors`, `integration`, `agent_artifacts`).
- `<noun>` — the entity or aggregate the event is about (optional; omitted when the context only has one primary subject).
- `<past-tense-verb>` — what happened (`created`, `updated`, `deleted`, `started`, `ended`, `received`, `delivered`, `phase_advanced`, etc.).

Examples: `workflow.todo.created`, `agent_runtime.session.started`, `integration.outbox.delivered`, `knowledge.snippet.indexed`.

### Per-event description format

Each event below carries:

- **Name** — `<context>.<noun>.<verb>`
- **Producer** — the context that emits the event
- **Emitted when** — the domain condition that triggers emission
- **Payload** — the data carried, in domain field names
- **Known consumers** — contexts (and external systems) that subscribe and act
- **Visibility** — per `event-bus-transports.md` posture: `LOCAL` (in-process only), `CLUSTER` (cross-process via Redis), `PUBLIC` (exposed to external mesh — rare)
- **Idempotency key** — the field tuple that makes two emissions "the same event" for consumer dedup
- **Emit posture** — `commit-then-emit` (loud-fail) | `outbox` (atomic with caller commit) | `inbox` (durable capture then publish)

### Events

> **Status:** skeleton on first commit. Per-context specs append their events to the relevant section as they're authored. Order within a section is alphabetical by event name.

#### identity

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `identity.principal.created` | identity | CLUSTER | commit-then-emit |
| `identity.token.issued` | identity | CLUSTER | commit-then-emit |
| `identity.token.revoked` | identity | CLUSTER | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/identity` authoring.

#### config

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `config.effective.updated` | config | CLUSTER | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/config` authoring.

#### workflow

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `workflow.todo.created` | workflow | CLUSTER | commit-then-emit |
| `workflow.todo.updated` | workflow | CLUSTER | commit-then-emit |
| `workflow.todo.phase_advanced` | workflow | CLUSTER | commit-then-emit |
| `workflow.todo.delivered` | workflow | CLUSTER | commit-then-emit |
| `workflow.roadmap.entry_moved` | workflow | CLUSTER | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/workflow` authoring.

#### knowledge

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `knowledge.snippet.indexed` | knowledge | CLUSTER | commit-then-emit |
| `knowledge.taxonomy.updated` | knowledge | CLUSTER | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/knowledge` authoring.

#### agent_runtime

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `agent_runtime.session.started` | agent_runtime | CLUSTER | LISTEN/NOTIFY (after batched write commits) |
| `agent_runtime.session.updated` | agent_runtime | CLUSTER | LISTEN/NOTIFY (batched, may carry many sessions in one event payload) |
| `agent_runtime.session.ended` | agent_runtime | CLUSTER | LISTEN/NOTIFY (urgent-flushed; payload includes native_file_path for session_mirrors extraction) |
| `agent_runtime.operation.completed` | agent_runtime | CLUSTER | commit-then-emit |

Note: agent_runtime uses windowed batched writes + LISTEN/NOTIFY dispatch for the high-volume hook-driven events (started/updated/ended). See `feature/agent_runtime/windowed-batch-write-and-dispatch`.

**Detailed entries:** see `project/spec/domain/agent_runtime`.

#### session_mirrors

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `session_mirrors.mirror.created` | session_mirrors | CLUSTER | commit-then-emit |

**Detailed entries:** see `project/spec/domain/session_mirrors`.

#### integration

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `integration.inbox.received` | integration | CLUSTER | inbox |
| `integration.outbox.appended` | integration | CLUSTER | commit-then-emit |
| `integration.outbox.delivered` | integration | CLUSTER | commit-then-emit |
| `integration.outbox.dead_lettered` | integration | CLUSTER | commit-then-emit |

Note: `integration.inbox.agent_hook_received` was REMOVED in the agent_runtime/integration boundary correction. Agent CLI hooks bypass integration entirely — they reach agent_runtime directly via the `telec-hook` subprocess (owned by agent_runtime). Integration's inbox is for true external webhooks only (Telegram, Discord, WhatsApp, GitHub).

**Detailed entries:** see `project/spec/domain/integration`.

#### agent_artifacts

| Event | Producer | Visibility | Posture |
|---|---|---|---|
| `agent_artifacts.synced` | agent_artifacts | CLUSTER | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/agent_artifacts` authoring.

### Subscription map

Inverse view: for each event, which consumers act on it. Populated as per-context specs land.

| Event | Consumers |
|---|---|
| `integration.inbox.received` | `agent_runtime` (routes inbound EXTERNAL messages to sessions; e.g., Telegram inbound) |
| `agent_runtime.session.started` | `frontend` (live UI), audit log consumers |
| `agent_runtime.session.updated` | `frontend` (live UI, iterates batched payload), `telec-tui` (cache invalidation) |
| `agent_runtime.session.ended` | `session_mirrors` (extracts mirror from native_file_path), `identity` (auto-revokes session token), `frontend` (live UI removal) |
| `session_mirrors.mirror.created` | `frontend` (history search index refresh), audit log consumers |
| `agent_runtime.operation.completed` | `workflow` (advances todo phase when operation completes a step) |
| `workflow.todo.phase_advanced` | `integration` (outbox notifications to recipients per subscription) |
| `workflow.todo.delivered` | `integration` (delivery announcement notifications) |
| `knowledge.snippet.indexed` | `frontend` (search index refresh) |
| `config.effective.updated` | every service that caches config (re-read on next access) |

## Allowed values

- `visibility`: `LOCAL` (in-process only, never published to Redis), `CLUSTER` (cross-process via Redis, the default for domain events that cross context boundaries), `PUBLIC` (exposed to external mesh — reserved for federation use cases, currently unused).
- `posture` (emit safety pattern): `commit-then-emit` (the producer commits its state change in Postgres, THEN publishes the event; loud-fail on publish failure — caller treats it as a defect since the state change already landed), `outbox` (the event is written to the producing context's outbox table atomically with the caller's state change; a dispatcher publishes asynchronously — used for outbound external delivery and for cross-context events where at-least-once matters), `inbox` (the event represents an external input captured durably first then published; used for ingress paths from external systems).

## Known caveats

- This catalog is `actual` upon commit and evolves with every per-context spec edit.
- The producer context's per-context spec is the authoritative source for event payload field names; this catalog summarizes for cross-context discoverability. If they disagree, the per-context spec wins and this catalog gets corrected in the same PR.
- Events not in this catalog don't exist. An emitter trying to publish an event not in the catalog is a defect — register it here first, in the same PR.
- v1 events that don't fit the v2 naming convention will be carried through the v1→v2 ACL with translation. The ACL maps v1 event names to v2 catalog entries. v1 names are NOT included in this catalog.
- Event payload schemas live in the producing context's spec, not here. This catalog gives the name + the field set in domain terms; the per-context spec gives the wire schema.
- Consumer lists in the subscription map are aspirational pending per-context spec authoring. They're listed here so cross-context coordination is visible from one place.
