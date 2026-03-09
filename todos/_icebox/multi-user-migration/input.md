# Multi-User Migration Tooling

## Origin

Extracted from `multi-user-system-install` Phase 6. This is the final phase of the multi-user project: migrate an existing single-user SQLite installation to the system-wide PostgreSQL deployment. Non-destructive -- the SQLite file is preserved for rollback.

## Current State

Today, a typical TeleClaude installation looks like:

- `teleclaude.db` (SQLite) in the project root -- all sessions, memory, hooks, jobs, settings
- `config.yml` in the project root -- single config file with everything
- `.env` in the project root -- API keys and tokens
- `~/.teleclaude/docs/` -- personal doc snippets and index
- `~/.teleclaude/` -- agent artifacts, scripts, session transcripts
- All data owned by one user, no ownership tracking on sessions

After the multi-user project delivers Phases 0-5, the target state is:

- PostgreSQL database owned by `teleclaude` service user
- Config split into `/etc/teleclaude/config.yml` (system), `/etc/teleclaude/secrets.yml` (secrets), `~/.teleclaude/config.yml` (per-user)
- Shared docs at `/usr/local/share/teleclaude/`
- Daemon running as system service

The migration must bridge these two states.

## What the Migration Does

### Step 1: Detect Existing Installation

Find the single-user layout:

- Locate `teleclaude.db` (check project root, check `TELECLAUDE_DB_PATH` env var, check config for `database.path`)
- Locate `config.yml` and `.env`
- Locate `~/.teleclaude/docs/` for doc snippets

### Step 2: Export SQLite Data to PostgreSQL

Table-by-table data transfer using SQLAlchemy:

- Open source SQLite database (read-only)
- Open target PostgreSQL database (the one created by `install-system.sh`)
- For each table: read all rows from SQLite, batch-insert into PostgreSQL
- Handle type differences: SQLite's loose typing vs PostgreSQL's strict typing
- Handle datetime format differences (SQLite stores as text, PostgreSQL uses native timestamps)
- Handle auto-increment/serial column differences

### Step 3: Split Config

Reuse Phase 4's config split tool:

- Split `config.yml` into system/secrets/per-user layers
- Extract secrets from `.env` into `secrets.yml`
- Write files to the system config directory

### Step 4: Assign Session Ownership

All existing sessions belong to the migrating user:

- Set `owner_person` to the migrating user's person name (from config)
- Set `owner_uid` to their OS UID
- This requires the session ownership columns from Phase 2

### Step 5: Move Shared Docs

Copy shared doc snippets to the system location:

- Copy from `~/.teleclaude/docs/` to `/usr/local/share/teleclaude/docs/`
- Preserve the per-user copy (user may have personal snippets too)
- Rebuild the snippet index at the system location

### Step 6: Validate

After migration, verify everything works:

- Row count comparison: every table in SQLite has the same row count in PostgreSQL
- Start the daemon against PostgreSQL and verify it initializes
- Verify sessions are accessible via MCP tools
- Verify config loads correctly from the three-layer system
- Print a summary report

### Step 7: Document Rollback

The migration is non-destructive:

- SQLite file is NOT deleted or modified
- Original `config.yml` and `.env` are NOT deleted
- To rollback: stop system daemon, start single-user daemon with original config
- Print rollback instructions after migration

## Key Challenges

1. **Type mapping**: SQLite stores everything as text. PostgreSQL is strict about types. Dates, booleans, JSON columns all need explicit conversion.
2. **Sequence/serial sync**: After bulk inserting into PostgreSQL, auto-increment sequences must be reset to max(id)+1 to avoid conflicts.
3. **Migration atomicity**: If migration fails midway, PostgreSQL should be in a clean state. Use a transaction for the data transfer.
4. **Large databases**: A busy installation might have thousands of sessions and memory entries. The transfer must handle this efficiently (batch inserts, not row-by-row).

## Open Questions

1. Should the migration tool support incremental migration (only transfer rows newer than last migration)? Or is it always a full, one-time transfer?
2. How to handle the case where PostgreSQL already has data (e.g., migration run twice)? Truncate and re-import? Merge? Fail?
3. Should the migration verify data integrity beyond row counts (e.g., checksum comparison on key columns)?

## Dependencies

- Phase 2 (`multi-user-sessions`): Session ownership columns (`owner_person`, `owner_uid`) must exist in the database schema
- Phase 4 (`multi-user-config`): Config split tool (reused by the migration)
- Phase 5 (`multi-user-service`): System directory layout must be established (installer has been run)
- Phase 0 (`multi-user-db-abstraction`): PostgreSQL backend support
