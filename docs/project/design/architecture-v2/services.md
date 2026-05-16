---
description: 'The eight services that compose v2 TeleClaude. Each is a Rust crate with a Postgres schema; binaries embed the crates they need.'
id: 'project/design/architecture-v2/services'
scope: 'project'
type: 'design'
---

# Services — Design

## Required reads

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/file-layout.md

## Purpose

Define the eight services that compose v2 TeleClaude — what each owns, what
each explicitly does not own, and how they relate to one another. This is the
service-oriented decomposition that the file layout and transport rules
implement.

## Inputs/Outputs

**Inputs:**

- the v2 target architecture (Rust services-as-crates, Postgres-only)
- the v1 functionality that must be carried forward
- the principle that each service has one purpose, one storage authority, and
  a clear public surface

**Outputs:**

- the list of services
- ownership and non-ownership boundaries for each
- the Postgres schema each service owns
- the cross-service rules that constrain implementation

## Invariants

- **Every service is a Rust library crate** at `crates/<name>/`.
- **Every service has one purpose.** If a description needs too many `and`s,
  it is too broad.
- **Every service owns its Postgres schema.** No other code queries it
  directly. Cross-service data access goes through the service's public
  function surface.
- **Services don't talk to each other via transports.** A service that needs
  another service depends on its crate. Function call, not HTTP.
- **Cross-service coordination uses Redis events.** Loosely coupled
  notification of state changes; not request/response.
- **Workflow runs without daemon dependency.** Local-first invariant: CLI
  embeds workflow and operates against Postgres directly.
- **No service owns business-domain Presentation.** Presentation lives in
  `frontend/` and consumes services via the HTTP API.

## Primary flows

### The eight services

### 1. `identity`

**Owns:**

- people (humans with email + role)
- machine and session principals
- API tokens and boundary credentials
- authentication policy resolution (env, headers, tokens → `Principal`)
- per-service role definitions

**Does not own:**

- session runtime state (lives in `agent_runtime`)
- workflow/todos
- knowledge retrieval
- adapters

