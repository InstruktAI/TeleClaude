# Requirements: deployment-migrations

## Goal

Introduce a migration framework so breaking changes between versions ship with
idempotent migration scripts that run automatically during upgrade. No manual
steps, no silent partial state.

## Scope

### In scope

1. **Migration manifest format** — versioned directory of numbered Python scripts
   with a `check()`/`migrate()` contract.
2. **Migration runner** — discovers, orders, and executes migrations between
   current and target version with state tracking and resumability.
3. **CLI entry point** — `telec migrate [--dry-run] [--from VERSION] [--to VERSION]`
   for manual invocation and debugging.
4. **Migration state tracking** — `~/.teleclaude/migration_state.json` records
   which migrations have been applied.

### Out of scope

- Downgrade support (rollback is manual; migration failure halts and reports)
- Auto-triggering migrations on update (handled by `deployment-auto-update`)
- Specific migration scripts for existing state (first real migration ships
  with the version that needs it)

## Success Criteria

- [ ] Migrations directory structure: `migrations/v{semver}/NNN_description.py`
- [ ] Each migration exposes `check() -> bool` and `migrate() -> bool`
- [ ] Runner discovers migrations between two versions, runs in order
- [ ] Runner skips migrations where `check()` returns True (already applied)
- [ ] Runner records completion in migration state file
- [ ] On failure: runner halts, reports which migration failed, state preserved
- [ ] `telec migrate --dry-run` lists pending migrations without executing
- [ ] `telec migrate` runs all pending migrations

## Constraints

- Migration scripts must be idempotent (`check()` gate prevents double-apply)
- No new external dependencies
- Runner must work offline (no network required)
- State file must be atomic-write safe (write to temp, rename)

## Risks

- **Corrupt migration state**: if process dies mid-write. Mitigation: atomic
  writes using temp file + rename.
- **Migration script bugs**: a non-idempotent check/migrate pair causes
  corruption on re-run. Mitigation: document the contract clearly, validate
  check() consistency in tests.

## Research

Migration patterns from Alembic, Django, and Flyway were considered during design.
The check/migrate contract is simpler than these frameworks (no ORM, no SQL).
The ordering and dynamic-loading patterns are validated by existing internal prior
art in `teleclaude/core/migrations/runner.py` (19 working migrations using
`importlib.util` + numbered scripts + state tracking). No third-party migration
library needed.
