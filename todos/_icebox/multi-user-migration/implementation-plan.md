# Implementation Plan: Migration Tooling (multi-user-migration)

## Overview

Build a migration tool that transfers an existing single-user SQLite TeleClaude installation to the system-wide PostgreSQL deployment. The approach uses SQLAlchemy to read from SQLite and write to PostgreSQL, ensuring type safety and transactional integrity. A shell script orchestrates the full migration workflow: detection, transfer, config split, ownership backfill, doc relocation, and validation.

This phase depends on Phases 0, 2, 4, and 5 being complete. It is the integration capstone of the multi-user project.

## Phase 1: Data Transfer Module

### Task 1.1: SQLite-to-PostgreSQL transfer engine

**File(s):** `teleclaude/migration/data_transfer.py` (new)

- [ ] Create `DataTransfer` class that takes:
  - `source_url: str` (SQLite connection string)
  - `target_url: str` (PostgreSQL connection string)
  - `batch_size: int = 1000`
- [ ] Implement `discover_tables() -> list[str]`: reflect SQLite schema to get all table names
- [ ] Implement `transfer_table(table_name: str) -> TransferResult`: for a single table:
  1. Reflect table schema from SQLite
  2. Read all rows in batches of `batch_size`
  3. Apply type coercion for each row (see Task 1.2)
  4. Insert into PostgreSQL within a transaction
  5. Return row counts (source, transferred, skipped/warned)
- [ ] Implement `transfer_all() -> MigrationReport`: iterate all tables, transfer each, collect results
- [ ] Use synchronous SQLAlchemy (not async) for the migration tool -- simpler and migration is a one-time operation
- [ ] Handle `UNIQUE` constraint violations gracefully (log warning, skip row) for idempotency

### Task 1.2: Type coercion utilities

**File(s):** `teleclaude/migration/type_coercion.py` (new)

- [ ] `coerce_datetime(value: str | None) -> datetime | None`: Parse SQLite text datetime to Python datetime. Handle ISO 8601 format and common SQLite datetime strings.
- [ ] `coerce_boolean(value: Any) -> bool | None`: SQLite stores booleans as 0/1 integers. Convert to Python bool.
- [ ] `coerce_json(value: str | None) -> dict | list | None`: Parse JSON text columns to Python objects for PostgreSQL's native JSON type.
- [ ] `coerce_integer(value: Any) -> int | None`: Handle empty strings and null values that should be integers.
- [ ] `build_coercion_map(table_name: str, columns: list) -> dict[str, Callable]`: Map column names to their coercion functions based on declared PostgreSQL column types.

### Task 1.3: Sequence reset after bulk insert

**File(s):** `teleclaude/migration/data_transfer.py` (extend)

- [ ] After transferring each table, detect serial/auto-increment columns
- [ ] Execute `SELECT setval(pg_get_serial_sequence('table', 'column'), MAX(column)) FROM table` for each serial column
- [ ] Handle tables with no serial columns (skip)
- [ ] Handle empty tables (setval to 1)

---

## Phase 2: Session Ownership Backfill

### Task 2.1: Ownership assignment

**File(s):** `teleclaude/migration/ownership.py` (new)

- [ ] `backfill_ownership(db_url: str, person_name: str, uid: int) -> int`: Update all sessions where `owner_person IS NULL` to set the migrating user as owner
- [ ] Use SQLAlchemy `update()` statement with a WHERE clause
- [ ] Return count of updated rows
- [ ] Log the backfill operation

---

## Phase 3: Integration with Existing Tools

### Task 3.1: Config split integration

**File(s):** `teleclaude/migration/config_migration.py` (new)

