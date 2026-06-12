---
description: 'The services that compose v2 TeleClaude. Each is a Rust crate with a clear storage posture; binaries embed the crates they need.'
visibility: 'public'
---

# Services — Design

## Required reads

- @docs/project/design/architecture-v2/overview.md
- @docs/project/design/architecture-v2/transport-rules.md
- @docs/project/design/architecture-v2/file-layout.md

## Purpose

Define the nine services that compose v2 TeleClaude — what each owns, what
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

### The services

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
- historical session record (session_mirrors)
- knowledge storage
- UI/business logic

**Postgres schema:** `agent_runtime`

- `sessions` (full entity)
- `operations` (durable receipts for long-running operations)
- `availability` (per-agent availability state)

**Emits events:** `agent_runtime.session.started`,
`agent_runtime.session.updated`, `agent_runtime.session.ended`,
`agent_runtime.operation.completed`.

**Owns agent CLI hook reception directly.** The `telec-hook` binary, its IPC delivery to the daemon, the HookReceiver windowed-batch-write, and the LISTEN/NOTIFY dispatch pattern all live here. Per the change-axis test: agent CLI hooks change when agent CLI protocols change, which is agent_runtime's axis (we control the agent CLIs we supervise). Truly external HTTP webhooks (Telegram, GitHub, etc.) remain `integration`'s domain.

**Subscribes to:** `integration.inbox.received` for external messaging routed to sessions (e.g., Telegram inbound). NOT for agent CLI hooks (those bypass integration entirely).

**Why it exists:** This is the genuine daemon-shaped part of the system —
processes that must stay alive, observable, and connected. The
`telec-daemon` binary embeds this service in long-running form. The CLI
and TUI also embed it for read queries.

---

### 3. `workflow`

**Owns:**

- todos
- roadmap entries and dependencies
- workflow artifacts (input, PRD, architecture, implementation
  plan, etc.) — content stored as TEXT columns in Postgres
- workflow state machines (prepare/work/integrate lifecycle)
- local bookkeeping operations
- integration delivery calls into context docs-authority to reconcile
  `delivered_by` during delivery so snippet flips are staged in the
  squash-merge commit

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

### 4. `session_mirrors`

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

**Postgres schema:** `session_mirrors`

- `blocks` (canonical event/message blocks)
- `cursors` (consumer state)
- `projections` (read models)

**Emits events:** `session_mirrors.block.appended`,
`session_mirrors.projection.updated`.

**Why it exists:** Consumers should stop parsing transcript files directly.
The ledger becomes the system of record for session history. Replaces v1
mirrors as a compensating mechanism.

---

### 5. `context`

**Owns:**

- ALL filesystem-driven context engineering: docs (snippets), skills,
  commands, and agent files (AGENTS.master.md, addenda)
- Per-kind validation against schemas
- Inflation (e.g., `AGENTS.master.md` → `AGENTS.md` with addendum merging)
- Distribution / deployment to agent runtime directories
  (`~/.claude/`, `~/.codex/`, `~/.gemini/`)
- `telec context sync` operation (replaces v1 `telec sync` docs portion)
- docs-authority operations for serialized structural writes to `docs/`
- file watching for authored docs source and debounce-triggered sync
- sync triggering after external docs edits, with manual sync retained as
  an escape hatch
- Selection policy as a pure function
- CRUD CLI per kind: `telec context docs|skills|commands|agents
list/get/create/update/delete`

**Does not own:**

- the authored source content itself (lives in git under `docs/` and
  `agents/`/`.agents/`; this service indexes, validates, deploys)
- runtime session streaming
- todo state
- adapter lifecycle
- HTTP integration

**Postgres schema:** NONE. Filesystem-driven. State lives in git
(source) + filesystem (deployed). The index is a pre-computed YAML at
`~/.teleclaude/docs/index.yaml` produced by sync.

**Emits events:** NONE. Filesystem-driven; no event-bus participation as
a source. The act of `git commit` + `telec context sync` is the implicit
"context changed" signal.

**Why it exists:** v1 had two services (`knowledge` for docs, separately
`agent_artifacts` for skills/commands/agents) that shared the same change
axis — file-based context engineering. v2 folds them. The "context"
naming captures both static reference (docs) AND invokable capability
(skills/commands/agents), which is what "context engineering" means in
the AI sense.

**v2 fold:** The previous v1 split (knowledge + agent_artifacts) was
artifactual — both contexts had the same change axis (file-based
inflation + deployment to agent runtimes). The fold reduces the service
count from 8 to 7 architectural pieces, then re-rises to 8 with the
addition of `memory` as a distinct service.

