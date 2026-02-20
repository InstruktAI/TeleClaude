# DOR Report: multi-user-migration

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success -- PASS

The goal is clear and well-bounded: migrate existing single-user data to system-wide multi-user layout. Success criteria are concrete (row counts match, daemon starts, sessions accessible). The non-destructive approach (preserve SQLite, print rollback instructions) is the right safety model.

### Gate 2: Scope & Size -- PASS

The migration is a well-defined pipeline: detect -> transfer -> split config -> backfill ownership -> relocate docs -> validate. Each step is a focused module. The orchestration script ties them together. The implementation plan has 13 tasks -- substantial but coherent for a single session.

### Gate 3: Verification -- PASS

Strong verification model:

- Row count comparison between source and target for every table
- Daemon startup verification against the new backend
- Session accessibility check
- Type coercion logging for debugging
- Transaction rollback on failure ensures clean state

### Gate 4: Approach Known -- PASS

The technical approach is well-understood:

- SQLAlchemy reflection for schema discovery (standard feature)
- Batch read/write for data transfer (standard pattern)
- Type coercion for SQLite -> PostgreSQL (well-documented differences)
- Sequence reset via `setval()` (standard PostgreSQL operation)
- Transaction-scoped writes for atomicity

No novel patterns. The main complexity is handling edge cases in type coercion, which is a known-quantity problem.

### Gate 5: Research Complete -- NEEDS WORK

The validation approach for data transfer needs more definition:

- **Row count comparison is necessary but not sufficient**: Should we also compare checksums or sample rows? What about JSON column content?
- **Datetime format variations in existing SQLite data**: Need to survey the actual datetime formats stored in the production database to ensure the coercion handles all variants.
- **PostgreSQL `setval()` behavior with empty tables**: Edge case that needs verification.

### Gate 6: Dependencies & Preconditions -- NEEDS WORK

This phase has the most dependencies of any phase in the project:

- **Phase 0 (`multi-user-db-abstraction`)**: Must be complete -- PostgreSQL backend must work.
- **Phase 2 (`multi-user-sessions`)**: Must be complete -- session ownership columns must exist.
- **Phase 4 (`multi-user-config`)**: Must be complete -- config split tool is imported and reused.
- **Phase 5 (`multi-user-service`)**: Must be complete -- system directories and service user must exist.

All four dependencies are hard blockers. None can be worked around.

### Gate 7: Integration Safety -- PASS

The migration is explicitly non-destructive:

- SQLite file is read-only during migration
- Original config files are never modified
- PostgreSQL writes are transactional (rollback on failure)
- Rollback path is documented: stop system daemon, revert to single-user mode

### Gate 8: Tooling Impact -- N/A

The migration tool is a one-time operation, not ongoing tooling.

## Assumptions

1. SQLAlchemy reflection correctly discovers all tables and columns in the SQLite database.
2. The SQLite and PostgreSQL schemas are identical (both managed by the same SQLAlchemy models after Phase 0).
3. Datetime values in SQLite are stored in ISO 8601 format (the format used by Python's `datetime.isoformat()`).
4. JSON columns in SQLite contain valid JSON (no truncated or corrupted values).
5. The PostgreSQL database is empty when migration runs (fresh install from Phase 5's installer).

## Open Questions

1. **Validation depth**: Is row count comparison sufficient, or should the migration also verify sample rows / checksums? Recommendation: start with row counts; add checksum comparison as a stretch goal.
2. **Duplicate migration handling**: What if the user runs the migration twice against a non-empty PostgreSQL? Current plan: the script checks if the target has data and refuses to run unless `--force` is specified. With `--force`, it truncates all target tables first.
3. **Schema version check**: Should the migration enforce that the SQLite database has been fully schema-migrated before export? Recommendation: yes -- run pending migrations on SQLite first.

## Score: 5/10

**Status: needs_work**

This phase is well-designed but has four hard dependencies that must all be complete before build can start. The SQLite-to-PostgreSQL data transfer validation approach also needs clearer definition before implementation.

**Blockers:**

- Depends on Phases 0 (`multi-user-db-abstraction`), 2 (`multi-user-sessions`), 4 (`multi-user-config`), and 5 (`multi-user-service`)
- SQLite-to-PostgreSQL data transfer validation approach needs definition (row counts vs checksums vs sample verification)
