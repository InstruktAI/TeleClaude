# DOR Report: multi-user-db-abstraction

## Assessment

### Gate 1: Intent & Success -- PASS

The goal is precise: make the database engine configurable (SQLite default, PostgreSQL opt-in). The problem statement identifies six specific areas of SQLite coupling with file paths and line numbers. Success criteria are testable: full test suite on both backends, CI matrix, backward compatibility. No ambiguity in what "done" means.

### Gate 2: Scope & Size -- PASS

This is a focused infrastructure change within one subsystem (the database layer). The touchpoints are well-bounded: `db.py`, config, migration runner, and CI. The implementation plan has 13 tasks across 4 phases. Fits in a single focused session, possibly two if Alembic setup is slower than expected.

### Gate 3: Verification -- PASS

Strong verification story:

- `make test` on SQLite (regression) and PostgreSQL (new coverage)
- `make lint` (code quality)
- CI matrix ensures both backends stay green
- Backward compatibility: omitting `database:` config must produce identical behavior
- Each task has a concrete, checkable outcome

### Gate 4: Approach Known -- PASS

The approach builds on existing infrastructure:

- SQLAlchemy already handles dialect differences for most queries
- Engine creation is a URL change + conditional PRAGMAs
- Alembic is the standard SQLAlchemy migration tool, well-documented
- `session.merge()` is a known pattern for dialect-agnostic upserts
- Docker Compose for PostgreSQL is standard practice

No novel techniques required. All patterns are well-established in the SQLAlchemy ecosystem.

### Gate 5: Research Complete -- NEEDS WORK

Two research gaps remain before build:

1. **asyncpg + SQLAlchemy async engine**: The combination is documented but untested in this codebase. Specific questions:
   - Connection pool behavior differences vs aiosqlite (pool_pre_ping, pool recycling)
   - Error types and handling (asyncpg exceptions vs aiosqlite exceptions)
   - Transaction semantics (autocommit behavior, nested transactions)
   - Impact on the `_session()` context manager pattern used throughout `db.py`

2. **Alembic async migration runner**: Alembic's async support was added in 1.12. Questions:
   - Configuration for async engines in `env.py` (`run_async` flag)
   - How to detect existing hand-rolled migrations on SQLite and stamp Alembic baseline
   - Interaction between Alembic's version table (`alembic_version`) and the existing `schema_migrations` table
   - Whether Alembic auto-generate correctly reflects all SQLModel model definitions (JSON columns, indexes, constraints)

**Remediation**: 1-2 hours of targeted research with a test PostgreSQL instance before build. Create a minimal proof-of-concept: SQLAlchemy async engine with asyncpg, Alembic init, one migration, verify round-trip.

### Gate 6: Dependencies & Preconditions -- PASS

- `asyncpg` is a mature, widely-used library (10k+ GitHub stars, active maintenance)
- `alembic` is the official SQLAlchemy migration tool (7k+ stars, maintained by the SQLAlchemy team)
- `psycopg2` (for sync helpers) is the standard PostgreSQL adapter
- Docker is already used in the project for other purposes
- No external approvals or access needed
- No dependency on other multi-user phases (this is Phase 0, the foundation)

### Gate 7: Integration Safety -- PASS

- SQLite remains the default. Existing users experience zero change.
- PostgreSQL is opt-in via explicit config.
- The `Db` class interface (methods like `create_session`, `get_session`, etc.) does not change -- only the internal engine creation.
- Module-level singleton pattern (`db = Db(...)`) is preserved.
- Event bus, adapter client, and all consumers of `db` are unaffected.

### Gate 8: Tooling Impact -- PARTIAL

If Alembic is adopted (recommended):

- Future migration authoring changes: `alembic revision --autogenerate -m "description"` instead of creating numbered Python files
- Developers need Alembic CLI or a Makefile wrapper
- The hand-rolled `schema_migrations` table becomes legacy (Alembic uses `alembic_version`)
- Migration testing workflow changes: run `alembic upgrade head` instead of relying on `Db.initialize()` alone

**Remediation**: Document the new migration workflow. Add Makefile targets (`make migration`, `make migrate`). The change is straightforward and well-understood.

## Assumptions

1. SQLAlchemy's async engine supports both `aiosqlite` and `asyncpg` transparently for the ORM query patterns used in `db.py` (all are `select()`, `update()`, `delete()` via SQLModel).
2. Alembic auto-generate correctly reflects SQLModel model definitions including JSON text columns, indexes, and constraints.
3. The existing 17 hand-rolled migrations can be frozen as SQLite-only and replaced by an Alembic baseline without re-running them.
4. `session.merge()` is an adequate replacement for `sqlite_insert(...).on_conflict_do_update()` for the voice assignment use case.
5. PostgreSQL 16 is the target version (current LTS).

## Open Questions

1. **Alembic auto-generate fidelity**: Do the SQLModel models in `db_models.py` fully represent the schema, or does `schema.sql` contain constraints/indexes not reflected in the models? This must be verified before creating the Alembic baseline.
2. **Sync helper future**: The two sync functions (`_fetch_session_id_sync`, `get_session_field_sync`) are used by standalone scripts. Should they be refactored to read engine URL from config, or should they be deprecated in favor of an async API? Decision can be made during build.

## Score: 6/10

Research gates (Gate 5) are the primary gap. The approach is sound and the scope is well-defined, but the asyncpg integration and Alembic async configuration need hands-on validation before committing to the build. Gate 8 (tooling impact) is minor and addressable with documentation.

**Recommendation**: Conduct targeted research (asyncpg + SQLAlchemy async PoC, Alembic async init), then re-assess. Expected post-research score: 8/10.
