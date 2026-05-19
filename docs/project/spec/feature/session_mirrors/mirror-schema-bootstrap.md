---
id: 'project/spec/feature/session_mirrors/mirror-schema-bootstrap'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Idempotent SQLite schema bootstrap for mirrors, mirror_tombstones, the FTS5 index, and the three sync triggers — plus per-process column ALTERs that keep older databases compatible with newer code.'
---

# Mirror Schema Bootstrap — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

The mirror store uses a SQLite database (`MIRRORS_DB_PATH`) with three logical
objects: the `mirrors` row table, the `mirror_tombstones` table for
empty-transcript memory, and the `mirrors_fts` FTS5 virtual table that
provides full-text search. Three triggers (`mirrors_ai`, `mirrors_ad`,
`mirrors_au`) keep the FTS index in sync with the row table on INSERT,
DELETE, and UPDATE.

Schema bootstrap happens lazily on first use, gated by a per-process
`_schema_initialized` set so a given path runs through `CREATE TABLE IF NOT
EXISTS` / `CREATE INDEX IF NOT EXISTS` once per process. Older databases
created before the `summary`, `human_email`, and `visibility` columns
existed get those columns added via best-effort `ALTER TABLE` statements
that swallow `duplicate column` errors. The `idx_mirrors_human_email` index
is also created idempotently.

Two engine caches sit alongside the schema state: one for the writable
engine (used for upserts and tombstone writes) and two for read-only
engines (one for the mirrors DB, one for the read-only main DB). The
read-only engines use SQLite URI mode (`?mode=ro&uri=true`) and only get
constructed after the writable engine has confirmed the schema exists.

## Canonical fields

### Behavioral contract

#### Initial bootstrap

```
Given MIRRORS_DB_PATH points to a database file that does not yet exist
When any store function is invoked (e.g., search_mirrors, upsert_mirror)
Then _resolve_mirrors_db_path expands ~ and creates the parent directory if missing
And the writable engine is created via create_sync_db_engine(path)
And on the first connection from that engine, _ensure_schema runs
And _MIRRORS_SCHEMA is executed (mirrors, indexes, mirror_tombstones, mirrors_fts, three triggers)
And _migrate_add_mirror_columns runs (idempotent ALTERs)
And the path is recorded in _schema_initialized so subsequent calls skip the bootstrap
```

#### Idempotent column migration

```
Given a database created by an older version that lacks summary / human_email / visibility
When _migrate_add_mirror_columns runs
Then ALTER TABLE mirrors ADD COLUMN summary TEXT is executed
And ALTER TABLE mirrors ADD COLUMN human_email TEXT is executed
And ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private' is executed
And each statement that raises an OperationalError containing "duplicate column" is swallowed
And any other OperationalError re-raises
And CREATE INDEX IF NOT EXISTS idx_mirrors_human_email is executed unconditionally
```

#### Read-only engine gating

```
Given a caller requests the read-only engine for a path that has never been bootstrapped
When _get_ro_engine runs
Then it first invokes _get_rw_engine to ensure schema initialization
And then constructs the read-only engine via the file:<path>?mode=ro&uri=true URI
And caches it in _ro_engines keyed by the URI
```

#### Main DB read-only engine

```
Given the processor needs to look up upstream session rows
When _get_main_ro_engine runs
Then it constructs a read-only engine against tc_paths.MAIN_DB_PATH
And caches it in _main_ro_engines
And subsequent calls reuse the cached engine
```

#### FTS sync triggers

```
Given the mirrors table receives an INSERT
When the row is committed
Then mirrors_ai inserts a corresponding row into mirrors_fts

Given a DELETE removes a mirrors row
Then mirrors_ad inserts a 'delete' command row into mirrors_fts

Given an UPDATE modifies a mirrors row
Then mirrors_au first emits the 'delete' command for the old row
And then inserts the new row
```

#### Missing-table tolerance at read sites

```
Given the mirrors table does NOT exist (fresh install before any bootstrap)
When a read site (search_mirrors / get_mirror / list_mirrors / get_mirror_state_by_transcript / get_mirror_tombstone) catches SqlAlchemyOperationalError
Then _is_missing_table_error returns True for "no such table" causes
And the read function returns an empty result (None / empty list / empty dict)
And the exception is NOT re-raised
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:_MIRRORS_SCHEMA` — DDL for tables, indexes, FTS virtual table, and the three triggers.
- `teleclaude/mirrors/store.py:_ensure_schema` — per-path guard via `_schema_initialized`.
- `teleclaude/mirrors/store.py:_migrate_add_mirror_columns` — idempotent ALTERs and the new index.
- `teleclaude/mirrors/store.py:_get_rw_engine` — writable engine cache + schema bootstrap call.
- `teleclaude/mirrors/store.py:_get_ro_engine` — read-only engine cache gated on writable bootstrap.
- `teleclaude/mirrors/store.py:_get_main_ro_engine` — read-only engine cache for the main DB lookup.
- `teleclaude/mirrors/store.py:_resolve_mirrors_db_path` — path resolution + parent-directory creation.
- `teleclaude/mirrors/store.py:_is_missing_table_error` — exception classification for the read-side tolerance.
- `teleclaude/core/db/connection_factory.py:create_sync_db_engine` — the underlying engine factory.
- `teleclaude/paths.py:MIRRORS_DB_PATH` / `MAIN_DB_PATH` — canonical path constants.

## Known caveats

- Engine caches (`_rw_engines`, `_ro_engines`, `_main_ro_engines`,
  `_schema_initialized`) are module-level globals. They live for the
  process lifetime; tests that need a fresh state monkeypatch the paths AND
  clear the caches.
- `_schema_initialized` keys are resolved absolute paths. Two different
  string spellings of the same path resolve to the same key.
- The mirrors_fts triggers do not handle multi-row UPDATEs atomically with
  respect to FTS consistency under concurrent writers; SQLite's
  single-writer model is the safety net.
- The ALTER TABLE migration runs every time `_ensure_schema` runs for a
  new path within the process. Subsequent connections to the same path
  skip the bootstrap entirely thanks to `_schema_initialized`.
- The schema does NOT include a foreign key between `mirrors` and
  `mirror_tombstones`. The two tables coordinate via `source_identity`
  application-side only.
