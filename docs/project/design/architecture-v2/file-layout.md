---
description: 'Concrete directory and file structure for v2 Rust workspace, per-crate conventions, naming rules, install symlinks.'
visibility: 'public'
---

# File Layout — Design

## Required reads

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md

## Purpose

Pin the on-disk shape of v2 against enterprise Rust best practice. Every
directory, every file convention, every naming rule. Reviewers and agents
reference this when deciding where new code goes.

## Inputs/Outputs

**Inputs:**

- the v2 architectural model (services as crates, infrastructure crosscuts,
  binaries consume via SDK)
- Rust workspace and crate conventions used by production projects
  (rust-analyzer, Cargo itself, InfluxDB IOx, Materialize, Helix, Zed,
  Astral's uv, Lemmy, Datafusion)
- the desire to keep v1 (Python) and v2 (Rust) coexistent in the same repo
  until v1 is retired

**Outputs:**

- the workspace layout
- per-crate file conventions
- naming rules
- install symlink pattern
- the v1/v2 coexistence layout in the same repo

## Invariants

- **One Cargo workspace.** Single `Cargo.toml` at repo root declares
  workspace members. No nested workspaces.
- **Crates live under `crates/` in a flat list.** No grouping subdirectories.
  Matches every cited production project.
- **Library crates contain logic; binary crates are thin entry points.**
  Binaries call into library crates. No business logic in `main.rs`.
- **Module visibility is the boundary mechanism.** `pub` for crate-public,
  `pub(crate)` for workspace-internal, plain `mod foo;` for file-private.
  No leading-underscore naming convention for "internal" — Rust's
  visibility modifiers are the convention.
- **No `mod.rs` files.** Use `<name>.rs` at the parent level for the
  module file. Rust 2018+ convention.
- **Workspace dependencies declared once.** Shared deps in
  `[workspace.dependencies]`; member crates reference via `workspace = true`.
- **Crate names: kebab-case, role-suffixed for binaries (`telec-cli`,
  `telec-daemon`), short unsuffixed for library crates (`workflow`,
  `identity`).**
- **Install symlinks decouple crate names from user-typed commands.**
  Symlinks live under `~/.local/bin/`; crate names stay role-descriptive.
- **User home dir is `~/.teleclaude/`.** Single tree containing global
  config, secrets, deployed slash commands (central source for all agent
  CLIs), shell wrapper init scripts, sandbox profiles, and small per-machine
  preferences. State lives in Postgres/Redis, not files; the home dir holds
  authored/installed content only. Relocation via the `TELECLAUDE_HOME` env var,
  read once at process startup by `teleclaude.runtime.config` and frozen into
  `RuntimeConfig.home`; no code reads it at runtime.
- **`frontend/`** (Next.js) stays where it is, untouched by the Rust workspace.
- **v1 Python stays in `teleclaude/`** at the repo root, untouched by v2
  until each v1 path is retired by a service migration.

## Primary flows

### Repo-root layout

```
TeleClaude/                          (repo root)
├── Cargo.toml                       (workspace root)
├── Cargo.lock
├── rust-toolchain.toml              (pinned Rust version)
├── crates/                          (v2 Rust workspace — flat list)
├── teleclaude/                      (v1 Python package — retired piece-by-piece)
├── frontend/                        (Next.js — existing, untouched)
├── docs/                            (authored docs, shared between v1 and v2)
├── agents/                          (agent artifact sources, shared)
├── trees/                           (worktrees)
├── docker-compose.yml               (local Postgres + Redis for dev)
├── Makefile                         (orchestration: build, install, pg-up, etc.)
├── pyproject.toml                   (v1 Python project)
└── README.md
```

### Crates workspace layout (flat)

```
crates/
├── shared/                          (library — primitive types)
├── observability/                   (library — tracing wrapper)
├── event-bus/                       (library — Redis pub/sub + streams wrapper)
├── storage/                         (library — sqlx::PgPool helpers, migration runner)
├── state-machine/                   (library — generic engine)
<!-- planned:data-upcasting-kernel -->
├── upcasting/                       (library — lazy data-upcasting engine)
<!-- /planned:data-upcasting-kernel -->
│
├── identity/                        (library — service)
├── agent-runtime/                   (library — service)
├── workflow/                        (library — service)
├── session-ledger/                  (library — service)
├── knowledge/                       (library — service)
├── integration/                     (library — service)
├── config/                          (library — service)
├── agent-artifacts/                 (library — service)
│
├── telec-cli/                       (binary — CLI; embeds service crates)
├── telec-tui/                       (binary — TUI)
├── telec-daemon/                    (binary — long-running supervisor)
├── telec-api/                       (binary — HTTP API server)
└── telec-hook/                      (binary — subprocess hook receiver for agent CLIs)
```

**Why flat, not grouped (e.g., `crates/services/`, `crates/binaries/`):**
every serious Rust workspace uses flat layout under one directory. Grouping
adds nesting without resolution benefit; the Cargo workspace glob (`crates/*`)
is one level. Tool, IDE navigation, and search all work better flat.

### Per-crate file conventions

A library crate (e.g., `crates/workflow/`):

```
crates/workflow/
├── Cargo.toml
├── README.md                        (crate purpose, public surface)
├── migrations/                      (sqlx migrations; service owns its schema)
│   └── 0001_init.sql
├── src/
│   ├── lib.rs                       (public re-exports; the crate's surface)
│   ├── models.rs                    (pub domain types: Todo, RoadmapEntry, ...)
│   ├── events.rs                    (pub event schemas for subscribers)
│   ├── errors.rs                    (pub error type via thiserror)
│   ├── service.rs                   (pub Service struct + new())
│   ├── state_machine.rs             (pub; uses crates/state-machine engine)
│   ├── state.rs                     (mod state; — file-private)
│   ├── roadmap.rs                   (mod roadmap;)
│   └── artifacts.rs                 (mod artifacts;)
└── tests/                           (integration tests against public API)
    ├── common/
    │   └── mod.rs                   (test builders, fixtures)
    └── workflow_api.rs
```

A binary crate (e.g., `crates/telec-cli/`):

```
crates/telec-cli/
├── Cargo.toml
└── src/
    ├── main.rs                      (entry — observability::init, dispatch)
    ├── todo.rs                      (telec todo subcommands)
    ├── sessions.rs                  (telec sessions subcommands)
    └── ...                          (one module per top-level subcommand)
```

### Module visibility (the right convention)

Rust visibility modifiers ARE the convention. Use them; don't invent a
naming scheme on top.

- **`mod foo;`** — module is private to its parent.
- **`pub(crate) mod foo;`** — module accessible within this crate only.
- **`pub mod foo;`** — module is part of the crate's public surface.

Inside a module:

- **`pub fn` / `pub struct`** — exported by the module per its mod declaration.
- **`pub(crate) fn`** — usable across the crate, not outside.
- **`fn`** (no `pub`) — file-private.

No leading-underscore filename convention. Privacy is declarative, not
nominal. The crate's `lib.rs` decides what's public by which modules it
declares as `pub mod`.

### Naming conventions

- **Crate names:** kebab-case for binaries (`telec-cli`, `telec-daemon`,
  `telec-tui`, `telec-api`, `telec-hook`). Short unsuffixed names for
  library crates (`workflow`, `identity`, `agent-runtime`, `event-bus`,
  `state-machine`).
- **Module names (files):** snake_case (`state_machine.rs`, `roadmap.rs`).
- **Public types:** PascalCase (`Todo`, `Principal`, `EventEnvelope`).
- **Public functions:** snake_case (`list_todos`, `resolve_caller`).
- **Constants:** SCREAMING_SNAKE_CASE.
- **Event names:** `{service}.{aggregate}.{verb_past}` lowercase snake
  (`workflow.todo.updated`).
- **Postgres schemas:** snake_case matching the crate name where applicable
  (`workflow`, `agent_runtime`, `session_mirrors`).

### Install symlinks (decouple crate name from user command)

Crate names reflect role (uniform `telec-<role>`). What users type can be
shorter via symlinks installed at `make install` time.

| Crate / Binary | Install target                               | What users type                         |
| -------------- | -------------------------------------------- | --------------------------------------- |
| `telec-cli`    | `~/.local/bin/telec` → `telec-cli`           | `telec`                                 |
| `telec-cli`    | `~/.local/bin/telec-cli` → `telec-cli`       | `telec-cli` (optional, explicit)        |
| `telec-tui`    | `~/.local/bin/telec-tui` → `telec-tui`       | `telec-tui`                             |
| `telec-daemon` | `~/.local/bin/telec-daemon` → `telec-daemon` | (machine-invoked)                       |
| `telec-api`    | `~/.local/bin/telec-api` → `telec-api`       | (machine-invoked)                       |
| `telec-hook`   | `~/.local/bin/telec-hook` → `telec-hook`     | (machine-invoked by Claude Code config) |

The only special case is `~/.local/bin/telec` — a Unix-conventional short
name for the primary user-typed command, symlinked to the actual binary
`telec-cli`. Every other binary keeps its descriptive name on PATH.

`make install` is responsible for:

1. Building the workspace (`cargo build --release`).
2. Copying or symlinking each binary into `~/.local/bin/<name>`.
3. Creating the `telec` → `telec-cli` shortcut.

### User home dir (`~/.teleclaude/`)

v2 keeps the v1 home dir convention. Single tree at `~/.teleclaude/`
holding all authored and installed content. State (sessions, todos,
transcripts, tokens, outbox/inbox, etc.) moves to Postgres; the home dir
is for configs, deployed artifacts, and per-machine preferences only.

```
~/.teleclaude/
├── teleclaude.yml          # global config (authored, editable)
├── .env                    # secrets (or use env vars / OS keychain)
├── tui_state.json          # per-machine TUI view state (rebuildable)
├── commands/               # deployed slash commands — central source for all agent CLIs
├── shell/                  # teleclaude-shell wrapper init scripts (.profile, .bashenv, ZDOTDIR)
├── company/                # company-scoped authored overlays (if used)
└── personal/               # personal-scoped authored overlays (if used)
```

**Dropped from v1:**

- `sandbox-cartridges/` was defined in v1's `paths.py` but never
  referenced anywhere. Dead. Not in v2.
- `storage/` (delivery binary archive) moves out of `~/.teleclaude/`.
  Binary artifacts colocate with their todo per-project (see below).

### Per-project `.teleclaude/` directory

Each project has its own `.teleclaude/` directory at the project root:

```
<project_root>/
├── teleclaude.yml          # per-project config (committed)
└── .teleclaude/            # per-project state (gitignored)
    └── deliveries/
        └── <slug>/         # whatever binary artifacts the workers produced for this todo
```

Workers produce whatever they produce: generated images from
`next-create-art`, HTML prototypes from `next-create-html`, screenshots,
transcripts, etc. The slug directory archives those outputs verbatim — no
imposed structure, no canonical subdirectory names. Workflow service moves
them here at delivery time and records the path in Postgres.

**Why colocate binaries with the todo:** delivery binaries change when
their owning todo changes, not when other deliveries change. Same
change-axis → same location. Per-project means trivial "delete this
project, delete its delivery archive" semantics.

**What's in Postgres vs files for deliveries:**

- Metadata (slug, delivered_at, commit SHA, content listing) → Postgres
  `workflow` schema.
- Binary artifact content → files at the path above. Postgres holds a
  path reference, not the bytes.

**What stays as files:** authored content (configs, secrets), installed
artifacts that agent CLIs reference at runtime (commands, shell scripts),
small per-machine preferences (tui_state).

**What does NOT live here in v2** (moved out from v1):

| v1 location                                                                 | v2 destination                                                                   |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `teleclaude.db`, `mirrors.db`, `events.db`                                  | Postgres schemas (`identity`, `agent_runtime`, `session_mirrors`, `integration`) |
| `state/*.json` (session_map, runtime-settings, cron_state, migration_state) | Postgres schemas of the owning services                                          |

<!-- planned-change:adopt-xdg-user-space-logger -->

| `logs/` | `/var/log/instrukt-ai/teleclaude/` (system location, per `instrukt_ai_logging` standard) |
<!-- change:adopt-xdg-user-space-logger -->

| `logs/` | `~/.local/state/instrukt-ai/teleclaude/` (user-space XDG state location, per `instrukt_ai_logging` standard) |
<!-- /planned-change:adopt-xdg-user-space-logger -->

| `tmp/sessions/<id>/` | `$TMPDIR/teleclaude-<session>/` (system tmpdir, OS-cleaned) |
| `session-auth/` | `identity.session_tokens` (Postgres) |
| `integration/` | `integration` Postgres schema |
| `bin/` (wrappers) | Single Rust binaries at `~/.local/bin/`; git wrapper retired (pre-commit hook enforces same rules) |
| `docs/` (global snippets mirror) | Gone — `context` service indexes directly from repo `docs/` source |
| Lock files (`git-main.lock`) | Postgres advisory locks or Redis SET NX |
| PID files (`cron_runner.pid`) | systemd / launchd manages PIDs |

**Why a single tree and not XDG split:** v2's home dir contains multiple
categories (config, secrets, installed commands, shell scripts, sandbox
profiles, overlays). Splitting these across `~/.config/` and
`~/.local/share/` adds two paths to remember without buying real benefit
at this scale. Many CLI tools use a single dotfile tree
(`~/.aws/`, `~/.kube/`, `~/.docker/`, `~/.gradle/`, `~/.cargo/`); v2
joins them. Self-contained tree means trivial backup (`tar`), uninstall
(`rm -rf`), and move-machine (`rsync`).

**Relocation:** `TELECLAUDE_HOME` env var. Set it before the process starts;
`teleclaude.runtime.config` reads it exactly once during module import, freezes
the value into `RuntimeConfig.home`, and all path constants derive from it.
Everything under `~/.teleclaude/` moves transparently. Same as v1.

**Migration from v1:** mostly nothing. The directory structure stays.
Per-service data migrations (in each service's wave) read v1 SQLite content
and write to Postgres. The few authored files (`teleclaude.yml`, `.env`,
`commands/`, `shell/`, `sandbox-cartridges/`, etc.) are already in the
right place from v1's perspective and don't need to move.

### Workspace `Cargo.toml` (the canonical shape)

```toml
[workspace]
members = ["crates/*"]
resolver = "2"

[workspace.package]
edition = "2024"
rust-version = "1.83"
version = "0.1.0"
license = "MIT OR Apache-2.0"

[workspace.dependencies]
tokio = { version = "1", features = ["full"] }
sqlx = { version = "0.8", features = ["postgres", "runtime-tokio", "uuid", "chrono"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
thiserror = "1"
anyhow = "1"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
async-trait = "0.1"
uuid = { version = "1", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }
redis = { version = "0.27", features = ["tokio-comp", "streams"] }
ratatui = "0.28"
crossterm = "0.28"
clap = { version = "4", features = ["derive"] }
axum = "0.7"

[workspace.lints.clippy]
all = { level = "warn", priority = -1 }
pedantic = { level = "warn", priority = -1 }
nursery = { level = "warn", priority = -1 }
# Specific lints that don't fit can be silenced with documented reason
module_name_repetitions = "allow"
```

### Member `Cargo.toml`

```toml
[package]
name = "workflow"
edition.workspace = true
version.workspace = true
license.workspace = true

[dependencies]
shared = { path = "../shared" }
observability = { path = "../observability" }
storage = { path = "../storage" }
event-bus = { path = "../event-bus" }
state-machine = { path = "../state-machine" }
tokio.workspace = true
sqlx.workspace = true
serde.workspace = true
serde_json.workspace = true
thiserror.workspace = true
tracing.workspace = true
async-trait.workspace = true

[lints]
workspace = true
```

Workspace lint inheritance keeps every crate under the same rules.

### `rust-toolchain.toml`

Pinned at repo root so contributors and CI use the same compiler:

```toml
[toolchain]
channel = "1.83.0"
components = ["rustfmt", "clippy", "rust-src"]
```

Update on a deliberate cadence; don't drift on contributor's local rustc.

### Tests

Rust convention, applied consistently:

- **Unit tests inside the module** (`#[cfg(test)] mod tests { ... }` at the
  bottom of each source file).
- **Integration tests** in `crates/<crate>/tests/` — separate compilation
  unit, exercises the crate's public API.
- **Shared test helpers** in `crates/<crate>/tests/common/mod.rs`.
- **E2E tests** in a dedicated `crates/telec-e2e/` crate if needed —
  critical paths only, real Postgres + Redis via `docker-compose`.

No top-level `tests/` directory. Each crate owns its tests.

See `software-development/policy/rust/testing.md` for the full testing policy.

### Migrations

Each service crate has its own `migrations/` directory with sequentially-
numbered SQL files run via `sqlx::migrate!()` at service startup.
Forward-only; no rollback. Schema-version check at startup; hard fail if
the database is ahead of the binary's expected version.

### v1/v2 coexistence

While v1 (Python) and v2 (Rust) coexist:

- `teleclaude/` (Python package) is untouched by v2 work. v1 features keep
  shipping in their existing shape.
- `crates/` (Rust workspace) is the v2 target. New v2 features and
  migrations land here.
- `docs/` and `agents/` are shared — both v1 and v2 read from them.
- `frontend/` is shared — talks to whichever backend exposes the API at
  the time (v1 daemon today, v2 `telec-api` eventually).
- `Makefile` orchestrates both: `make build` builds both; `make test` runs
  both; `make pg-up` brings up Postgres for v2 if not using native Postgres.

After v2 reaches full parity and v1 is retired, `teleclaude/` deletes.

## Failure modes

- **Adding crates outside `crates/`.** Breaks workspace resolution and
  convention. Always `crates/<name>/`.
- **Grouping crates into subdirectories** (`crates/services/`, `crates/binaries/`).
  Cited Rust projects use flat layout. Don't invent nesting.
- **Top-level `tests/` directory.** Each crate owns its tests. No global
  test directory.
- **Leading-underscore filenames for "internal" modules.** Use Rust
  visibility modifiers (`mod foo;` vs `pub mod foo;`). Privacy is
  declarative, not nominal.
- **`mod.rs` files.** Legacy Rust 2015 convention. Use `<name>.rs` at the
  parent level.
- **Cross-crate imports of internal modules.** Rust visibility prevents at
  compile time; PRs that try `crate::other_crate::internal::*` fail to
  build.
- **Sharing a Postgres schema across crates.** Each service's
  `migrations/` defines its own schema. Querying another schema from
  outside its owning crate violates the layer ownership rule.
- **Adding a service-level binary that runs as a process.** Services are
  library crates, not processes. The set of binaries is fixed
  (`telec-cli`, `telec-tui`, `telec-daemon`, `telec-api`, `telec-hook`,
  and worker binaries that integration spawns). Don't add a
  `workflow-server` binary that "exposes workflow over a port." Binaries
  embed services; services don't get their own processes.
- **Naming a binary `telec` directly** (without the `-cli` suffix). The
  crate is `telec-cli`; the symlink at install time is `telec`. Don't
  invert this — it breaks the uniform `telec-<role>` crate-naming pattern.
- **Inconsistent crate naming** (some kebab-case, some snake_case). Rust
  convention is kebab-case for crate names; modules and files inside use
  snake_case.

## See Also

- docs/project/design/architecture-v2/transport-rules.md
  rule this layout implements.
- docs/project/design/architecture-v2/services.md
  this layout.
- docs/project/design/architecture-v2/observability-model.md
  observability crate's role.
- docs/project/design/architecture-v2/auth-model.md
  role.
- ~/.teleclaude/docs/software-development/policy/rust/core.md
  Rust language usage rules.
- ~/.teleclaude/docs/software-development/policy/rust/testing.md
  Rust testing patterns.
