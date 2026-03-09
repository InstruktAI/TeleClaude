# Requirements: Migration Tooling (multi-user-migration)

## Goal

Provide a non-destructive migration path from an existing single-user SQLite TeleClaude installation to a system-wide PostgreSQL deployment, preserving all sessions, configuration, and shared resources.

## Problem Statement

Existing TeleClaude installations have all data in SQLite, config in a single file, and no concept of system-wide deployment. When a user installs the multi-user system (Phase 5), they need their existing data migrated to the new layout. This must be safe (non-destructive), validated (row-count verification), and reversible (original files preserved, rollback documented).

## In Scope

1. **Installation detection**: Automatically find the existing SQLite database, config files, `.env`, and doc snippets from the current installation.
2. **SQLite-to-PostgreSQL data transfer**: Table-by-table data export from SQLite to PostgreSQL via SQLAlchemy, handling type differences, datetime formats, and sequence resets.
3. **Config splitting**: Reuse Phase 4's config split tool to produce system/secrets/per-user files from the existing monolithic config.
4. **Session ownership backfill**: Set `owner_person` and `owner_uid` on all existing sessions to attribute them to the migrating user.
5. **Doc snippet relocation**: Copy shared doc snippets from the user's home directory to the system-wide shared location.
6. **Validation step**: Compare row counts between source (SQLite) and target (PostgreSQL). Verify the daemon starts against the new backend. Print a summary report.
7. **Rollback documentation**: Print clear rollback instructions after migration. The original SQLite file and config are never modified or deleted.
8. **Orchestration script**: `bin/migrate-to-system.sh` that orchestrates all steps in order with progress reporting and error handling.

## Out of Scope

- Incremental or partial migration (this is a one-time, full transfer).
- Merging data when PostgreSQL already has data from another source.
- Migrating agent session transcripts (these are files in `~/.teleclaude/`, not database records -- they stay in the user's home directory).
- Automated rollback (manual rollback by stopping system daemon and reverting to single-user mode).
- Cross-machine migration (this handles local single-user to local system-wide).

## Success Criteria

- [ ] `bin/migrate-to-system.sh` completes end-to-end on a sample single-user installation, transferring all data to PostgreSQL.
- [ ] Row counts match for every table: source SQLite equals target PostgreSQL.
- [ ] Datetime values are correctly converted from SQLite text format to PostgreSQL timestamp type.
- [ ] JSON columns (e.g., session metadata) are correctly transferred and queryable.
- [ ] PostgreSQL auto-increment sequences are reset to `max(id) + 1` after bulk insert.
- [ ] All existing sessions have `owner_person` and `owner_uid` set to the migrating user.
- [ ] Config is split into system/secrets/per-user files at the correct locations.
- [ ] Doc snippets are copied to the system-wide shared location.
- [ ] The daemon starts against PostgreSQL after migration and can list sessions.
- [ ] The original SQLite file is preserved (not modified, not deleted).
- [ ] The original config.yml and .env are preserved.
- [ ] Rollback instructions are printed at the end of a successful migration.
- [ ] The migration script is idempotent when run against an empty PostgreSQL target (can be re-run after a failed attempt).
- [ ] Data transfer uses transactions: a mid-migration failure leaves PostgreSQL in a clean (empty) state, not a half-migrated state.

## Constraints

- Must use SQLAlchemy for both SQLite reads and PostgreSQL writes (consistent with the codebase's ORM layer).
- Must handle all tables in the current schema (sessions, memory, hooks, jobs, settings, audit log if present from Phase 3).
- Batch insert size should be configurable (default: 1000 rows) to handle large databases without excessive memory usage.
- The migration script (`bin/migrate-to-system.sh`) is a shell wrapper that calls Python migration modules. The actual data transfer logic is Python.
- Must work on both macOS and Linux.
- The PostgreSQL target database must already exist (created by `install-system.sh` from Phase 5).

## Risks

- **Type conversion errors**: SQLite's loose typing may have stored unexpected values (e.g., empty strings where integers are expected). Mitigation: add type coercion with fallback values during transfer; log warnings for coerced rows.
- **Large database performance**: A database with tens of thousands of sessions could take minutes to transfer. Mitigation: batch inserts with progress reporting; option to increase batch size.
- **Schema drift**: If the SQLite schema was partially migrated (some but not all schema migrations applied), the export may fail. Mitigation: run schema migrations on SQLite before exporting.
- **Sequence reset failure**: If PostgreSQL sequences are not reset after bulk insert, new rows will conflict. Mitigation: explicit `setval()` call for each serial column after transfer.
- **Concurrent access**: If the daemon is running during migration, SQLite reads may conflict. Mitigation: require the daemon to be stopped before migration (checked at script start).

## Design Decisions

1. **Full transfer, not incremental**: The migration is a one-time operation. Incremental adds complexity (tracking what was already migrated) without clear benefit -- the user switches from SQLite to PostgreSQL once.
2. **Transactional data transfer**: All PostgreSQL writes happen in a single transaction per table. If anything fails, the table's data is rolled back to empty.
3. **Config split reuse**: The config splitting logic from Phase 4 is imported and called directly. No duplication.
4. **Shell orchestration, Python data transfer**: The shell script handles orchestration (checking prerequisites, calling tools in order, printing summaries). The Python module handles the actual SQLAlchemy-based data transfer.
5. **Daemon stopped during migration**: The migration script checks that no TeleClaude daemon is running against the source database. This prevents read conflicts and ensures data consistency.

## Dependencies

- `multi-user-db-abstraction` (Phase 0): PostgreSQL backend support in the codebase. The migration writes to PostgreSQL using SQLAlchemy -- this requires Phase 0's async engine configuration.
- `multi-user-sessions` (Phase 2): Session ownership columns (`owner_person`, `owner_uid`) must exist in the schema for the backfill step.
- `multi-user-config` (Phase 4): Config split tool. The migration reuses this to split the monolithic config.
- `multi-user-service` (Phase 5): System directory layout. The migration writes files to system paths created by the installer.
