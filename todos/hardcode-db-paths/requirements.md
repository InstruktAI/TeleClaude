# hardcode-db-paths — Requirements

## Problem statement

The mirrors DB refactor (06ef8962a) introduced a regression where `daemon.py`
passed the main DB path (`config.database.path`) to `MirrorWorker`, which then
read/wrote mirrors to the wrong database. Root cause: `DatabaseConfig` and
`resolve_db_path()` create indirection that allows callers to pass the wrong
path. Two additional bugs exist:

- `processors.py` passes the mirrors DB path to `get_session_context()`, which
  queries the sessions table in the **main** DB — so lookups fail silently.
- `events_signals.py` queries signal tables against the main DB when signals
  live in the **events** DB.

## Intent

Eliminate all database path configuration. Replace the single configurable
`DatabaseConfig.path` and all ad-hoc path literals/resolution functions with
three canonical constants in `teleclaude/paths.py`. After this change, every
database consumer uses a compile-time constant — there is no runtime path
resolution, no config indirection, and no opportunity for a caller to pass the
wrong path.

## Requirements

### R1 — Canonical database path constants

Three path constants must exist in `teleclaude/paths.py`, derived from
`TELECLAUDE_HOME`, covering the main, mirrors, and events databases. All
production code that opens a database connection must resolve its path through
one of these constants. [inferred: the constant names and derivation follow
the existing `TELECLAUDE_HOME`-based pattern already established in `paths.py`]

### R2 — Remove `DatabaseConfig` and its config surface

The `DatabaseConfig` dataclass, its field on the top-level `Config`, and its
construction from `DATABASE_DIR`/`DATABASE_FILENAME` constants must be removed.
No user-facing configuration surface for database paths may remain. The
`DATABASE_DIR` and `DATABASE_FILENAME` constants in `constants.py` must also be
removed since they only served `DatabaseConfig`.

### R3 — Remove `resolve_db_path()` from mirrors store

The `resolve_db_path()` function and its module-level `_MIRRORS_DB_PATH`
constant in the mirrors store must be removed. All callers that used
`resolve_db_path()` must use the canonical constant from R1 directly.

### R4 — Fix mirrors processor bug: `get_session_context()` database target

`get_session_context()` queries the sessions table, which lives in the main DB.
The function must always connect to the main DB. Its `db` parameter (which
allowed callers to pass the wrong database) must be removed. Callers that
previously passed a mirrors-DB path must stop doing so.

### R5 — Fix events/signals CLI bug: wrong database for signal queries

The signals status handler queries signal tables. Signal tables live in the
events DB, not the main DB. The handler must connect to the events DB using the
canonical constant from R1.

### R6 — Preserve test isolation parameters

Database classes and helpers that accept an explicit `db_path` parameter for
test isolation (`:memory:` databases, temp directories) must retain that
parameter. The change is limited to **production call sites** — where the
default path or config-derived path is replaced by the canonical constant. Test
code that previously monkeypatched `config.database.path` must monkeypatch the
canonical constant instead.

### R7 — Alembic migration entry point

The Alembic `env.py` must use the canonical main DB constant from R1 instead of
`config.database.path`. [inferred: Alembic must still produce a valid
`sqlite:///` URL from the constant]

## Success criteria

1. `grep -r "config\.database" teleclaude/ --include="*.py"` returns zero hits.
2. `grep -r "resolve_db_path" teleclaude/ --include="*.py"` returns zero hits.
3. `grep -r "DATABASE_DIR\|DATABASE_FILENAME" teleclaude/ --include="*.py"` returns zero hits.
4. Full test suite passes (`uv run pytest tests/ -x -q --timeout=10`).
5. Pre-commit hooks pass (lint, typecheck, tests).
6. Daemon starts healthy after restart — mirror reconciliation runs with
   `failed=0` and writes to the correct mirrors database.
7. Signal status CLI handler connects to the events database.

## Scope

### In scope

- All production call sites that resolve a database path via `config.database`,
  `resolve_db_path()`, `DATABASE_DIR`/`DATABASE_FILENAME`, or hardcoded path
  literals.
- Removal of `DatabaseConfig`, `resolve_db_path()`, and the associated constants.
- Test fixture updates to monkeypatch the new constants instead of old config.
- Deletion of tests that only tested `resolve_db_path()` behavior.

### Out of scope

- `teleclaude/core/db/_sync.py` sync helpers — retain `db_path` parameter for
  test isolation.
- `teleclaude/memory/` modules — retain `db_path` parameters; callers are fixed
  at their source.
- `teleclaude/services/monitoring_service.py` — retains `db_path` constructor
  parameter for test isolation.
- `teleclaude/core/db/_base.py` — retains `db_path` constructor parameter for
  `:memory:` test support.
- `teleclaude/project_setup/macos_setup.py` — system databases, not ours.
- `teleclaude/memory/migrate_from_claude_mem.py` — one-off migration script.

## Deferred items

None.

## Dependencies

None — this todo has no roadmap dependencies.
