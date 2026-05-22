---
description: 'Concrete shape of the v2 MVP: workflow service + Rust CLI + Postgres + observability + identity stub + Redis bridge to v1. The first cutover proves the v2 pattern.'
id: 'project/design/architecture-v2/mvp-shape'
scope: 'project'
type: 'design'
visibility: 'public'
---

# MVP Shape — Design

## Required reads

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/file-layout.md
- docs/project/design/architecture-v2/reconstruction-order.md

## Purpose

Pin the concrete deliverable of the v2 MVP. After this lands, the v2
machinery (workspace, infrastructure crates, identity stub, workflow
service, CLI, Postgres, Redis bridge, observability, cutover tooling)
exists and works end-to-end for the workflow domain. Every subsequent
service migration uses the same pattern.

This doc is the contract the MVP todo's PRD/plan/build is built against.

## Inputs/Outputs

**Inputs:**

- the v2 architecture (services as crates, Postgres-only, single Redis
  transport, observability, identity)
- the v1 codebase that must keep shipping during MVP build
- the principle: migration is dedicated workstream, not smeared across
  features
- the Redis-bridge pattern for v1↔v2 coexistence (see transport-rules)

**Outputs:**

- explicit scope (in/out of MVP)
- task DAG with parallelization plan for team-mode execution
- per-task deliverables and acceptance criteria
- cutover process
- success definition

## Invariants

- **MVP delivers ONE service cutover.** Workflow. Not all services.
  Other services stay v1 until their wave.
- **v1 keeps running throughout MVP build.** Daemon, TUI, hooks,
  webhooks, sessions — all unchanged. Only the workflow code paths
  cut over at the end.
- **No dual-write at any point.** Pre-cutover: v1 owns workflow data
  in SQLite. Post-cutover: v2 owns workflow data in Postgres. Switch is
  atomic in the cutover PR.
- **Redis is the v1↔v2 bridge.** v1 daemon subscribes to v2 workflow
  events (post-cutover) to refresh its TUI cache. No other inter-version
  communication.
- **Tasks decompose for parallel execution.** Multiple agents can work
  concurrently on independent crates. The DAG is explicit.

## Primary flows

### What MVP delivers

**Rust workspace at `crates/`** containing:

- `crates/shared/` — primitive types (`Slug`, `ProjectId`, `TodoId`,
  time helpers).
- `crates/observability/` — `tracing` wrapper emitting `instrukt_ai_logging`
  format to `/var/log/instrukt-ai/teleclaude/<source>.log`.
- `crates/storage/` — `sqlx::PgPool` builder, migration runner helpers.
- `crates/event_bus/` — Redis Streams + pub/sub wrapper. Single
  transport contract. Idempotency-key support.
- `crates/identity/` — single-user stub. `resolve_from_env()` returns
  `Principal::Human { email: from-config, role: Owner }`. Full
  implementation deferred to Wave 2.
- `crates/workflow/` — full workflow service:
  - Postgres `workflow` schema with migrations (todos, roadmap,
    artifacts, state_transitions)
  - Domain models (`Todo`, `RoadmapEntry`, `Artifact`, `LifecyclePhase`)
  - State machine (lifecycle phase transitions)
  - Service struct with CRUD + state-machine operations
  - Events module (`workflow.todo.*`, `workflow.roadmap.*`)
  - Integration tests against public API via `sqlx::test`
- `crates/telec-cli/` — CLI binary:
  - `telec todo list|show|create|update|delete|move|freeze|unfreeze`
  - `telec migrate-workflow-v1` — one-shot data migration command
  - Embeds workflow + identity + observability crates
  - Constructor-injected services in `main()`

**Postgres setup:**

- `docker-compose.yml` at repo root: Postgres 17 + Redis 7, named
  volumes for persistence.
- `make pg-up` / `make pg-down` / `make pg-reset` targets.
- Connection config via `DATABASE_URL` env var (`postgres://localhost/teleclaude`
  default).

**Data migration tool** (`telec migrate-workflow-v1`):

- Reads v1 `{project}/.teleclaude/todos.db` for the current project.
- Writes rows to Postgres `workflow` schema.
- Idempotent (re-runnable).
- Records migration completion in `workflow.migrations_v1` table.

**v1 daemon Redis bridge** (small Python addition):

- v1 daemon subscribes to `workflow.todo.*` and `workflow.roadmap.*`
  Redis channels.
- On event, daemon refreshes its in-memory cache and pushes WebSocket
  update to TUI (existing mechanism).
- This is a small Python-side change (~30 lines) added in the cutover PR
  so v1 TUI displays v2-managed todos transparently.

**Cutover (in the same PR as data migration):**

- Run `telec migrate-workflow-v1` for each registered project.
- Delete v1 Python paths: `teleclaude/core/next_machine/`,
  `teleclaude/core/todos_db/`, and `teleclaude/cli/telec/handlers/todo.py`.
- Replace v1 `telec todo *` dispatch with
  invocation of the Rust `telec-cli` binary (shim in v1 CLI, or
  install-time symlink replacement).
