# Implementation Plan: multi-user-db-abstraction

## Overview

The codebase already uses SQLAlchemy + SQLModel for all ORM queries. The core work is: (1) make engine creation configurable, (2) guard SQLite-specific operations behind dialect checks, (3) adopt Alembic for dual-dialect migrations, and (4) validate both backends in CI.

**Alembic recommendation**: Adopt Alembic. The 17 existing migrations are raw aiosqlite SQL with SQLite-specific patterns (table-copy, `PRAGMA foreign_keys=OFF`, `PRAGMA table_info()`). Making each of these dialect-aware by hand is error-prone and produces a second hand-rolled migration framework. Alembic auto-generates DDL from SQLModel models, handles both dialects natively, and is the standard SQLAlchemy migration tool. The existing migrations can be frozen as a SQLite-only baseline; Alembic takes over for the current schema state and all future changes. One-time conversion cost, long-term maintainability gain.

## Phase 1: Config and Engine Abstraction

### Task 1.1: Extend DatabaseConfig

**File(s):** `teleclaude/config/__init__.py`, `teleclaude/config/schema.py`

- [ ] Add `DatabaseSchemaConfig` Pydantic model to `schema.py`:
  ```python
  class DatabaseSchemaConfig(BaseModel):
      engine: Literal["sqlite", "postgresql"] = "sqlite"
      host: Optional[str] = "localhost"
      port: int = 5432
      dbname: Optional[str] = "teleclaude"
      user: Optional[str] = "teleclaude"
      password: Optional[str] = None
  ```
- [ ] Extend `DatabaseConfig` dataclass in `__init__.py`:
  - Add `engine: str` field (default `"sqlite"`)
  - Add PostgreSQL connection fields (`host`, `port`, `dbname`, `user`, `password`)
  - Add `url` property that builds the correct SQLAlchemy URL:
    - SQLite: `sqlite+aiosqlite:///{path}` (existing behavior)
    - PostgreSQL: `postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}`
  - Add `sync_url` property for sync helpers:
    - SQLite: `sqlite:///{path}`
    - PostgreSQL: `postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}`
  - Add `is_sqlite` / `is_postgresql` convenience properties
- [ ] Preserve backward compatibility: omitting `database:` from config or setting only `database.path` must produce identical SQLite behavior to today
- [ ] Parse `database:` config section from `teleclaude.yml` through the schema validator

### Task 1.2: Make engine creation configurable in `Db`

**File(s):** `teleclaude/core/db.py`

- [ ] Refactor `Db.__init__` to accept `DatabaseConfig` (or derive engine URL from config) instead of raw `db_path`
- [ ] Refactor `Db.initialize()`:
  - SQLite path: keep aiosqlite bootstrap for schema + migrations (existing behavior), then create async engine
  - PostgreSQL path: create async engine directly via `create_async_engine` with `postgresql+asyncpg://` URL, skip aiosqlite bootstrap entirely
  - Pool parameters: `pool_size=5, max_overflow=3` works for both; add `pool_pre_ping=True` (already present)
- [ ] Update module-level singleton at `db.py:1829` to use the new constructor
- [ ] Ensure `Db.close()` works for both engine types (already engine-agnostic via `engine.dispose()`)

### Task 1.3: Conditional PRAGMAs (SQLite only)

**File(s):** `teleclaude/core/db.py`

- [ ] Guard aiosqlite bootstrap PRAGMAs (lines 160-162) behind `config.database.is_sqlite`
- [ ] Guard SQLAlchemy engine PRAGMAs (lines 196-198) behind engine dialect check
- [ ] Guard `wal_checkpoint()` method (line 260) -- make it a no-op when engine is not SQLite
- [ ] For PostgreSQL: set appropriate connection parameters instead (e.g., `statement_timeout` via connect_args)
- [ ] Use SQLAlchemy `event.listen(engine, "connect", set_pragmas)` pattern to apply PRAGMAs on every new connection from the pool (cleaner than executing after engine creation)

