---
description: 'Deferred work — the authoritative v1→v2 workflow cutover that v2-mvp-bootstrap explicitly does not perform. Notes the prerequisites and the shape of the eventual cutover todo.'
id: 'project/design/architecture-v2/future-cutover'
scope: 'project'
type: 'design'
visibility: 'public'
---

# Future Cutover — Design

## Required reads

- docs/project/design/architecture-v2/mvp-shape.md
- docs/project/design/architecture-v2/reconstruction-order.md
- docs/project/design/architecture-v2/services.md

## Purpose

The v2-mvp-bootstrap delivery stops short of replacing v1 as the
authoritative workflow data source. That deliberate boundary lives here
so future planning can pick it up cleanly without re-discovering the I1
scope catch from MVP.

## Inputs/Outputs

**Inputs:**

- the v2-mvp-bootstrap delivery (Rust workflow service + CLI + bridge)
- the complete v1 footprint for workflow data (per `services.md`)
- the cutover safety checklist (per `reconstruction-order.md`)
- the broader v2 reconstruction sequence

**Outputs:**

- the exact boundary of what MVP did vs deliberately did NOT do
- the prerequisites that must be met before the `v2-workflow-cutover`
  todo can execute safely
- the sequencing of the cutover relative to other service migrations
- what's explicitly out of scope (post-MVP work tracked elsewhere)

## Invariants

- **MVP shipped parallel-capable, not authoritative.** v2 workflow
  service exists and works; v1 SQLite remains authoritative for
  workflow data.
- **The authoritative cutover is its own todo.** Not a follow-up patch;
  a dedicated `v2-workflow-cutover` todo that lands when prerequisites
  are met.
- **All v1 read/write paths for workflow data migrate in ONE PR.** No
  CLI-only cutover (creates dual source-of-truth). No staged migration
  per file (creates inconsistent reads).
- **The cutover must not self-destruct the running orchestrator.**
  `teleclaude/core/next_machine/` includes the build worker driving the
  cutover itself. Cutover sequencing must keep the orchestrator
  functional through the transition.
- **Data migration is idempotent.** `telec migrate-workflow-v1` is
  SHA-tracked so re-runs are safe.

## Primary flows

### What v2-mvp-bootstrap delivered

- Cargo workspace at `crates/` with seven crates (`shared`,
  `observability`, `storage`, `event-bus`, `identity`, `workflow`,
  `telec-cli`).
- Postgres-backed `WorkflowService` with full CRUD, todo-list operations,
  artifact versioning, lifecycle state machine, and event emission.
- `telec-cli` binary mirroring v1's `telec todo` CRUD
  against the v2 schema. Orchestrator-level subcommands (`design`,
  `prepare`, `work`, `integrate`, `mark-phase`, `reconcile`, `dump`,
  `split`, `stamp`) exit with code 2 so a future shim can route them to v1.
- `migrate-workflow-v1` subcommand that copies v1 SQLite todos into the
  v2 Postgres schema. Tool only — the cutover PR does NOT invoke it
  against real project data.
- Python bridge in the v1 daemon
  (`teleclaude/transport/workflow_bridge.py`) that subscribes to
  `workflow.*` Redis events and refreshes the existing cache via
  `DaemonCache.publish_workflow_change`. No-op while nobody uses the v2
  CLI.
- `make pg-up` / `pg-down` / `pg-reset` and `cargo-build/test/lint/fmt`
  Makefile targets for non-native Postgres setups. Pre-commit hooks invoke `cargo fmt --check` and
  `cargo clippy --workspace --all-targets -- -D warnings` on Rust
  changes.

### What v2-mvp-bootstrap deliberately did NOT do

The original `mvp-shape.md` task DAG included a Wave I cutover that
deleted `teleclaude/core/next_machine/`, `teleclaude/core/todos_db/`,
and `teleclaude/cli/telec/handlers/todo.py`, then replaced v1 dispatch
with the Rust binary. **That cutover was deferred.**

Reality check during the build session: v1's workflow access paths are
much broader than four CLI files. The following all read or write
workflow data and would break under aggressive deletion:

- `teleclaude/api/todo_routes.py` (~25 `todos_db.*` calls; backs the
  HTTP API the browser frontend uses)
- `teleclaude/cli/tui/widgets/todo_row.py`,
  `teleclaude/cli/tui/views/preparation_actions.py` (TUI direct reads)
