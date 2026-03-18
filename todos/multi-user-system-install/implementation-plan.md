# Implementation Plan: Multi-User System-Wide Installation

## Overview

This is a large architectural project that **must be split into dependent sub-todos** before any build work begins. A single AI session cannot implement this safely. The plan below defines the phased breakdown; each phase should become its own todo with proper DOR gating.

The codebase already uses **SQLAlchemy + SQLModel** as the ORM layer, making dual database support (SQLite + PostgreSQL) significantly more tractable than a raw-SQL migration would be. The main work in the database phase is making engine creation configurable and handling dialect-specific operations.

## Recommended Todo Breakdown

### Phase 0: Database Backend Abstraction (sub-todo: `multi-user-db-abstraction`)

**Goal**: Make the database engine configurable so the same codebase runs on both SQLite (default) and PostgreSQL.

**File(s):** `teleclaude/core/db.py`, `teleclaude/core/db_models.py`, `teleclaude/core/migrations/`, `teleclaude/config/schema.py`, `pyproject.toml`

**Current state assessment:**

- SQLAlchemy/SQLModel already used for all ORM queries (`select()`, `update()`, etc.)
- Engine creation in `Db.__init__` / `Db.initialize()` is SQLite-specific (`aiosqlite`)
- SQLite PRAGMAs (`journal_mode=WAL`, `foreign_keys=ON`) are set at connection time
- `sqlite_insert` used for upserts (at least in `db.py:971`) — needs dialect-aware replacement
- 17 migration files use raw `aiosqlite` SQL — must be converted or made dialect-aware
- `schema.sql` is pure SQLite DDL — PostgreSQL needs its own bootstrap or Alembic

Tasks:

- [ ] Add `DatabaseConfig` to config schema: `engine: sqlite | postgresql`, `host`, `port`, `dbname`, `user`, `password` (optional, for Postgres)
- [ ] Add `asyncpg` as optional dependency in `pyproject.toml` (extra: `[postgres]`)
- [ ] Make engine creation configurable: `aiosqlite` for SQLite, `asyncpg` for PostgreSQL
- [ ] Conditionally apply SQLite PRAGMAs only when engine is SQLite
- [ ] Replace `sqlite_insert` upsert with `insert(...).on_conflict_do_update()` (SQLAlchemy generic)
- [ ] Audit all raw SQL in `db.py` for SQLite-specific syntax; convert to SQLAlchemy expressions
- [ ] Convert migration runner from raw `aiosqlite` to SQLAlchemy DDL operations (or introduce Alembic)
- [ ] Single-instance enforcement: SQLite exclusive lock (existing) vs PostgreSQL advisory lock (new)
- [ ] Docker Compose file with PostgreSQL for local development/testing
- [ ] Tests: run full test suite against both backends in CI

**Dependencies**: None. This is the foundation that all other phases build on.

**Research needed**: Alembic vs hand-rolled migration runner for dual-dialect support.

---

### Phase 1: OS User Identity Resolution (sub-todo: `multi-user-identity`)

**Goal**: Daemon can resolve a connecting Unix socket client's OS user to a TeleClaude person and role.

**File(s):** `teleclaude/config/schema.py`, `teleclaude/core/socket_auth.py` (new), `teleclaude/entrypoints/mcp_wrapper.py`, `teleclaude/mcp/server.py`

- [ ] Add `os_username: Optional[str]` field to `PersonEntry` config schema
- [ ] Create platform abstraction module for Unix socket peer credentials:
  - `SO_PEERCRED` (Linux) and `LOCAL_PEERCRED` (macOS)
  - Given a connected socket, return the peer's UID
  - Map UID → OS username → person lookup in config
  - Unknown UID → `public` role (least privilege)
- [ ] Integrate peer credential resolution into MCP socket accept path
- [ ] Inject resolved person identity (name + role) into command context alongside `caller_session_id`
- [ ] Tests: unit tests for credential extraction, person resolution, unknown-UID fallback
- [ ] Research: `SO_PEERCRED`/`LOCAL_PEERCRED` Python API (socket module support)

