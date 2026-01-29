# Eliminate Raw SQL from DB Layer

## Intended Outcome

All database operations in `teleclaude/core/db.py` use SQLModel/SQLAlchemy ORM instead of raw `text()` SQL. Raw SQL is only permitted in migrations and PRAGMA statements. A pre-commit hook enforces this going forward.

## Scope Hints

- Convert `assign_voice` upsert to SQLAlchemy `insert().on_conflict_do_update()`.
- Convert `cleanup_stale_voice_assignments` DELETE to SQLModel query.
- Convert `list_sessions` dynamic query builder from raw SQL to SQLModel `select()`.
- Convert agent availability updates (`clear_expired_unavailability`) to SQLModel.
- Convert hook outbox methods (lock, deliver, retry) to SQLModel.
- PRAGMAs and schema bootstrap (`executescript`) stay as raw SQL — mark with `# noqa: raw-sql`.
- Add pre-commit hook that greps for `from sqlalchemy import text` or `text(` in `db.py` and fails if any occurrence lacks the `# noqa: raw-sql` marker.