- [ ] Import and call Phase 4's `split_config()` function
- [ ] Locate source `config.yml` and `.env` from the detected installation
- [ ] Write output to the system config directory (from Phase 5's system layout)
- [ ] Verify output files load correctly with their respective Pydantic models
- [ ] Handle the case where config is already split (skip with message)

### Task 3.2: Doc snippet relocation

**File(s):** `teleclaude/migration/doc_relocation.py` (new)

- [ ] Copy `~/.teleclaude/docs/` contents to the system shared docs location
- [ ] Preserve the source directory (non-destructive copy, not move)
- [ ] Handle conflicts: if a file exists at the destination, skip with warning
- [ ] Rebuild the snippet index at the system location (call existing index-building logic)
- [ ] Report: files copied, files skipped, total size

---

## Phase 4: Orchestration Script

### Task 4.1: Migration orchestration

**File(s):** `bin/migrate-to-system.sh` (new)

- [ ] Pre-flight checks:
  1. Is the TeleClaude daemon stopped? (Check PID file and process list)
  2. Does the system installation exist? (Check for service user and system directories)
  3. Does the PostgreSQL database exist and is it reachable?
  4. Does the source SQLite database exist?
- [ ] Step 1: Detect existing installation (print paths found)
- [ ] Step 2: Run data transfer (`python -m teleclaude.migration.data_transfer`)
- [ ] Step 3: Run config split (`python -m teleclaude.migration.config_migration`)
- [ ] Step 4: Run ownership backfill (`python -m teleclaude.migration.ownership`)
- [ ] Step 5: Run doc relocation (`python -m teleclaude.migration.doc_relocation`)
- [ ] Step 6: Run validation (see Task 4.2)
- [ ] Step 7: Print rollback instructions
- [ ] Error handling: if any step fails, print what succeeded and what failed, suggest manual remediation
- [ ] `--dry-run` flag: run detection and pre-flight only, print what would happen

### Task 4.2: Validation module

**File(s):** `teleclaude/migration/validation.py` (new)

- [ ] `validate_row_counts(sqlite_url: str, postgres_url: str) -> list[TableComparison]`: Compare row counts for all tables
- [ ] `validate_daemon_startup(config_path: str) -> bool`: Start daemon in check mode (load config, connect to DB, return success/failure without actually serving)
- [ ] `validate_session_access(postgres_url: str) -> bool`: Query sessions table, verify at least one session is accessible
- [ ] Print summary report: table-by-table row counts, pass/fail per check, overall verdict

---

## Phase 5: Tests

### Task 5.1: Unit tests for data transfer

**File(s):** `tests/unit/test_data_transfer.py` (new)

- [ ] Test type coercion: datetime strings, booleans, JSON, integers
- [ ] Test transfer of a single table with sample data (SQLite in-memory -> PostgreSQL test DB)
- [ ] Test batch processing: verify correct behavior with batch sizes of 1, 10, 1000
- [ ] Test sequence reset: after bulk insert, verify next auto-increment value is correct
- [ ] Test idempotency: running transfer twice with same data produces no errors (unique constraint handling)
- [ ] Test transaction rollback: simulate a mid-transfer failure, verify PostgreSQL table is empty

### Task 5.2: Unit tests for ownership backfill

**File(s):** `tests/unit/test_ownership_backfill.py` (new)

- [ ] Test backfill sets owner on sessions with NULL owner
- [ ] Test backfill does not modify sessions that already have an owner
- [ ] Test backfill returns correct count

### Task 5.3: Integration test for full migration

**File(s):** `tests/integration/test_full_migration.py` (new)

- [ ] Create a sample SQLite database with representative data
- [ ] Run full migration against a test PostgreSQL database
- [ ] Verify row counts match
- [ ] Verify session ownership is set
- [ ] Verify config files are created
- [ ] Note: requires PostgreSQL test database (may be CI-only or Docker-based)

### Task 5.4: Quality checks

- [ ] Run `make test` -- all existing tests pass
- [ ] Run `make lint` -- no new lint violations
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Risks and Mitigations

- **Risk**: Type coercion edge cases cause data loss. **Mitigation**: Log every coercion with before/after values at debug level. Validation step catches row count mismatches.
- **Risk**: Large databases cause memory issues during batch transfer. **Mitigation**: Configurable batch size, streaming reads from SQLite.
- **Risk**: PostgreSQL schema doesn't match SQLite schema. **Mitigation**: Both schemas are managed by the same SQLAlchemy models (Phase 0 ensures compatibility). If discrepancy exists, the transfer will fail loudly.
- **Risk**: Migration run on a database with pending schema migrations. **Mitigation**: Pre-flight check verifies schema version matches expected version.

## Files Changed Summary

| File                                       | Change                                    |
| ------------------------------------------ | ----------------------------------------- |
| `teleclaude/migration/__init__.py`         | New: migration package                    |
| `teleclaude/migration/data_transfer.py`    | New: SQLite-to-PostgreSQL transfer engine |
| `teleclaude/migration/type_coercion.py`    | New: type coercion utilities              |
| `teleclaude/migration/ownership.py`        | New: session ownership backfill           |
| `teleclaude/migration/config_migration.py` | New: config split integration             |
| `teleclaude/migration/doc_relocation.py`   | New: doc snippet relocation               |
| `teleclaude/migration/validation.py`       | New: migration validation                 |
| `bin/migrate-to-system.sh`                 | New: orchestration shell script           |
| `tests/unit/test_data_transfer.py`         | New: data transfer tests                  |
| `tests/unit/test_ownership_backfill.py`    | New: ownership backfill tests             |
| `tests/integration/test_full_migration.py` | New: full migration integration test      |
