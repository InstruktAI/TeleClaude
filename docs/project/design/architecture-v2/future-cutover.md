---
description: 'Deferred work — the authoritative v1→v2 workflow cutover that the v2-mvp-bootstrap delivery explicitly does not perform. Notes the prerequisites and the shape of the eventual cutover todo.'
id: 'project/design/architecture-v2/future-cutover'
scope: 'project'
type: 'design'
---

# Future Cutover — Design Note

## Required reads

- docs/project/design/architecture-v2/mvp-shape.md
- docs/project/design/architecture-v2/reconstruction-order.md
- docs/project/design/architecture-v2/services.md

## Purpose

The v2-mvp-bootstrap delivery stops short of replacing v1 as the authoritative
workflow data source. That deliberate boundary lives here so future planning
can pick it up cleanly.

## What v2-mvp-bootstrap delivered

- Cargo workspace at `crates/` with seven crates (`shared`, `observability`,
  `storage`, `event-bus`, `identity`, `workflow`, `telec-cli`).
- Postgres-backed `WorkflowService` with full CRUD, roadmap operations,
  artifact versioning, lifecycle state machine, and event emission.
- `telec-cli` binary mirroring v1's `telec todo` / `telec roadmap` CRUD
  against the v2 schema. Orchestrator-level subcommands (`design`,
  `prepare`, `work`, `integrate`, `mark-phase`, `reconcile`, `dump`,
  `split`, `stamp`, `migrate-icebox`) exit with code 2 so a future shim can
  route them to v1.
- `migrate-workflow-v1` subcommand that copies v1 SQLite todos into the v2
  Postgres schema. Tool only — the cutover PR does NOT invoke it against
  real project data.
- Python bridge in the v1 daemon
  (`teleclaude/transport/workflow_bridge.py`) that subscribes to
  `workflow.*` Redis events and refreshes the existing cache via
  `DaemonCache.publish_workflow_change`. No-op while nobody uses the v2
  CLI.
- `make pg-up` / `pg-down` / `pg-reset` and `cargo-build/test/lint/fmt`
  Makefile targets. Pre-commit hooks invoke `cargo fmt --check` and
  `cargo clippy --workspace --all-targets -- -D warnings` on Rust changes.

## What v2-mvp-bootstrap deliberately did NOT do

The original `mvp-shape.md` task DAG included a Wave I cutover that
deleted `teleclaude/core/next_machine/`, `teleclaude/core/todos_db/`,
`teleclaude/cli/telec/handlers/todo.py`, and
`teleclaude/cli/telec/handlers/roadmap.py`, then replaced v1 dispatch
with the Rust binary. **That cutover was deferred.**

Reality check during the build session: v1's workflow access paths are
much broader than four CLI files. The following all read or write
workflow data and would break under aggressive deletion:

- `teleclaude/api/todo_routes.py` (~25 `todos_db.*` calls; backs the HTTP
  API the browser frontend uses)
- `teleclaude/cli/tui/widgets/todo_row.py`,
  `teleclaude/cli/tui/views/preparation_actions.py` (TUI direct reads)
- `teleclaude/core/integration/` and `teleclaude/core/operations/`
  (internal services)
- `teleclaude/core/roadmap.py` (v1 roadmap library)
- The entirety of `teleclaude/core/next_machine/` (the orchestrator that
  runs `/next-prepare`, `/next-build`, `/next-finalize`, etc.)
- `teleclaude/todo_artifacts.py`, `teleclaude/todo_scaffold.py`,
  `teleclaude/daemon.py`

Deleting `todos_db` and `next_machine` would self-destruct the running
orchestrator (the session driving the MVP build itself). A CLI-only
cutover (v2 CLI writes Postgres; everything else still writes SQLite)
creates dual source-of-truth — the failure mode v2 explicitly rejects.
Neither is acceptable.

## Prerequisites for the real `v2-workflow-cutover` todo

The authoritative cutover requires that every v1 read/write path for
workflow data is moved off SQLite onto the v2 Postgres schema in a single
coordinated step. That means:

1. **A Python read/write layer over the workflow Postgres schema** — a
   thin asyncpg / sqlalchemy module that exposes the same API surface
   v1's `todos_db` module does, backed by the v2 schema. v1 callers
   continue to import the same module name; the implementation swaps
   underneath.
2. **HTTP API migration** — `teleclaude/api/todo_routes.py` switches to
   the new Python layer. Browser frontend keeps the same wire shape.
3. **TUI widget migration** — `todo_row.py`, `preparation_actions.py`,
   and any other direct-read sites move to the new layer.
4. **Integration / operations / roadmap migration** —
   `teleclaude/core/integration/`, `teleclaude/core/operations/`,
   `teleclaude/core/roadmap.py` switch to the new layer.
5. **Orchestrator migration** — every file under
   `teleclaude/core/next_machine/` that reads or writes workflow state
   moves to the new layer. State writes additionally fire the matching
   v2 Redis events so subscribers (including the daemon bridge already
   in place) stay current.
6. **Data migration** — `telec migrate-workflow-v1` is invoked once per
   registered project to copy SQLite → Postgres. The migration is
   idempotent (SHA-tracked) so it can re-run safely.
7. **v1 CLI dispatch shim** — `teleclaude/cli/telec/handlers/todo.py` and
   `handlers/roadmap.py` keep their entry points but delegate CRUD
   subcommands to the Rust `telec-cli` binary (subprocess call). The
   orchestrator-level subcommands keep their v1 handler bodies.

Once all seven move together in one PR, the authoritative source of
truth flips from SQLite to Postgres atomically. v1 SQLite paths
(`teleclaude/core/todos_db/`) can be deleted at that point.

## Sequencing relative to the broader v2 migration

Per `reconstruction-order.md`, several other services (`agent_runtime`,
`session_ledger`, `knowledge`, `integration`, `config`,
`agent_artifacts`) will also migrate to dedicated v2 crates with their
own Postgres schemas. The workflow cutover can land independently of
those — workflow is the smallest entangled surface and the natural
first cutover. But the prerequisites above must be completed inside the
workflow cutover todo's scope.

## Not scoped here

- TUI / daemon / HTTP API / hooks remaining in v1 Python is by design
  for the v2 MVP. Rust replacements (`telec-tui`, `telec-daemon`,
  `telec-api`, `telec-hook`) are post-MVP work.
- Identity service expansion beyond the single-user stub is post-MVP.
- All other v2 service crates (agent_runtime, knowledge, integration,
  etc.) follow their own migration timelines.