### Task 1.4: Replace `sqlite_insert` with dialect-generic upsert

**File(s):** `teleclaude/core/db.py`

- [ ] Replace `assign_voice()` (line 971-990):
  - Remove `from sqlalchemy.dialects.sqlite import insert as sqlite_insert`
  - Use SQLAlchemy generic approach: attempt insert, catch `IntegrityError`, then update. Or use `merge()` via SQLModel session since this is a simple primary-key upsert.
  - Alternative: use `sqlalchemy.dialects.postgresql.insert` when on PostgreSQL and `sqlalchemy.dialects.sqlite.insert` when on SQLite, selected at init time. This preserves the `on_conflict_do_update` pattern but requires dialect dispatch.
  - Recommended: use `session.merge()` which is fully dialect-agnostic and correct for PK-based upsert. The voice assignment is a simple "insert or update by PK" -- `merge()` handles this.

### Task 1.5: Audit and convert remaining raw SQL

**File(s):** `teleclaude/core/db.py`

- [ ] Audit all `text()` usage beyond PRAGMAs (currently: only PRAGMAs and WAL checkpoint found)
- [ ] Ensure no other SQLite-specific SQL patterns exist in `db.py`
- [ ] Refactor sync helpers (`_fetch_session_id_sync` at line 1740+, `get_session_field_sync` at line 1795+):
  - Replace hard-coded `sqlite:///` with `config.database.sync_url`
  - Guard PRAGMA calls behind `config.database.is_sqlite`
  - Ensure `psycopg2` is used for sync PostgreSQL access (add to optional deps)

---

## Phase 2: Migration System

### Task 2.1: Adopt Alembic for dual-dialect migrations

**File(s):** `teleclaude/core/migrations/`, `pyproject.toml`, `alembic.ini` (new), `alembic/` (new)

Strategy: freeze existing 17 migrations as SQLite-only historical artifacts. Create an Alembic baseline that represents the current schema (generated from SQLModel models). New migrations use Alembic.

- [ ] Add `alembic` to `pyproject.toml` dependencies
- [ ] Initialize Alembic: `alembic init teleclaude/core/alembic`
- [ ] Configure `alembic/env.py`:
  - Import SQLModel metadata from `db_models.py`
  - Read engine URL from `DatabaseConfig`
  - Support both async engines (`run_async=True` for asyncpg/aiosqlite)
- [ ] Create baseline migration that represents the current full schema (all tables as they exist after the 17 hand-rolled migrations)
- [ ] For SQLite: detect if the hand-rolled migrations have already been applied (check `schema_migrations` table). If so, stamp Alembic as "already at baseline" without re-running DDL.
- [ ] For PostgreSQL (fresh install): run the Alembic baseline migration to create all tables from scratch
- [ ] Update `Db.initialize()` to call Alembic's migration runner instead of the hand-rolled one
- [ ] Keep the hand-rolled `runner.py` and 17 migration files for SQLite backward compatibility during transition (they do not execute on PostgreSQL)

### Task 2.2: Convert schema bootstrap

**File(s):** `teleclaude/core/db.py`, `teleclaude/core/schema.sql`

- [ ] For SQLite: Alembic baseline migration replaces `schema.sql` + `executescript()`. On first run, Alembic creates all tables.
- [ ] For PostgreSQL: same Alembic baseline migration, but generating PostgreSQL-compatible DDL (Alembic handles this automatically from SQLModel metadata)
- [ ] `schema.sql` becomes a reference artifact, no longer executed at runtime
- [ ] Remove `executescript()` call from `Db.initialize()`
- [ ] Ensure `CREATE TABLE IF NOT EXISTS` semantics are preserved (Alembic handles via migration versioning, not idempotent DDL)

### Task 2.3: Single-instance enforcement for PostgreSQL

**File(s):** `teleclaude/core/db.py` or new `teleclaude/core/instance_lock.py`

