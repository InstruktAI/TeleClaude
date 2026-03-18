# DOR Report: multi-user-system-install

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success — PASS

The input brain dump is exceptionally detailed. Problem statement, intended outcome, design decisions, and success criteria are all explicit and testable. Requirements have been formalized and updated to include the PostgreSQL decision.

### Gate 2: Scope & Size — FAIL

**This todo is too large for a single AI session.** The input itself acknowledges this: "This is a large architectural project, not a single session's work." The implementation plan proposes 7 dependent phases (Phase 0-6), each substantial enough to be its own todo.

**Remediation**: Split into sub-todos with dependency graph. The implementation plan provides the breakdown.

### Gate 3: Verification — PASS (per phase)

Each phase has clear verification criteria. Phase 0 in particular has a strong signal: the full test suite must pass on both SQLite and PostgreSQL backends. Integration tests span phase boundaries.

### Gate 4: Approach Known — PASS

Key architectural decisions are resolved:

- **Database**: SQLite for single-user (default), PostgreSQL for multi-user. Decided.
- **PostgreSQL packaging**: Not bundled. External dependency. Docker Compose as easy option. Decided.
- **ORM layer**: Already SQLAlchemy/SQLModel. Engine creation is the main change point. Verified in codebase.
- **Socket auth**: `SO_PEERCRED`/`LOCAL_PEERCRED` via Python `socket` module. Research still needed for macOS specifics.
- **Config merging**: Standard pattern, Pydantic schema already exists.
- **Service user**: Well-documented for both `launchd` and `systemd`.
- **Remaining open**: Alembic vs hand-rolled migrations (Phase 0 decision), socket file location (Phase 5 decision). These are phase-local decisions, not project-blocking.

### Gate 5: Research Complete — NEEDS WORK

- `SO_PEERCRED` (Linux) and `LOCAL_PEERCRED` (macOS) Python socket API: needs targeted research before Phase 1 build.
- Alembic for dual-dialect migrations: needs evaluation before Phase 0 build.
- `launchd` plist and `systemd` unit file conventions for Python services: needs research before Phase 5 build.
- `asyncpg` integration with SQLAlchemy async engine: needs targeted research before Phase 0 build.

### Gate 6: Dependencies & Preconditions — PASS

- `doc-access-control` is delivered.
- Session identity model is stable.
- People/identity configuration exists.
- SQLAlchemy/SQLModel already in the dependency tree.
- `asyncpg` is a standard, well-maintained library.

### Gate 7: Integration Safety — PASS

Each phase can be merged incrementally. Single-user SQLite mode continues to work throughout. Multi-user PostgreSQL mode is opt-in. No destructive changes to existing functionality.

### Gate 8: Tooling Impact — PARTIAL

Phase 0 changes the migration runner. If Alembic is adopted, that's a tooling change affecting how all future migrations are authored. The scaffolding procedure for database changes would need updating. This is phase-local and can be gated within Phase 0's own DOR.

## Assumptions

1. SQLAlchemy's async engine supports both `aiosqlite` and `asyncpg` transparently for the query patterns in use.
2. Python's `socket` module exposes peer credential retrieval on both macOS and Linux.
3. The existing command queue serialization pattern works identically on PostgreSQL (serialized writes via the queue, concurrent reads via the engine).
4. Per-user config is purely additive (preferences only); it cannot override system-level settings.
5. `sqlite_insert` (used for upserts) can be replaced with dialect-generic `insert().on_conflict_do_update()`.

## Open Questions

1. Alembic vs hand-rolled migration runner — decide during Phase 0 research.
2. Socket file location in system mode: `/tmp/` vs `/var/run/teleclaude/` — decide during Phase 5.
3. Should cost/token tracking be part of this project or a separate todo? (Recommendation: separate.)

## Recommendation

**Do not attempt to build this todo as-is.** Split into the 7 sub-todos defined in the implementation plan:

0. `multi-user-db-abstraction` — Database backend abstraction, SQLite + PostgreSQL (foundation, no dependencies)
1. `multi-user-identity` — OS user identity resolution (parallel with Phase 0)
2. `multi-user-sessions` — Session ownership & visibility (depends on 0 + 1)
3. `multi-user-admin-audit` — Admin observability & audit logging (depends on 2)
4. `multi-user-config` — Config separation into system/secrets/personal (depends on 1)
5. `multi-user-service` — Service user & system-wide installation (depends on 0 + 4)
6. `multi-user-migration` — Migration tooling, SQLite → PostgreSQL (depends on 2 + 5)

Phases 0 and 1 can be built in parallel. After both complete, two parallel tracks open: sessions/audit (2→3) and config/service/migration (4→5→6).

Each sub-todo should go through its own DOR draft → gate cycle before build.
