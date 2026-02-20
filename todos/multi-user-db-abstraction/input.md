# Database Backend Abstraction

## Origin

Extracted from `multi-user-system-install` Phase 0. The multi-user project requires PostgreSQL for concurrent multi-user access, while single-user installs should keep SQLite's zero-config simplicity. This phase makes the database engine configurable.

## What We Have Today

- SQLAlchemy + SQLModel used for ORM models and queries (`select()`, `update()`, etc.)
- `aiosqlite` as the async engine driver
- Engine creation in `Db.__init__` / `Db.initialize()` is SQLite-specific
- SQLite PRAGMAs (`journal_mode=WAL`, `foreign_keys=ON`) set at connection time
- `sqlite_insert` used for upserts (e.g., `db.py` around line 971) — SQLite-specific dialect
- 17 migration files in `teleclaude/core/migrations/` use raw `aiosqlite` SQL
- `schema.sql` is pure SQLite DDL for bootstrapping
- Single-instance enforcement via SQLite exclusive lock
- All core tables: sessions, hook_outbox, notification_outbox, memory_observations, memory_summaries, agent_availability, voice_assignments, pending_message_deletions, session_listeners, webhook_contracts, webhook_outbox, system_settings

## What Needs to Change

### 1. Configurable Engine

Config selects backend at daemon startup:

- `database: { engine: sqlite }` — default, uses `aiosqlite`, zero config
- `database: { engine: postgresql, host: localhost, port: 5432, dbname: teleclaude, user: teleclaude, password: ... }` — uses `asyncpg`

### 2. Dialect-Aware Operations

- `sqlite_insert` → `insert(...).on_conflict_do_update()` (SQLAlchemy generic upsert)
- SQLite PRAGMAs conditionally applied only when engine is SQLite
- Any raw SQL in `db.py` audited and converted to SQLAlchemy expressions where needed

### 3. Migration Runner

Current: hand-rolled runner using raw `aiosqlite` SQL.
Options:

- Convert to SQLAlchemy DDL operations (keep hand-rolled runner, but dialect-aware)
- Adopt Alembic (auto-generated migrations, dual-dialect support out of the box)

Decision needed during this phase.

### 4. Single-Instance Enforcement

- SQLite: exclusive lock on DB file (existing)
- PostgreSQL: advisory lock (`pg_advisory_lock`) on a well-known key

### 5. Testing

- Full test suite must pass on both backends
- Docker Compose with PostgreSQL for local development and CI
- CI matrix: SQLite + PostgreSQL

## Dependencies

- `asyncpg` as new optional dependency (`pyproject.toml` extra: `[postgres]`)
- Docker (for PostgreSQL in dev/CI)

## Open Questions

1. Alembic vs keep the hand-rolled migration runner? Alembic gives auto-generation and multi-dialect, but adds complexity and a new tool to the dev workflow.
2. Should `schema.sql` be kept as the source of truth, or should SQLModel models become the authoritative schema with Alembic generating DDL?