**Dependencies**: None (parallel with Phase 0, no database changes needed).

---

### Phase 2: Session Ownership & Visibility (sub-todo: `multi-user-sessions`)

**Goal**: Every session records its owner. Visibility is role-scoped.

**File(s):** `teleclaude/core/db_models.py`, `teleclaude/core/migrations/` (new), `teleclaude/core/db.py`, `teleclaude/commands/`, `teleclaude/api/`, `teleclaude/cli/tui/`

- [ ] Add `owner_person` TEXT and `owner_uid` INTEGER columns to `sessions` model
- [ ] Migration: add columns to `sessions` table (must work on both SQLite and PostgreSQL)
- [ ] Populate ownership on session creation from resolved identity
- [ ] Add session query filtering: member sees own sessions, admin sees all
- [ ] API server: filter session list by caller identity
- [ ] MCP tools: scope `list_sessions` results by caller role
- [ ] TUI: show owner badge on sessions belonging to other users (admin view)
- [ ] Session start notice: "Sessions on this system are subject to admin audit"
- [ ] Tests: ownership assignment, visibility filtering, role boundary checks

**Dependencies**: Phase 0 (migrations must work on both backends) + Phase 1 (identity resolution).

---

### Phase 3: Admin Observability & Audit (sub-todo: `multi-user-admin-audit`)

**Goal**: Admin can access session transcripts explicitly, and that access is logged.

**File(s):** `teleclaude/core/db_models.py` (audit model), `teleclaude/api/`, `teleclaude/commands/`, `teleclaude/cli/tui/`

- [ ] Create `AuditLog` SQLModel (who, what, when, target_session_id) + migration
- [ ] Admin transcript access endpoint: explicit action, not default
- [ ] Log every admin transcript access to audit table
- [ ] TUI admin view: metadata always visible, transcript requires explicit action
- [ ] API: transcript endpoint checks caller role + logs access
- [ ] Tests: audit logging, role-gated transcript access, log integrity

**Dependencies**: Phase 2 (session ownership must exist).

---

### Phase 4: Config Separation (sub-todo: `multi-user-config`)

**Goal**: Split config into system, secrets, and per-user layers.

**File(s):** `teleclaude/config/`, `teleclaude/daemon.py`, per-user config loading

- [ ] Define config file hierarchy:
  - `/etc/teleclaude/config.yml` or `/usr/local/etc/teleclaude/config.yml` — system config (people, projects, adapters, database connection)
  - `/etc/teleclaude/secrets.yml` — API keys, tokens (600 permissions, root-owned)
  - `~/.teleclaude/config.yml` — personal preferences (thinking mode, default model)
- [ ] Update config loading to merge layers: system → secrets → per-user
- [ ] Per-user config cannot override system-level settings (people, roles, projects, database)
- [ ] Config validation rejects secrets in per-user files
- [ ] Migration tool: split existing single `config.yml` into the three layers
- [ ] Tests: config merging, layer precedence, secrets isolation

**Dependencies**: Phase 1 (identity resolution informs which per-user config to load).

---

### Phase 5: Service User & System Installation (sub-todo: `multi-user-service`)

**Goal**: Daemon runs under a dedicated `teleclaude` service user with proper service management.

**File(s):** `bin/install-system.sh` (new), `etc/` (new — service unit files), `docker-compose.yml` (new), `teleclaude/daemon.py`

- [ ] Define system directory layout:
  - `/usr/local/share/teleclaude/` — shared docs, global snippets, index
  - `/var/lib/teleclaude/` — runtime state (SQLite DB if single-user fallback)
  - `/var/log/teleclaude/` — daemon logs
  - `/var/run/teleclaude/teleclaude.sock` — MCP socket