- v1 daemon's todo-related cache code paths deprecated; cache fed by
  Redis subscription instead.

### What MVP does NOT include

Explicitly out of scope so the prepare worker doesn't expand:

- Rust TUI (`telec-tui`). v1 TUI continues; sees v2 todos via Redis bridge.
- Rust daemon (`telec-daemon`). v1 Python daemon continues.
- Rust HTTP API (`telec-api`). v1 daemon's HTTP API continues for browser.
- `telec-hook` binary. v1 Python hook receiver continues.
- Webhook receivers in Rust. v1 Python webhook handlers continue.
- Other services: `agent_runtime`, `session_mirrors`, `context`,
  `integration` (full), `config` (full), `agent_artifacts`. All stay v1.
- Full identity service. Only single-user stub in MVP.
- Frontend changes. `frontend/` Next.js untouched.

### Task DAG (for parallel execution in team mode)

Tasks are grouped into waves; within a wave, tasks listed in parallel
run concurrently on separate worker sessions. Between waves, dependencies
must complete first.

```
Wave A — Foundation (1 agent sequential, ~30 min)
  A1: Workspace bootstrap
      - Cargo.toml workspace, rust-toolchain.toml, .gitignore additions
      - Empty crate dirs created
      - docker-compose.yml for Postgres + Redis
      - Makefile additions (pg-up, pg-down, build, test)
      - Acceptance: `cargo check` succeeds against empty workspace

Wave B — Infrastructure crates (3 agents parallel)
  B1: crates/shared/
      - Primitive types: Slug, ProjectId, TodoId, timestamp helpers
      - All pub re-exported from lib.rs
      - Unit tests colocated
      - Acceptance: `cargo test -p shared` passes
  B2: crates/observability/
      - tracing-subscriber configured to write JSON Lines matching
        instrukt_ai_logging format to /var/log/instrukt-ai/teleclaude/<source>.log
      - pub fn init(source: &str)
      - Acceptance: `cargo test -p observability` passes; smoke test
        writes a sample event to log file in expected format
  B3: crates/event_bus/
      - Redis client wrapper using `redis` crate with tokio-comp
      - EventEnvelope type, emit(envelope) async fn
      - subscribe(channel_pattern) returning a Stream
      - Idempotency key tracking (handler success cache)
      - Acceptance: `cargo test -p event_bus` passes; integration
        test using docker-compose Redis publishes and receives event

Wave C — Storage + Identity (2 agents parallel)
  C1: crates/storage/
      - PgPool builder with config-driven URL
      - Migration runner helper using sqlx::migrate!()
      - Acceptance: `cargo test -p storage` passes; smoke test
        connects to docker-compose Postgres
  C2: crates/identity/
      - Single-user stub: resolve_from_env() returns Principal::Human
        with email from config / env
      - Principal enum + Role enum
      - Acceptance: `cargo test -p identity` passes

Wave D — Workflow service internals (4 agents parallel)
  D1: crates/workflow/migrations/0001_init.sql
      - Schema: workflow.todos, workflow.roadmap, workflow.artifacts,
        workflow.state_transitions, workflow.migrations_v1
      - Foreign keys, indexes, enum types for LifecyclePhase
      - Acceptance: migration applies cleanly to fresh Postgres
  D2: crates/workflow/src/models.rs + src/errors.rs
      - pub Todo, RoadmapEntry, Artifact, LifecyclePhase, kind/state enums
      - WorkflowError (thiserror-based)
      - Acceptance: types compile, derive serde/sqlx where needed
  D3: crates/workflow/src/events.rs
      - pub event schemas: TodoCreated, TodoUpdated, TodoPhaseAdvanced,
        RoadmapEntryMoved, etc.
      - Channel name constants
      - Acceptance: schemas compile, serde round-trips
  D4: crates/workflow/src/state_machine.rs
      - Pure function: next_lifecycle_phase(current, signal)
      - Full unit-test coverage of every transition
      - Acceptance: `cargo test` covers all transitions

Wave E — Workflow service composition (1 agent, depends on D)
  E1: crates/workflow/src/service.rs + storage internals
      - WorkflowService struct, ::new(pool, event_bus, identity)
      - CRUD: list, get, create, update, delete
      - State-machine ops: advance_phase, etc.
      - Event emission on every mutation
      - Roadmap ops: add, move, freeze, unfreeze
      - Acceptance: integration tests via sqlx::test covering all
        public API; events emitted correctly

Wave F — CLI binary (1 agent, depends on E)
  F1: crates/telec-cli/
      - main.rs: observability::init, config load, workflow service
        construction, clap-derive dispatch
      - Subcommand module: todo.rs
      - All operations from v1 `telec todo` commands
      - Acceptance: full CLI smoke test against docker-compose Postgres;
        all commands work, events fire to Redis

Wave G — Data migration tool (1 agent, parallel with F)
  G1: telec migrate-workflow-v1 subcommand in crates/telec-cli/
      - Reads v1 todos.db for the current project
      - Writes to Postgres workflow schema
      - Idempotent: skips already-migrated todos
      - Acceptance: smoke test on a copy of real v1 todos.db produces
        identical-shape data in Postgres

Wave H — v1 daemon Redis bridge (1 agent, Python, parallel with E-G)
  H1: Python: subscribe to workflow.* Redis channels in v1 daemon
      - Add Redis subscriber to teleclaude/daemon.py
      - On workflow.todo.* events, invalidate daemon cache, push WS
      - Acceptance: smoke test — emit a workflow.todo.created event
        from CLI; v1 TUI refreshes within 1s

Wave I — Cutover (1 agent, sequential, depends on ALL above)
  I1: Cutover PR
      - Run telec migrate-workflow-v1 for each project
      - Delete v1 paths: teleclaude/core/next_machine/, todos_db/,
        cli/telec/handlers/todo.py
      - Replace v1 telec todo dispatch with telec-cli invocation
      - Verify: v1 TUI displays v2-managed todos via Redis bridge
      - Verify: all v1 todo surfaces still work end-to-end
      - Acceptance: full smoke test of telec todo commands;
        TUI updates live; no regressions in v1 features
```

