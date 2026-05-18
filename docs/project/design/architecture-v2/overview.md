---
description: 'Target architecture for v2: Rust services-as-crates, Postgres-only storage, in-place greenfield rebuild alongside v1 in the same repo.'
id: 'project/design/architecture-v2/overview'
scope: 'project'
type: 'design'
visibility: 'public'
---

# Architecture V2 Overview — Design

## Required reads

- docs/project/design/architecture/system-overview.md
- docs/project/design/architecture-v2/journey.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/file-layout.md

## Purpose

Define the target architecture for v2 and the operational model that gets us
there. v2 is a Rust greenfield rebuild of the TeleClaude backend, executed
in-place in the same repo as v1, with services lifting one at a time until v1
is fully retired.

## Inputs/Outputs

**Inputs:**

- the current TeleClaude (v1) architecture and its drift (see journey)
- the operational reality: single machine, single-user-today,
  multi-concurrent-writers, AI-agent-heavy workload
- the existing `frontend/` (Next.js) which v2 keeps unchanged

**Outputs:**

- the target architectural shape
- the language, storage, and transport choices
- the service model and runtime composition
- the migration approach that gets us from v1 to v2 without freezing
  development

## Invariants

- **Backend is Rust.** The compiler is the discipline enforcer that v1
  (Python) couldn't be. Frontend stays TypeScript/Next.js where it already
  lives.
- **Services are crates.** Every service is a Rust library crate consumed as
  an SDK by the binaries that need it. No local-process transports between
  same-language services. See transport-rules.
- **Local-first.** Project-local work runs without daemon dependency. CLI
  embeds the service crates it needs and calls them directly.
- **Postgres-only for persistent state.** One local Postgres instance,
  schema per service. No SQLite anywhere in v2. No filesystem-as-database.
- **Redis is the bus, not state.** Pub/sub for events, queues for work,
  leases for coordination, ephemeral cache. State lives in Postgres.
- **Daemon is narrow.** Hosts the agent_runtime service in long-running
  form, supervises workers, runs the WebSocket bridge for browser delivery.
  It is no longer the gravity well for business logic.
- **Greenfield in same repo.** v2 lives at `crates/` alongside v1
  (`teleclaude/`). They coexist until v1 is retired piece by piece. No
  separate fork, no parallel repo.
- **No transports between local same-language processes.** SDK calls only
  within Rust. HTTP only for cross-language (browser) or cross-machine.
- **Single event-bus transport.** Redis Streams for events.
  In-coroutine sync uses Tokio channels (`oneshot`, `broadcast`) — not
  events.
- **Authored content stays as files.** Code, configs, docs sources, agent
  artifacts — all filesystem. Services ingest from files but don't own the
  source.

## Primary flows

### Target stack

| Concern | Choice |
|---|---|
| Backend language | Rust |
| Frontend | TypeScript / Next.js (already in `frontend/`) |
| Persistent state | Postgres (single local instance, schema per service) |
| Events / queues / leases / cache | Redis |
| Browser real-time | WebSocket (frontend custom server bridges to Redis) |
| Logging | `tracing` → `instrukt_ai_logging` format files |
| Migrations | `sqlx::migrate!()` per service |
| Async runtime | Tokio |

### The eight services

Each is a library crate under `crates/`. See `services.md` for full
ownership boundaries.

- `identity` — principals, roles, tokens, auth resolution
- `agent_runtime` — agent sessions, tmux orchestration, live coordination
- `workflow` — todos, roadmap, artifacts, state machines
- `session_mirrors` — canonical transcripts, history, replay
- `knowledge` — snippets, taxonomy, selection policy
- `integration` — webhooks, outbox/inbox, workers, retries
- `config` — system, project, person configuration overlays
- `agent_artifacts` — artifact sources, inflation, distribution

Plus cross-cutting infrastructure crates: `observability`, `event_bus`,
`storage`, `state_machine`, `shared`.

### Binary composition

A small fixed set of binaries embeds these crates:

- `telec` — CLI, single binary, embeds whatever services its subcommands
  need
- `telec-tui` — TUI, embeds workflow + agent_runtime + others as needed
- `telec-daemon` — long-running supervisor; hosts agent_runtime, spawns
  workers, runs the WebSocket bridge
- `telec-api` — HTTP API for the browser frontend
- Worker binaries — spawned by daemon for integration outbox drainage,
  retries, etc.

### Runtime topology

```
[browser]
   ↓ WebSocket (via frontend custom server bridge → Redis sub)
[telec-api]                            ← HTTP API in Rust, embeds services
   |
   |                       ┌──── Redis ────┐
   |                       │ events queues │
   ↓                       │ pub/sub leases│
[Postgres]  ←──schema────  └─────  ▲ ──────┘
   ↑                              │
   |                              │
[telec-daemon]                    │
   ↑                              │
[telec / telec-tui (per invocation, in-process services)]
```

Every binary embeds the service crates it needs. Postgres holds all
persistent state. Redis carries events and ephemeral coordination. The
daemon is one binary among several, not the central hub.

### Cross-cutting principles

**Local-first project autonomy.** Project-local work runs without daemon
dependency. `telec todo list` calls workflow service directly via the crate.