---

### 6. `integration`

**Owns: ALL inbound from external systems, regardless of transport.**

- **Inbound HTTP webhooks** (Telegram, Discord, WhatsApp, future
  third-party platforms) — receive payload, validate, normalize, emit
  typed event.
- **Outbox/inbox patterns** for at-least-once durable external delivery
  (notifications going OUT to Telegram, etc., and inbound webhooks).
- **Retries and dead-letter behavior** for both inbound and outbound.
- **Async work dispatch** to workers (outbox dispatchers, per-provider).
- **Worker process supervision spec** (the daemon spawns workers per this
  service's definitions).

The principle (refined): **anything coming from systems we DO NOT control
is integration's domain.** External providers (Telegram, GitHub) are
systems we don't control — their protocols change at their pace. Agent
CLIs are systems we DO control (we supervise, configure, deploy) — they
belong to `agent_runtime`. The change-axis test, not the "is it
subprocess vs HTTP" transport question, decides ownership.

**Does not own:**

- domain business rules themselves (each domain service owns its rules)
- local workflow state
- agent CLI hook reception (that's `agent_runtime`'s domain — the
  `telec-hook` binary is owned by agent_runtime, not integration)
- long-lived session orchestration (agent_runtime owns sessions)

**Postgres schema:** `integration`

- `outbox` (outbound external deliveries)
- `inbox` (inbound events from EXTERNAL HTTP webhooks; agent CLI hooks
  bypass this — they go direct to agent_runtime)
- `dlq` (dead-letter)
- `worker_state`

**Emits events:** `integration.outbox.appended`,
`integration.outbox.delivered`, `integration.outbox.dead_lettered`,
`integration.inbox.received` (external webhook arrivals).

**Binary entry points:**

- `telec-api` (or `telec-daemon`) — HTTP server that hosts webhook routes
  dispatching to `integration` crate functions.
- Per-provider outbox dispatcher workers (spawned by the daemon).

**Why it exists:** Anything that crosses restart boundaries from genuinely
external systems needs durable handoff. The inbox + outbox patterns give
audit + replay for business events that we cannot replay from upstream.

See `transport-rules.md` for the change-axis heuristic. The corrected v2
placement puts agent CLI hooks in `agent_runtime` (we control them) and
external webhooks here (we don't control them).

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

### 8. `memory`

**Owns:**

- durable observations agents store and query (gotchas, decisions,
  patterns, preferences, relationships, facts)
- full-text search over observations
- timeline queries (around an anchor observation)
- per-principal authorship + per-project optional scoping
- CLI surface: `telec memory list/search/save/delete/update/timeline`

**Does not own:**

- session transcripts (`session_mirrors`)
- context content (`context`)
- workflow state
- adapter lifecycle

**Postgres schema:** `memory`

- `observations` — own UUID, type, title, body, author principal,
  project_slug (nullable), anchor_id (nullable), timestamps
- Full-text index on (title || body) for search

**Emits events:** `memory.observation.saved`, `memory.observation.deleted`.

**Why it exists:** v1's `teleclaude/memory/` already exists; v2 ports it
to Rust + Postgres with cleaner CRUD surface. Memory is distinct from
session_mirrors (per-fact vs per-session-text) and from context
(observed vs authored). The third pillar of "things the platform
remembers": context = static reference; mirrors = session history;
memory = curated observations.

**Mining:** No internal mining. Memory miner is an intelligence agent
running OUTSIDE this context — consumes `agent_runtime.extract-window`,
writes via `telec memory save`. See `transport-rules.md` "Cross-cutting
concerns via intelligence + shared utilities + CLI" for the pattern.

---

### 9. `reconciliation`

**Owns:**

- installation desired-state convergence
- channel-gated self-update policy
- exactly-once applied-version state
- ordered convergence runs
- fleet capability-map materialization from heartbeat advertisements

**Does not own:**

- external webhook ingress or provider protocols (`integration`)
- peer identity/version/capability truth beyond consuming heartbeat advertisements
- per-aggregate data upcasting owned by each domain
- v1 deployment paths during the migration window

**Postgres schema:** NONE in this slice. The applied-version ledger and run history use a local store under `TELECLAUDE_HOME`; the Postgres schema is deferred to the v2 cutover while every node still needs the loop.

**Emits events:** `reconciliation.installation.drift_detected`,
`reconciliation.installation.converged`, `reconciliation.convergence.failed`.

**Subscribes to:** `integration.inbox.received` for the release/version subset.
Config drift is re-evaluated by the loop's own self-check interval because
`config.effective.updated` is reserved and not emitted.

**Why it exists:** every installation evaluates release visibility against its
own channel policy and converges itself exactly once per target version while
remaining safe in a deliberately mixed-version fleet.

---

### 9. `reconciliation`

**Owns:**

- desired-state convergence for the local installation (version per channel,
  installation-level structural migration, process health)
- the channel-gated self-update control loop, mounted as a `ServiceLoop` on
  the `telec-daemon` seam and running on every node
- exactly-once application of a target version, and `ConvergenceRun` history
  retained for operator inspection
- the fleet capability map view it materializes from the cluster heartbeat,
  and the in-code feature-ID registry that gates cross-node behavior

**Does not own:**

- foreign-protocol ingress or transport (`integration` terminates and relays
  external webhooks; reconciliation only subscribes to the relayed event)
- per-aggregate data evolution (each domain owns its own upcasters)
- agent-artifact distribution (`context`) or product lifecycle (`workflow`)

**Postgres schema:** none yet. The loop runs on every node — including nodes
that have not provisioned v2 Postgres — so for this slice the exactly-once
applied-version record and `ConvergenceRun` history live in a lightweight
local store, mirroring the v1 deployment status/migration-ledger pattern.
The Postgres `reconciliation` schema is an intentional deferral to the v2
cutover; standing it up now would couple self-update to a store that
`make install` does not yet provision, violating the run-on-every-node
invariant.

**Emits events:** `reconciliation.installation.drift_detected`,
`reconciliation.installation.converged`, `reconciliation.convergence.failed`,
`reconciliation.capability.advertised` (the last rides the cluster heartbeat).

**Subscribes to:** `integration.inbox.received` (release/version subset,
relayed by the single ingress). Each node decides independently; the ingress
relays unconditionally. Desired-state config inputs (`channel`, `pinned_minor`)
are re-read on the loop's periodic self-check; the `config.effective.updated`
event-driven path is deferred until a producer exists (the event is reserved,
not yet emitted).

**Cross-runtime window note.** During v1→v2 the feature-ID capability map and
the heartbeat that carries it are delivered in v1 Python. The v2 loop does not
call into v1: it reads the same cluster heartbeat from Redis and materializes
its own capability view, honoring the reconciliation invariant that the
heartbeat is the single source of fleet identity/version/capabilities and no
separate distribution path exists.

**Why it exists:** ADR-0024 makes fleet convergence its own bounded context,
separate from `integration`'s foreign-protocol boundary. The control loop is
the actuator that v1's never-functional deployment plumbing lacked.

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

| Binary      | Embeds (typical)                                                         | Purpose |
| ----------- | ------------------------------------------------------------------------ | ------- |
| `telec`     | workflow, identity, config, knowledge, observability                     | CLI     |
| `telec-tui` | workflow, agent_runtime, identity, observability, event_bus (subscriber) | TUI     |

| `telec-daemon` | agent_runtime, identity, integration, reconciliation, event_bus, observability | Long-running supervisor |

| `telec-api` | all services (read-mostly), identity, observability | HTTP API for browser |
| `worker-<name>` | the service crate it serves (e.g. integration), event_bus, observability | Per integration's outbox/inbox workers |

Each binary embeds exactly what it needs. No more, no less. Multiple
binaries embed the same service crate — that's fine; they don't share
in-memory state because state lives in Postgres.

### Storage ownership map

One local Postgres instance. Schema per service:

| Service           | Schema                                | Notes                                                                                                           |
| ----------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------- | --- | ---- |
| `identity`        | `identity`                            |                                                                                                                 |
| `agent_runtime`   | `agent_runtime`                       | Includes `sessions`, `operations`, `availability`, `extractor_cursors` (source-side cursor table for consumers) |
| `workflow`        | `workflow` (or `<project>_workflow`)  | Per-project isolation: see file-layout                                                                          |
| `session_mirrors` | `session_mirrors`                     | Flat text per session; TOAST handles large content; built incrementally by session_history consumer             |
| `context`         | **none**                              | Filesystem-driven (docs + skills + commands + agents); index file at `~/.teleclaude/docs/index.yaml`            |
| `integration`     | `integration`                         | Outbox/inbox/dlq — for true external webhooks only                                                              |
| `config`          | `config` (optional, for history only) | Otherwise stateless                                                                                             |
| `memory`          | `memory`                              | Observations with full-text index on title                                                                      |     | body |

| `reconciliation` | **none** | Local applied-version ledger under `TELECLAUDE_HOME`; Postgres deferred until v2 cutover |

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

### Complete v1 footprint per service (for cutover safety)

Before any service's authoritative cutover, the build worker MUST verify
every v1 path that touches that service's data is migrated together. See
`reconstruction-order.md` "What makes a cutover safe" for the trap and
checklist. This section maintains the per-service footprint inventory.

**Add a service's footprint to this section when planning its cutover.**
Future service migrations grep here first. Incomplete footprint blocks
authoritative cutover; defer to parallel-capable instead.

#### `workflow` (mapped 2026-05-16 during MVP I1)

Complete v1 footprint for workflow data (todos, roadmap, artifacts,
state machines):

- **CLI handlers** — `teleclaude/cli/telec/handlers/todo.py`
- **HTTP API** — `teleclaude/api/todo_routes.py` (~25 calls to
  `todos_db.*` functions; backs the browser-facing API)
- **TUI direct reads** — `teleclaude/cli/tui/widgets/todo_row.py`,
  `teleclaude/cli/tui/views/preparation_actions.py`
- **Internal service callers** —
  - `teleclaude/core/integration/*`
  - `teleclaude/core/operations/service.py`
  - `teleclaude/core/roadmap.py`
- **Orchestrator** — all 20+ files under `teleclaude/core/next_machine/`
  (drives `/next-prepare`, `/next-build`, `/next-finalize` etc. — the
  build session running ANY workflow todo references these)
- **Storage** — `teleclaude/core/todos_db/` (all of it),
  `{project}/.teleclaude/todos.db` (SQLite, one per project)

**MVP cutover status:** deferred (parallel-capable shipped). Authoritative
cutover requires migrating ALL of the above together. Likely sequence:
agent_runtime + integration + knowledge migrate first; the orchestrator
becomes v2-callable; THEN workflow can cut over because the orchestrator
won't depend on v1 paths anymore.

#### `identity` (to map during v2-spine-completion)

Initial inventory from grep (refine during spine-completion):

- **Resolution sources** — `teleclaude/session_identity.py`,
  `teleclaude/core/session_bootstrap.py`, `teleclaude/api_server.py`,
  `teleclaude/cli/telec/auth.py` (if exists)
- **Token storage** — `teleclaude/core/db/_tokens.py`,
  `teleclaude/core/db/_sessions.py`
- **Models** — `teleclaude/core/db_models.py`,
  `teleclaude/core/models/_session.py`
- **Per-person config** — `~/.teleclaude/people/<name>/teleclaude.yml`
- **CLI auth surface** — `teleclaude/cli/telec/handlers/auth.py` (if
  exists), `telec auth login/whoami/logout` commands
- **HTTP middleware** — `teleclaude/api/session_access.py` (header
  parsing: `x-session-token`, `x-caller-session-id`, `x-tmux-session`,
  `x-telec-email`)
- **Schema** — `teleclaude/core/schema.sql` (identity-related tables)
- **Storage** — `~/.teleclaude/teleclaude.db` (principals, tokens),
  `~/.teleclaude/people/` (per-person config files)

**Spine-completion approach:** identity v2 service is built and exists
parallel to v1. Authoritative cutover is its own future todo with the
full footprint above migrated together.

#### `config` (to map during v2-spine-completion)

Initial inventory:

- **Loader** — `teleclaude/config/__init__.py` (and submodules)
- **Schema** — `teleclaude/config/schema.py` (Pydantic models for
  validation)
- **Consumers** — broad surface; ~30+ files import `teleclaude.config`
  for various settings (database paths, redis URL, daemon socket path,
  etc.). Examples: `daemon.py`, `api_server.py`,
  `transport/redis_transport/`, `core/cache.py`, `core/identity.py`,
  `core/conversation_delivery.py`, etc.
- **Storage** — YAML files: `~/.teleclaude/teleclaude.yml` (global),
  `<project>/teleclaude.yml` (per-project), `~/.teleclaude/people/<name>/teleclaude.yml`
  (per-person overlays), `.env` for secrets

**Spine-completion approach:** config v2 service is built and exists
parallel. v1 consumers continue to use `teleclaude.config`. Future
cutover migrates v1 consumers to read effective config from v2 service.

#### Remaining services — footprint mapping deferred to each migration

`agent_runtime`, `session_mirrors`, `context`, `integration`,
`agent_artifacts` — full v1 footprints get mapped here during planning
of each service's migration. The cutover safety checklist in
`reconstruction-order.md` references this section.

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