- [ ] Create `teleclaude` service user (like `_postgres`, `_mysql`)
- [ ] Write `launchd` plist (macOS) and `systemd` unit (Linux)
- [ ] Installer script: create user, directories, set permissions, install unit, create PostgreSQL database+role
- [ ] Docker Compose: TeleClaude daemon + PostgreSQL as turnkey deployment option
- [ ] Daemon startup: detect system-wide vs single-user mode and load paths accordingly
- [ ] File permissions: shared resources world-readable, secrets root-only, DB service-user-owned
- [ ] Tests: installation script idempotency, permission checks, service lifecycle

**Dependencies**: Phase 0 (PostgreSQL backend) + Phase 4 (config separation).

---

### Phase 6: Migration Tooling (sub-todo: `multi-user-migration`)

**Goal**: Existing single-user installs migrate to system-wide without data loss.

**File(s):** `bin/migrate-to-system.sh` (new), migration scripts

- [ ] Detect existing single-user layout
- [ ] Export SQLite data to PostgreSQL (table-by-table transfer via SQLAlchemy)
- [ ] Split config into system/secrets/personal layers
- [ ] Re-assign existing sessions to the migrating user (set `owner_person`/`owner_uid`)
- [ ] Move shared docs/snippets to system location
- [ ] Validate migration: verify daemon starts, sessions accessible, config loads, row counts match
- [ ] Rollback guide: document how to revert if migration fails (SQLite file is preserved, not deleted)
- [ ] Tests: migration on sample data, idempotency, rollback verification

**Dependencies**: Phase 2 (session ownership columns) + Phase 5 (system layout).

---

## Phase Dependency Graph

```
Phase 0: DB Abstraction ─────┐
                              ├──→ Phase 2: Session Ownership ──→ Phase 3: Admin Audit
Phase 1: Identity Resolution ─┤                                           │
                              ├──→ Phase 4: Config Separation              │
                              │         │                                  │
                              │         ↓                                  │
                              └──→ Phase 5: Service User                   │
                                        │                                  │
                                        ↓                                  │
                                  Phase 6: Migration ←─────────────────────┘
```

**Parallel tracks after Phase 0 + 1:**

- Track A: Phase 2 → Phase 3 (sessions, then audit)
- Track B: Phase 4 → Phase 5 → Phase 6 (config, then service, then migration)

Phase 0 and Phase 1 have no dependencies on each other and can be built in parallel.

## Open Design Questions (Must Resolve Before Phase Builds)

1. **Socket location in system mode**: `/tmp/teleclaude.sock` (current) vs `/var/run/teleclaude/teleclaude.sock`? The latter is more conventional but requires directory creation at boot.
2. **Agent credential model**: Daemon holds all API keys centrally. Users don't need keys. But if a user wants to run `claude` directly outside TeleClaude, they need their own key. This is explicitly out of scope.
3. **Cost allocation**: Session metadata already includes `thinking_mode` and `active_agent`. Token counting is not yet implemented. Defer to a separate todo.
4. **Worktree coordination**: Two users on the same project need separate worktrees. The existing worktree system is per-session. Document this as a limitation; full coordination is a separate concern.
5. **Alembic vs hand-rolled migrations**: Current migration runner is hand-rolled with raw SQL. Alembic would give auto-generated dual-dialect migrations but adds complexity. Decide during Phase 0 research.

## Validation Strategy

Each phase has its own test suite. Integration testing across phases:

- Phase 0: Full test suite passes on both SQLite and PostgreSQL.
- Phase 0+1+2: Two OS users create sessions via different backends; each sees only their own.
- Phase 2+3: Admin views all sessions; transcript access is logged.
- Phase 4+5: Daemon starts from system config under service user with PostgreSQL.
- Phase 5+6: Migrate existing SQLite install to PostgreSQL; verify all sessions and config survive.

## Risk Mitigation

- **Incremental delivery**: Each phase is independently useful and mergeable.
- **No big-bang migration**: System-wide mode is opt-in. Single-user SQLite mode continues to work.
- **Platform abstraction**: macOS/Linux differences isolated in a platform module.
- **Dual-backend CI**: Both SQLite and PostgreSQL tested from Phase 0 onward, preventing regression.
- **SQLite preserved**: Migration copies data to PostgreSQL; the original SQLite file is kept as rollback.