- [ ] SQLite: keep existing file-based exclusive lock (no change)
- [ ] PostgreSQL: implement `pg_advisory_lock(key)` at daemon startup
  - Use a well-known lock key (e.g., hash of "teleclaude-daemon")
  - `pg_try_advisory_lock()` returns false if another daemon holds it
  - Lock is automatically released when the connection closes
  - Wrap in a small abstraction: `async def acquire_instance_lock(engine) -> bool`
- [ ] Call the lock acquisition from daemon startup, fail fast if lock is held

---

## Phase 3: Infrastructure

### Task 3.1: Docker Compose for PostgreSQL

**File(s):** `docker-compose.yml` (new or extend existing), `scripts/` or `Makefile`

- [ ] Create `docker-compose.yml` with PostgreSQL 16 service:
  ```yaml
  services:
    postgres:
      image: postgres:16
      environment:
        POSTGRES_DB: teleclaude
        POSTGRES_USER: teleclaude
        POSTGRES_PASSWORD: teleclaude_dev
      ports:
        - '5432:5432'
  ```
- [ ] Add Makefile targets: `make postgres-up`, `make postgres-down`
- [ ] Document how to run tests against PostgreSQL locally

### Task 3.2: CI matrix (SQLite + PostgreSQL)

**File(s):** `.github/workflows/test.yml` (or equivalent)

- [ ] Add PostgreSQL service container to CI
- [ ] Run test suite twice: once with SQLite (default), once with `TELECLAUDE_DB_ENGINE=postgresql`
- [ ] Ensure both backends produce the same test results

### Task 3.3: Tests for both backends

**File(s):** `tests/`

- [ ] Add pytest fixture that parameterizes database backend (SQLite and PostgreSQL)
- [ ] Ensure existing tests run unmodified on both backends
- [ ] Add specific tests for:
  - Engine URL construction from config
  - PRAGMA application on SQLite, skip on PostgreSQL
  - Upsert behavior (voice assignment) on both backends
  - Migration runner applies all migrations on both backends
  - Single-instance lock on both backends
  - Sync helper functions work on both backends

---

## Phase 4: Validation

### Task 4.1: Full validation

- [ ] `make test` passes on SQLite
- [ ] `make test` passes on PostgreSQL
- [ ] `make lint` passes
- [ ] No SQLite-specific imports in runtime paths (only behind dialect conditionals)
- [ ] Backward compatibility: fresh install with no `database:` config produces identical behavior to today
- [ ] All implementation tasks above marked `[x]`

### Task 4.2: Review readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

---

## Design Decisions

### Alembic adoption rationale

The hand-rolled migration runner (`runner.py`) is 82 lines of code that:

1. Tracks applied versions in a `schema_migrations` table
2. Discovers `###_name.py` files
3. Calls `up(db: aiosqlite.Connection)` on each

This is adequate for SQLite-only. For dual-dialect:

- Each of the 17 `up()` functions would need rewriting to produce dialect-aware SQL
- The runner would need to accept both `aiosqlite.Connection` and an asyncpg equivalent
- Future migration authors would need to handle dialect branching manually

Alembic solves all three by auto-generating DDL from SQLModel models and rendering it in the correct dialect. The one-time cost is: init Alembic, create a baseline, and update `Db.initialize()`. The ongoing benefit: every future migration is automatically dual-dialect.

### Existing migration handling

The 17 existing migrations are frozen as SQLite-specific history. They are not converted. Instead:

- SQLite installs that have already applied them: Alembic detects the schema is at baseline and stamps itself
- Fresh PostgreSQL installs: Alembic runs its baseline migration to create all tables
- This avoids a risky mass-conversion of 17 migration files while preserving the exact SQLite upgrade path

### Upsert strategy

`session.merge()` is the simplest dialect-agnostic approach for PK-based upserts. It issues a SELECT then INSERT or UPDATE as needed. For the voice assignment use case (low frequency, single row), the extra SELECT is negligible. This avoids maintaining a dialect-dispatch layer for `on_conflict_do_update`.