**Business logic in services, not transports.** CLI, TUI, API, hook
receivers, UI adapters are all thin entry points. They authenticate,
validate, translate, and call into service crates. They define no domain
behavior.

**Event-driven side effects.** Cross-component coordination uses Redis
events. Side effects that must survive restart use the integration
service's outbox/inbox.

**Storage is operational truth.** All operational state lives in Postgres,
service-owned schemas. No SQLite, no JSON state files, no compensating
caches.

**Progressive-disclosure context.** The strongest existing platform idea
survives intact in the knowledge service. Structured retrieval, scope-aware
selection, policy-driven, not generic RAG.

### Frontend

`frontend/` (Next.js + custom server for WebSocket support) stays where it
is. It talks to `telec-api` (or, during transition, to the v1 daemon HTTP
API). When `telec-api` is up, the frontend's HTTP/WebSocket bridge points
at it instead of v1.

The frontend is not part of the Rust rewrite. It evolves on its own
timeline. v2 backend exposes the contract; frontend consumes it.

### Migration approach

v2 lives at `crates/` alongside v1 at `teleclaude/`. No `_legacy/` move, no
big-bang. Each service migrates as its own focused effort:

1. **MVP first** — workflow + identity-stub + observability + CLI to
   functional alpha. This proves the pattern.
2. **Per-service alpha** thereafter — each subsequent service is its own
   focused work item with a narrow freeze on that service's domain during
   the lift.
3. **Cutover per service** — when a service's alpha lands, its v1
   counterpart's call sites switch to v2. The v1 code is deleted in the
   same PR.
4. **End state** — all eight services in v2 alpha. `teleclaude/` is empty
   and deleted. v1 is fully retired.

During transition, v1 and v2 read/write independent storage. v1 SQLite
files coexist with v2 Postgres. Cutover per service includes a one-shot
data migration from v1's storage to v2's Postgres schema. No dual-write,
no shared schemas across the v1/v2 boundary.

### Why Rust specifically

Maurice's chosen reasoning (recorded for future readers):

- **Discipline enforcement.** v1's "convoluted feel" is the cost of
  Python's flexibility. Rust's compiler is the structural answer that
  agents-and-reviewers-being-careful couldn't be.
- **AI writing quality.** Smaller training corpus than Python, but much
  more uniform — the compiler rejects bad code before it can be written.
  Agent iteration loop maps perfectly to compile-fix-recompile.
- **Concurrent workload fit.** Tokio + Postgres MVCC handle the
  multi-writer concurrent reality (many hook events per minute, daemon +
  CLI + TUI all writing) far better than Python with SQLite.
- **Long-running daemon ergonomics.** Single binary, no GC pauses, small
  memory footprint, easy to ship.
- **Industry direction.** Infrastructure tooling is consolidating on
  Rust (Cargo, ripgrep, fd, bat, oxc, biome, turbopack, sqlx, etc.).

### Why Postgres-only

- Real concurrent multi-writer workload demands MVCC. SQLite's
  single-writer serialization is the wrong primitive for our shape.
- Transactional coherence within services — atomic multi-table operations,
  no partial states.
- Single mental model and toolchain. One DB technology, one set of
  patterns, no context-switching.
- Service boundaries enforced by schema ownership without scattering across
  files. Per-project isolation via per-project schemas (`acme_workflow`)
  or `project_id` column.
- Single backup, single observability surface, single tooling story.
- Future-ready for multi-host without rewrite.

The "install one Postgres locally" friction is operational; the
architectural benefits are structural and weigh more.

## Failure modes

- **Local-first not actually local.** A v2 path silently routes through
  daemon HTTP for something the CLI binary could call in-process. Reverts
  v1's CLI-coupled-to-daemon problem under Rust syntax.
- **Daemon re-grows.** v2 daemon accretes responsibilities that should
  live in their own services or worker binaries. Reproduces the gravity
  well.
- **Services reintroducing transports between themselves.** "Workflow
  exposes an HTTP endpoint that agent_runtime calls" — wrong shape. They
  share a crate dependency, not an HTTP layer.
- **Storage tier sprawl.** A service decides it needs "just a small
  SQLite cache" for performance. Reintroduces the fragmented-storage
  failure mode. Postgres-only, always.
- **Dual-transport bus.** Tempting to add a LOCAL fast-path to events
  when Redis costs feel high. The cost is the discipline benefit.
- **Cross-service queries against another service's schema.** Workflow
  reading from identity's tables directly. Same coupling as cross-service
  HTTP, different transport.
- **Authored content drifting into Postgres.** Configs, doc sources, agent
  artifacts ending up in Postgres "for queryability." Authored content
  stays in files; services ingest indexes from files but don't own the
  source.
- **Treating the v2 work as a side effect of features.** Migration must
  be its own dedicated workstream. New features land in v1 until their
  service migrates, then in v2.

## See Also

- docs/project/design/architecture-v2/journey.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/file-layout.md
- docs/project/design/architecture-v2/redesign-list.md
- docs/project/design/architecture-v2/auth-model.md
- docs/project/design/architecture-v2/observability-model.md
- docs/project/design/architecture-v2/event-bus-transports.md
- docs/project/design/architecture-v2/reconstruction-order.md