- `teleclaude/core/integration/` and `teleclaude/core/operations/`
  (internal services)
- `teleclaude/core/roadmap.py` (v1 roadmap library)
- The entirety of `teleclaude/core/next_machine/` (the orchestrator
  that runs `/next-prepare`, `/next-build`, `/next-finalize`, etc.)
- `teleclaude/todo_artifacts.py`, `teleclaude/todo_scaffold.py`,
  `teleclaude/daemon.py`

Deleting `todos_db` and `next_machine` would self-destruct the running
orchestrator (the session driving the MVP build itself). A CLI-only
cutover (v2 CLI writes Postgres; everything else still writes SQLite)
creates dual source-of-truth — the failure mode v2 explicitly rejects.
Neither is acceptable.

### Prerequisites for the real `v2-workflow-cutover` todo

The authoritative cutover requires that every v1 read/write path for
workflow data is moved off SQLite onto the v2 Postgres schema in a
single coordinated step. That means:

1. **A Python read/write layer over the workflow Postgres schema** — a
   thin asyncpg / sqlalchemy module that exposes the same API surface
   v1's `todos_db` module does, backed by the v2 schema. v1 callers
   continue to import the same module name; the implementation swaps
   underneath.
2. **HTTP API migration** — `teleclaude/api/todo_routes.py` switches to
   the new Python layer. Browser frontend keeps the same wire shape.
3. **TUI widget migration** — `todo_row.py`, `preparation_actions.py`,
   and any other direct-read sites move to the new layer.
4. **Integration / operations / todo-list migration** —
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
7. **v1 CLI dispatch shim** — `teleclaude/cli/telec/handlers/todo.py`
   keeps its entry points but delegates CRUD
   subcommands to the Rust `telec-cli` binary (subprocess call). The
   orchestrator-level subcommands keep their v1 handler bodies.

Once all seven move together in one PR, the authoritative source of
truth flips from SQLite to Postgres atomically. v1 SQLite paths
(`teleclaude/core/todos_db/`) can be deleted at that point.

### Sequencing relative to the broader v2 migration

Per `reconstruction-order.md`, several other services (`agent_runtime`,
`session_mirrors`, `context`, `integration`, `config`,
`agent_artifacts`) will also migrate to dedicated v2 crates with their
own Postgres schemas. The workflow cutover can land independently of
those — workflow is the smallest entangled surface and the natural
first cutover. But the prerequisites above must be completed inside the
workflow cutover todo's scope.

### Not scoped here

- TUI / daemon / HTTP API / hooks remaining in v1 Python is by design
  for the v2 MVP. Rust replacements (`telec-tui`, `telec-daemon`,
  `telec-api`, `telec-hook`) are post-MVP work tracked under their own
  reconstruction-order waves.
- Identity service expansion beyond the single-user stub is post-MVP,
  tracked under v2-spine-completion (Wave 2).
- All other v2 service crates (agent_runtime, knowledge, integration,
  etc.) follow their own migration timelines per
  `reconstruction-order.md`.

## Failure modes

- **CLI-only cutover.** Replacing only `telec todo` dispatch with v2
  while leaving HTTP API + TUI + internal services + orchestrator on
  v1 SQLite. Creates dual source-of-truth. Forbidden — the cutover
  PR must include the Python read/write layer migration for ALL v1
  consumers in the same commit.
- **Aggressive deletion mid-build.** Deleting `next_machine/` or
  `todos_db/` while the orchestrator session running the cutover
  depends on them. Self-destructs the build. The cutover PR must stage
  deletions so the orchestrator continues to function until the new
  orchestrator paths are in place.
- **Skipping the data migration.** Cutting over CLI dispatch without
  copying v1 SQLite content first leaves new v2 paths reading empty
  Postgres. User loses access to their existing todos.
- **Partial v1 footprint coverage.** Migrating six of the seven
  prerequisites and assuming "we'll get the last one in a follow-up."
  The remaining v1 consumer continues to write SQLite, recreating the
  dual-truth problem in a smaller form.
- **Skipping pre-cutover verification.** Not running `telec
migrate-workflow-v1` against a copy of real v1 data before the
  cutover PR. The migration tool was unit-tested but the cutover PR
  itself is the first time it runs against production-shape data; the
  PR's verification step must include a dry run.

## See Also

- docs/project/design/architecture-v2/mvp-shape.md
- docs/project/design/architecture-v2/reconstruction-order.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/redesign-list.md
