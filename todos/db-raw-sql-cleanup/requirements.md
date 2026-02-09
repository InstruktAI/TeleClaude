# Requirements: Eliminate Raw SQL from DB Layer

## Goal

Convert remaining inline raw SQL in `teleclaude/core/db.py` to SQLModel/SQLAlchemy ORM. PRAGMAs and schema bootstrap stay as raw SQL with `# noqa: raw-sql` markers.

## Problem Statement

The input described several methods using raw SQL. Upon codebase inspection, most have already been migrated:

- `assign_voice` — already uses `sqlite_insert().on_conflict_do_update()`.
- `cleanup_stale_voice_assignments` — already uses `sqlalchemy.delete()`.
- `list_sessions` — already uses `sqlmodel.select()`.
- Agent availability methods — already use SQLModel.
- Hook outbox methods — already use SQLModel/SQLAlchemy `update()`.

**Remaining raw SQL that needs conversion:**

1. **Sync helpers** (`_field_query`, `_fetch_session_id_sync`, `get_session_id_by_tmux_name_sync`) — use raw SQL strings for session_id lookups in standalone scripts. These build raw `SELECT` queries with f-strings.

**Raw SQL that stays (marked with `# noqa: raw-sql`):**

1. PRAGMAs (`PRAGMA journal_mode`, `PRAGMA synchronous`, `PRAGMA busy_timeout`, `PRAGMA wal_checkpoint`).
2. Schema bootstrap via `executescript` (DDL SQL for table creation).

## Scope

### In scope

1. Convert sync helper session_id lookups from raw SQL strings to SQLModel `select()` statements.
2. Add pre-commit hook that greps for raw SQL in `db.py` and fails if any occurrence lacks `# noqa: raw-sql`.

### Out of scope

- PRAGMAs and schema bootstrap (stay as raw SQL).
- Any methods already using SQLModel/SQLAlchemy ORM.

## Acceptance Criteria

1. `_field_query` and `_fetch_session_id_sync` use SQLModel `select()` instead of raw SQL strings.
2. `get_session_id_by_tmux_name_sync` uses SQLModel `select()`.
3. No raw SQL in `db.py` without `# noqa: raw-sql` marker.
4. Pre-commit hook validates raw SQL markers.
5. All existing tests pass.
6. Sync helpers still work correctly for standalone scripts (hook receiver, telec).