**Postgres schema:** `identity`
- `principals`
- `session_tokens`
- `roles` (or hardcoded in the Rust enum if flexibility isn't needed)

**Emits events:** `identity.principal.created`, `identity.token.issued`,
`identity.token.revoked`.

**Why it exists:** Authentication and authorization are cross-cutting but
should not drag the daemon into owning request handling. Identity is a
real service crate that every binary embeds.

See `auth-model.md` for the resolution and authorization flow.

---

### 2. `agent_runtime`

**Owns:**

- agent sessions (the live `Session` entity: tmux name, native session id,
  principal binding, status, last activity, project path, additional
  context)
- tmux orchestration
- agent CLI (Claude / Codex / Gemini) process supervision
- live input/output streaming for active sessions
- current runtime presence and liveness
- adapter binding per session (which UI adapter is attached right now)
- session-related operations (long-running operation receipts)
- per-agent availability state

**Does not own:**

- local project bookkeeping (workflow)
- historical session record (session_ledger)
- knowledge storage
- UI/business logic

**Postgres schema:** `agent_runtime`
- `sessions` (full entity)
- `operations` (durable receipts for long-running operations)
- `availability` (per-agent availability state)

**Emits events:** `agent_runtime.session.started`,
`agent_runtime.session.updated`, `agent_runtime.session.ended`,
`agent_runtime.operation.completed`.

**Subscribes to:** `integration.inbox.agent_hook_*` events emitted by
`integration` when subprocess hook receivers fire. Reacts by updating
session lifecycle state. Does NOT own hook ingestion — the `telec-hook`
binary, payload parsing, and event emission belong to `integration`.
agent_runtime is downstream of integration for inbound signals; the two
services have different change axes (session model vs external CLI
protocol).

**Why it exists:** This is the genuine daemon-shaped part of the system —
processes that must stay alive, observable, and connected. The
`telec-daemon` binary embeds this service in long-running form. The CLI
and TUI also embed it for read queries.

---

### 3. `workflow`

**Owns:**

- todos
- roadmap entries and dependencies
- workflow artifacts (input, PRD, architecture, test specs, implementation
  plan, etc.) — content stored as TEXT columns in Postgres
- workflow state machines (prepare/work/integrate lifecycle)
- local bookkeeping operations

**Does not own:**

- long-running runtime sessions
- transcript ingestion
- web transport concerns
- knowledge retrieval

**Postgres schema:** `workflow` (or per-project schema `<project>_workflow`
for isolation — see file-layout)
- `todos`
- `roadmap`
- `artifacts`
- `state_transitions`

**Emits events:** `workflow.todo.created`, `workflow.todo.updated`,
`workflow.todo.phase_advanced`, `workflow.roadmap.entry_moved`, etc.

**Why it exists:** This is the `telec todo` world. It must work locally,
directly, and transactionally with no daemon dependency for core operations.
The CLI embeds workflow directly.

---

### 4. `session_ledger`

**Owns:**

- canonical session history (the durable record of what happened)
- transcript ingestion and normalization
- deterministic ordering
- session deltas / cursors
- session read models for history and replay

**Does not own:**

- tmux/session runtime lifecycle (agent_runtime)
- workflow/todos
- auth
- documentation curation

**Postgres schema:** `session_ledger`
- `blocks` (canonical event/message blocks)
- `cursors` (consumer state)
- `projections` (read models)

**Emits events:** `session_ledger.block.appended`,
`session_ledger.projection.updated`.

**Why it exists:** Consumers should stop parsing transcript files directly.
The ledger becomes the system of record for session history. Replaces v1
mirrors as a compensating mechanism.

---

### 5. `knowledge`

**Owns:**

- global/company/project knowledge index
- snippet taxonomy
- context selection policy
- progressive disclosure rules
- ingestion pipelines for company and business information

**Does not own:**

- the authored snippet content itself (lives in `docs/` filesystem; this
  service indexes and serves it)
- runtime session streaming
- todo state
- adapter lifecycle

**Postgres schema:** `knowledge`
- `snippets_index` (id, source path, type, scope, domain, last indexed)
- `taxonomy`
- `selection_policy_rules`

**Emits events:** `knowledge.snippet.indexed`,
`knowledge.taxonomy.updated`.

**Why it exists:** Preserves the strongest existing platform idea —
structured, scope-aware, policy-driven context engineering. Not generic
RAG. The `telec docs` commands route through this service.

---

### 6. `integration`

**Owns: ALL inbound from external systems, regardless of transport.**

- **Inbound HTTP webhooks** (Telegram, Discord, WhatsApp, future
  third-party platforms) — receive payload, validate, normalize, emit
  typed event.
- **Inbound subprocess hook receivers** (Claude Code, Codex, Gemini, any
  future agent CLI) — invoked by the agent CLI as a subprocess; reads
  payload from stdin, validates, normalizes, emits typed event. The
  `telec-hook` binary is integration's subprocess entry point.
- **Outbox/inbox patterns** for at-least-once durable external delivery
  (notifications going OUT to Telegram, etc.).
- **Retries and dead-letter behavior** for both inbound and outbound.
- **Async work dispatch** to workers.
- **Worker process supervision spec** (the daemon spawns workers per this
  service's definitions).

The principle: **anything coming from outside our system is integration's
domain.** Same code path whether the transport is HTTP, subprocess, or
anything future. Domain services subscribe to the events integration
emits — they don't deal with transport.

**Does not own:**

- domain business rules themselves (each domain service owns its rules)
- local workflow state
- long-lived session orchestration (agent_runtime owns sessions; it
  subscribes to `integration.inbox.agent_hook_*` events to react to
  agent lifecycle signals)

**Postgres schema:** `integration`
- `outbox` (outbound external deliveries)
- `inbox` (inbound events from webhooks and subprocess hooks alike)
- `dlq` (dead-letter)
- `worker_state`

**Emits events:** `integration.outbox.appended`,
`integration.outbox.delivered`, `integration.outbox.dead_lettered`,
`integration.inbox.received`, `integration.inbox.agent_hook_received`
(or per-hook-type channels like `integration.inbox.session_start`).

**Binary entry points:**
- `telec-hook` — subprocess entry point for agent CLI hooks. Reads stdin,
  calls into `integration` crate, exits. Registered with Claude Code etc.
- `telec-api` (or `telec-daemon`) — HTTP server that hosts webhook routes
  dispatching to `integration` crate functions.

**Why it exists:** Anything that crosses restart boundaries or comes from
external systems needs durable handoff. This service turns side effects
and inbound signals into a reliable system instead of a chain of
in-process calls.

See `transport-rules.md` for the change-axis heuristic that places ALL
inbound here (versus splitting hooks into `agent_runtime` based on
domain-semantic similarity, which was the wrong cut).

---

### 7. `config`

**Owns:**

- configuration model (global, project, person overlays)
- effective-config computation
- config validation and versioning

**Does not own:**

- identity policy semantics (identity owns this)
- workflow state
- knowledge content itself

**Postgres schema:** `config` (optional; see note below)
- `effective_config_snapshots` (only if history is needed)

**Note on storage:** Configs are authored content (`teleclaude.yml`,
`config.yml`, `.env`). Config service reads from filesystem at startup and
computes effective config. Postgres is used only if effective-config
history matters — otherwise the service is stateless and config lives only
in YAML.

**Emits events:** `config.effective.updated` (when overlays change).

**Why it exists:** Configuration is too central to leave as scattered files
and ad hoc loader logic. The service centralizes overlay resolution and
validation.

---

### 8. `agent_artifacts`

**Owns:**

- agent artifact source manifest (commands, skills, agent files in
  `agents/`)
- inflation rules (e.g., `AGENTS.master.md` → `AGENTS.md`)
- distribution to deployed runtime directories (`~/.claude/`, `~/.codex/`,
  `~/.gemini/`)
- the `telec sync` operation

**Does not own:**

- the authored artifact content itself (lives in `agents/` filesystem)
- knowledge retrieval policy
- workflow/todo state
- session runtime orchestration
- presentation logic

**Postgres schema:** **none.** This service is filesystem-driven. Source is
in `agents/`, deployed output is on disk under `~/.<agent>/`, build/inflation
outputs land in `dist/`. There is no business state that survives a `telec
sync` and isn't already encoded in filesystem + git.

If inflation caching becomes expensive enough to justify a cache, that
cache goes in Redis (or `.cache/` on disk), not Postgres.

**Emits events:** `agent_artifacts.synced` (after `telec sync` completes).

**Why it exists:** The artifact system is too important to remain homeless.
It is adjacent to knowledge but not the same — knowledge owns retrieval
policy over authored content; artifacts owns how agent-facing deliverables
are built, packaged, and published.

---

### Cross-cutting infrastructure crates (not services)

These live at `crates/` alongside the services but are **infrastructure**,
not bounded domains. Services and binaries depend on them.

- `observability` — `tracing` wrapper writing `instrukt_ai_logging` format.
  See `observability-model.md`.
- `event_bus` — Redis pub/sub + streams wrapper. Single transport per
  `event-bus-transports.md`.
- `storage` — `sqlx::PgPool` helpers, migration runner.
- `state_machine` — generic state-machine engine; services define their own
  machines using this.
- `shared` — primitive types (`SessionId`, `Slug`, `ProjectId`, etc.).

### Binary composition

The fixed set of v2 binaries:

| Binary | Embeds (typical) | Purpose |
|---|---|---|
| `telec` | workflow, identity, config, knowledge, observability | CLI |
| `telec-tui` | workflow, agent_runtime, identity, observability, event_bus (subscriber) | TUI |
| `telec-daemon` | agent_runtime, identity, integration, event_bus, observability | Long-running supervisor |
| `telec-api` | all services (read-mostly), identity, observability | HTTP API for browser |
| `worker-<name>` | the service crate it serves (e.g. integration), event_bus, observability | Per integration's outbox/inbox workers |

Each binary embeds exactly what it needs. No more, no less. Multiple
binaries embed the same service crate — that's fine; they don't share
in-memory state because state lives in Postgres.

### Storage ownership map

One local Postgres instance. Schema per service:

| Service | Schema | Notes |
|---|---|---|
| `identity` | `identity` | |
| `agent_runtime` | `agent_runtime` | |
| `workflow` | `workflow` (or `<project>_workflow`) | Per-project isolation: see file-layout |
| `session_ledger` | `session_ledger` | Large transcript data; TOAST handles blobs |
| `knowledge` | `knowledge` | Index only; sources in `docs/` filesystem |
| `integration` | `integration` | Outbox/inbox/dlq |
| `config` | `config` (optional, for history only) | Otherwise stateless |
| `agent_artifacts` | **none** | Filesystem-driven |

Single Postgres, clean ownership, no fragmentation.

### Cross-service interaction rules

- **Service A needs service B's data (read).** A calls a public function on
  B's crate. Example: `workflow::list_todos(...)` called from inside
  `telec-api`'s HTTP handler.
- **Service A needs to react to service B's state changes.** A subscribes
  to B's Redis event channel. Example: a worker subscribes to
  `workflow.todo.created` to send a notification.
- **Service A needs service B's persistent state directly.** Never. A
  never queries B's Postgres schema. Always goes through B's crate.
- **Two services share data that doesn't fit either.** Surface the
  question; usually a new service or a cleaner ownership split. Don't
  paper over with shared-schema access.

### What's intentionally left out

- **Presentation context.** The v2 docs originally listed a Presentation
  bounded context (CRM, marketing, admin, support, public). That's the
  `frontend/` Next.js app, evolved separately from the Rust backend. It
  consumes the v2 services via `telec-api`'s HTTP surface. Not a service in
  this list.

## Failure modes

- **A service description grows too broad.** "Workflow owns todos and
  sessions and history and notifications..." — too many `and`s, split it.
- **A service queries another service's schema directly.** Same coupling
  as cross-service HTTP, just via SQL. Forbidden. Use the owning service's
  crate.
- **Workflow gains a daemon dependency.** Any path where `telec todo list`
  needs the daemon up is a regression. Workflow must run from the CLI
  binary embedding only the workflow crate + Postgres.
- **agent_runtime grows to host other services.** It owns sessions. It
  doesn't own todos. It doesn't own auth. It doesn't own webhooks. Each
  has its own service.
- **Knowledge owns the snippet content.** It indexes content authored in
  `docs/`. The files are the source of truth; the index is derived. Don't
  invert this.
- **agent_artifacts gains a Postgres schema.** Speculative — added once,
  reverted. The service is filesystem-driven. If a schema appears here,
  the addition needs to justify itself against the "no business state to
  persist" criterion.
- **Integration becomes "the place miscellaneous logic goes."** It owns
  webhook ingestion, outbox/inbox, retries, workers. It does not own
  domain logic; it owns the durability and delivery machinery around
  domain events.

## See Also

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/file-layout.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/auth-model.md
- docs/project/design/architecture-v2/observability-model.md
- docs/project/design/architecture-v2/event-bus-transports.md
- docs/project/design/architecture-v2/redesign-list.md
