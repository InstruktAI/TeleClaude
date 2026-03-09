# Requirements: multi-user-db-abstraction

## Goal

Make the database engine configurable so the same TeleClaude codebase runs on both SQLite (default, zero-config, single-user) and PostgreSQL (opt-in, multi-user). This is Phase 0 of the multi-user system-wide installation project; all subsequent phases depend on this foundation.

## Problem Statement

The current database layer is SQLite-specific in four distinct areas:

1. **Engine creation** (`teleclaude/core/db.py:178`): Hard-coded `sqlite+aiosqlite:///` URL. The `Db.__init__` constructor takes a file path, not a generic connection spec.
2. **PRAGMAs** (`db.py:160-162, 196-198, 260, 1764-1765, 1814-1815`): `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `wal_checkpoint(TRUNCATE)` are SQLite-only concepts. These are set in six locations: aiosqlite bootstrap, SQLAlchemy engine init, WAL checkpoint method, and two sync helper functions.
3. **Dialect-specific upsert** (`db.py:971`): `from sqlalchemy.dialects.sqlite import insert as sqlite_insert` -- only works against SQLite.
4. **Migration runner** (`teleclaude/core/migrations/runner.py`): Takes `aiosqlite.Connection`, runs `up(db)` functions from 17 migration files that use raw `aiosqlite` SQL, including SQLite-specific patterns (`PRAGMA foreign_keys=OFF`, `PRAGMA table_info()`, `executescript()`).
5. **Schema bootstrap** (`db.py:164-168`): Reads `schema.sql` and runs it via `conn.executescript()` -- a SQLite-only API. The DDL itself uses SQLite syntax (`INTEGER PRIMARY KEY AUTOINCREMENT`, `BOOLEAN DEFAULT 0`).
6. **Sync helpers** (`db.py:1762, 1812`): Two standalone sync functions create SQLite-specific engines with hard-coded `sqlite:///` URLs and PRAGMA setup.

## Scope

### In scope

- Extending `DatabaseConfig` and config schema with engine selection and PostgreSQL connection parameters
- Making `Db.__init__` and `Db.initialize()` engine-agnostic
- Conditional PRAGMA application (SQLite only)
- Replacing `sqlite_insert` with dialect-generic upsert
- Auditing all raw SQL in `db.py` and converting to SQLAlchemy expressions where needed
- Converting the migration runner to work with both backends (Alembic recommended)
- Converting `schema.sql` bootstrap to SQLAlchemy DDL or Alembic baseline
- PostgreSQL single-instance enforcement via advisory lock
- Making sync helper functions (`_fetch_session_id_sync`, `get_session_field_sync`) engine-aware
- `asyncpg` as optional dependency in `pyproject.toml`
- Docker Compose for PostgreSQL dev/CI
- CI matrix configuration for dual-backend testing

### Out of scope

- Multi-user identity resolution (Phase 1: `multi-user-identity`)
- Session ownership columns (Phase 2: `multi-user-sessions`)
- Config separation into system/secrets/personal layers (Phase 4: `multi-user-config`)
- System-wide service installation (Phase 5: `multi-user-service`)
- SQLite-to-PostgreSQL data migration tooling (Phase 6: `multi-user-migration`)
- New tables or schema changes beyond what is needed for dual-backend support
- Performance tuning of PostgreSQL connection pool parameters (can be done later)

## Success Criteria

- [ ] `teleclaude.yml` supports `database.engine: sqlite` (default) and `database.engine: postgresql` with connection parameters
- [ ] Daemon starts and passes full test suite on SQLite with zero config changes (backward compatibility)
- [ ] Daemon starts and passes full test suite on PostgreSQL with only `database:` config changes
- [ ] No SQLite-specific imports or APIs remain in runtime code paths (all behind engine-type conditionals or abstracted)
- [ ] Migration runner works on both backends; all 17 existing migrations apply cleanly on both
- [ ] Single-instance enforcement works on both backends (file lock for SQLite, advisory lock for PostgreSQL)
- [ ] `make test` passes on both backends
- [ ] `make lint` passes
- [ ] CI runs test matrix: SQLite + PostgreSQL

## Constraints

- **Backward compatibility**: Existing SQLite users must experience zero behavior change. `database.engine: sqlite` is the default. Omitting the `database:` config block entirely must produce the same behavior as today.
- **No data loss**: The 17 existing migrations must produce identical schema on both backends. No migration may be skipped or simplified in a way that loses data.
- **SQLAlchemy/SQLModel foundation**: The ORM layer already handles most dialect differences. The abstraction must build on this, not replace it.
- **Optional dependency**: `asyncpg` (and `psycopg2` for sync helpers if needed) must be optional extras, not hard requirements. SQLite-only installs must not require PostgreSQL drivers.
- **Module-level singleton**: `db.py:1829` creates `db = Db(config.database.path)` at import time. The refactored constructor must remain compatible with this pattern.

## Risks

- **Migration conversion scope**: 17 migrations use raw aiosqlite SQL with SQLite-specific patterns (table-copy for schema changes, `PRAGMA foreign_keys=OFF`, `PRAGMA table_info()`). Converting all to dialect-aware code is the largest task. Mitigation: adopt Alembic which handles dialect differences natively; treat existing migrations as a frozen baseline and only require new migrations to be dual-dialect.
- **Sync helper coupling**: Two sync functions in `db.py` create their own SQLite engines independently of the `Db` class. These must also be made engine-aware, but they run in non-async contexts (hook receiver, CLI). Mitigation: pass engine URL through config; use `psycopg2` (sync) for PostgreSQL sync access.
- **asyncpg + SQLAlchemy async integration**: While well-documented, the exact connection pool behavior, error handling, and transaction semantics differ from aiosqlite. Mitigation: targeted research and integration tests before build.
- **WAL checkpoint**: `wal_checkpoint(TRUNCATE)` is a SQLite maintenance operation with no PostgreSQL equivalent (PostgreSQL handles WAL differently via `autovacuum`). The checkpoint method must become a no-op on PostgreSQL. Mitigation: guard behind engine-type check.
- **Test isolation**: PostgreSQL tests need a real PostgreSQL instance (unlike SQLite which is in-process). CI must provision PostgreSQL. Mitigation: Docker Compose + GitHub Actions service container.

## Key Files

| File                                   | What changes                                                                               |
| -------------------------------------- | ------------------------------------------------------------------------------------------ |
| `teleclaude/config/__init__.py`        | Extend `DatabaseConfig` with engine type, PostgreSQL connection params                     |
| `teleclaude/config/schema.py`          | Add Pydantic model for database config validation                                          |
| `teleclaude/core/db.py`                | Engine-agnostic init, conditional PRAGMAs, dialect-generic upsert, sync helper refactoring |
| `teleclaude/core/migrations/runner.py` | Dual-backend migration execution (Alembic or refactored runner)                            |
| `teleclaude/core/migrations/*.py`      | 17 existing migrations: freeze as baseline or convert                                      |
| `teleclaude/core/schema.sql`           | May be replaced by Alembic baseline or SQLAlchemy DDL                                      |
| `pyproject.toml`                       | `asyncpg` optional extra, possibly `alembic` dependency                                    |
| `docker-compose.yml`                   | PostgreSQL service for dev/CI                                                              |
| `.github/workflows/`                   | CI matrix: SQLite + PostgreSQL                                                             |