### Parallelization summary

Maximum-parallelism schedule:

- Wave A: 1 agent (~30 min)
- Wave B: 3 agents concurrent (~1 hour)
- Wave C: 2 agents concurrent (~30 min)
- Wave D: 4 agents concurrent (~1-2 hours)
- Wave E: 1 agent (~1-2 hours)
- Wave F + G + H: 3 agents concurrent (~1-2 hours)
- Wave I: 1 agent (~1 hour)

**Calendar time at maximum parallelism: roughly half a working day to
a day** for an experienced team-mode execution. Sequential would be
2-3 working days.

### Success criteria

The MVP is done when ALL of these hold:

1. `cargo build --release --workspace` succeeds without warnings.
2. `cargo test --workspace` passes (unit + integration tests).
3. `cargo clippy --all-targets -- -D warnings` passes.
4. `make pg-up` brings up Postgres + Redis; `cargo run --bin telec-cli
-- todo list` succeeds (returns empty list).
5. `telec todo create my-test "<input>"` creates a todo in Postgres
   workflow schema; emits `workflow.todo.created` to Redis.
6. v1 TUI (running unchanged) displays the new todo after the daemon
   receives the Redis event.
7. `telec migrate-workflow-v1` migrates a real v1 `todos.db` for a
   project; all rows visible via `telec todo list`.
8. After cutover PR merges: v1's `telec todo`
   commands route to v2; all behaviors preserved; v1 TUI continues
   working unchanged for non-workflow concerns.
9. No regression in v1 features (sessions, hooks, webhooks, Telegram,
   etc. all unaffected).
10. Daemon restart unchanged in pain (still v1; agent_runtime migration
    is Wave 4 of the broader plan).

### Cutover process (the one PR)

The cutover PR is the final integration step. It contains:

1. The data migration invocation (one command per project).
2. The v1 path deletions listed in Wave I.
3. The v1 CLI dispatch shim pointing to `telec-cli`.
4. The v1 daemon Redis subscription wiring (from Wave H, integrated).
5. Updated `make install` to symlink `telec-cli` → `telec` (or replace
   the v1 entry point).
6. End-to-end smoke test logs proving v1 TUI refreshes on v2 events.

The PR is reviewed end-to-end; once approved, merge is the cutover
moment. Atomic. No transitional dual-mode.

## Failure modes

- **MVP scope creep.** Including TUI rewrite, daemon rewrite, hooks,
  webhooks, or additional services. MVP is workflow + CLI + bridge,
  full stop. Anything else is a separate wave.
- **Dual-write during build phase.** v2 writing to v1's SQLite or v1
  writing to v2's Postgres. Forbidden. v1 owns the data until cutover;
  v2 builds against empty Postgres.
- **Cross-language function calls.** v1 calling v2 Rust via HTTP or
  FFI. Redis events only.
- **Cutover PR mixing unrelated changes.** Cutover PR contains ONLY
  the migration + deletion + dispatch + bridge wiring. Unrelated
  changes go in separate PRs.
- **Skipping the Redis bridge in Wave H.** Without H, v1 TUI doesn't
  see v2 todos and looks broken. H is required for cutover.
- **Parallelism without DAG discipline.** Workers grabbing tasks in
  the wrong order, breaking dependencies. The DAG above is mandatory;
  orchestrator enforces ordering.
- **Workers expanding scope inside their task.** Each task has narrow
  acceptance criteria. If a worker thinks they need to do more,
  surface the question; don't expand silently.

## See Also

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/transport-rules.md
  bridge pattern
- docs/project/design/architecture-v2/services.md
  ownership
- docs/project/design/architecture-v2/file-layout.md
  shapes
- docs/project/design/architecture-v2/reconstruction-order.md
  MVP sits in the broader wave plan
- ~/.teleclaude/docs/software-development/policy/rust/testing.md
- ~/.teleclaude/docs/software-development/policy/rust/core.md
