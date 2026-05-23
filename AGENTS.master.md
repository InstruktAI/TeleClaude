# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

- @docs/project/baseline.md
- @docs/project/baseline-progressive.md

## External instrumentation

The TUI is instrumented by the dotfiles repository at `~/Sync/dotfiles/terminal/`. Key interactions:

- **Appearance sync:** `appearance.py reload` sends SIGUSR1 to the TUI when OS dark/light mode changes. The TUI handles this by saving state and restarting (same as SIGUSR2). The appearance script also sets tmux `@appearance_mode` and syncs agent CLI themes.
- **Agent restart:** tmux `bind R` triggers agent restart via the daemon API.
- See `~/Sync/dotfiles/terminal/AGENTS.md` for full architecture.

## Databases

- **Daemon DB:** `~/.teleclaude/teleclaude.db` (resolved from `config.database.path`) — sessions, operations, tokens, availability.
- **Mirrors DB:** `~/.teleclaude/mirrors.db` — transcript mirrors, used by `telec history search`. Separate database.
- **Todos DB:** `{project_root}/.teleclaude/todos.db` — per-project todo state, artifacts, and roadmap. One per project. **Authoritative for v1 workflow surfaces** (API, TUI, `/next-*` orchestrators, integration).

## v2 workspace (Rust, parallel-capable)

A v2 Rust workspace lives alongside v1 under `crates/`. It exposes a parallel `WorkflowService` plus a `telec-cli` binary that mirrors v1's `telec todo` CRUD against a Postgres-backed schema. As of the `v2-mvp-bootstrap` delivery:

- **v1 remains authoritative for all workflow data.** The Rust binary writes to its own `workflow` Postgres schema and emits `workflow.*` Redis events. It is **not** wired into v1 dispatch.
- **The v1 daemon subscribes to `workflow.*` Redis channels** (`teleclaude/transport/workflow_bridge.py`) and invalidates its cache when events arrive. The subscription is a no-op while nobody uses the v2 CLI.
- [DEVELOPMENT] **`make pg-up` / `make pg-down` / `make pg-reset`** bring local Postgres 17 + Redis 7 up via `docker-compose.yml`. We recommend choosing native Postgres install during `make install`.
- **`cargo build/test/clippy --workspace`** are the v2 quality gates. Pre-commit hooks run `cargo fmt --check` and `cargo clippy --workspace --all-targets -- -D warnings` on Rust changes.
- **Authoritative cutover is a future dedicated todo** (`v2-workflow-cutover`). It will migrate v1's HTTP API, TUI, integration, operations, and `next_machine/` orchestrator off SQLite onto the v2 Postgres schema in one coordinated step. Until then, do not delete v1 paths and do not run `telec migrate-workflow-v1` against real project data.
- **The `workflow` crate's `RoadmapEntry`/`roadmap` modeling does NOT represent the intended shape.** The workflow domain has one entity — the todo, ordered and dependency-gated; there is no separate roadmap concept. See `project/adr/0009-workflow-domain-has-no-roadmap`; the rework is tracked by the `v2-workflow-drop-roadmap` todo. (v1's legacy `roadmap` table/module names stay until cutover.)

## TUI work

- After any TUI code change, send SIGUSR2 to the running TUI to reload. (SIGUSR1 is reserved for appearance/theme refresh.)
  ```bash
  kill -USR2 "$(tmux list-panes -t tc_tui -F '#{pane_pid}' | head -1)"
  ```
  The TUI runs as the first pane in the `tc_tui` tmux session. Using tmux's pane PID is reliable regardless of how the process was launched.
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.

## Integration push guard

The pre-push hook runs `telec code lint --all` before allowing any push from `trees/_integration/` to `origin/main`.

- **Canonical source:** `.githooks/pre-push` (tracked in git; edit this file to change hook behavior).
- **Active hook:** `.git/hooks/pre-push` (deployed from canonical source; this is the file git actually executes).
- **Per-worktree mirror:** `trees/_integration/.githooks/pre-push` (kept in sync to prevent regression when hooks are re-deployed from this mirror).

If an integration push is blocked with `ERROR: Integration push blocked — telec code lint --all failed.`, resolve all lint violations reported by `telec code lint --all` and retry the push. The CI `make lint` check is a redundant post-push catch layer; the pre-push guard is the primary enforcement surface.

## Git Documentation Filters

The `teleclaude-docs` git filter ensures that `@~/.teleclaude` paths in documentation snippets are expanded to absolute paths on checkout, and contracted back to `@~/.teleclaude` on commit.
This filter configuration is a dual-responsibility to cover both the core platform and isolated projects:

- **Mother Project (TeleClaude core):** Configured automatically during `make install`.
- **Downstream Projects:** Configured automatically by `telec projects init` when initializing a new AI-managed project.
