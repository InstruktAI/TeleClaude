# Requirements: deployment-migrations

## Goal

Introduce a migration framework so breaking changes between versions ship with
idempotent migration scripts that run automatically during upgrade. No manual
steps, no silent partial state. Internal library only — no CLI.

## Scope

### In scope

1. **Migration manifest format** — versioned directory of numbered Python scripts
   with a `check()`/`migrate()` contract.
2. **Migration runner** — discovers, orders, and executes migrations between
   current and target version with state tracking and resumability.
3. **Migration state tracking** — `~/.teleclaude/migration_state.json` records
   which migrations have been applied.
4. **Shared version utilities** — `parse_version()`, `version_cmp()`,
   `version_in_range()` in `teleclaude/deployment/__init__.py`, used by both
   the migration runner and the deployment handler.

### Out of scope

- CLI entry point (migrations are internal, triggered by the update executor)
- Downgrade support (migration failure halts and reports; rollback is manual)
- Auto-triggering migrations on update (handled by `deployment-channels`)
- Specific migration scripts (first real migration ships with the version that needs it)

## Success Criteria

- [ ] Migrations directory structure: `migrations/v{semver}/NNN_description.py`
- [ ] Each migration exposes `check() -> bool` and `migrate() -> bool`
- [ ] Runner discovers migrations between two versions, runs in order
- [ ] Runner skips migrations where `check()` returns True
- [ ] Runner records completion in migration state file
- [ ] On failure: runner halts, reports which migration failed, state preserved
- [ ] Version utilities handle semver correctly (with and without `v` prefix)
- [ ] Runner callable as library: `run_migrations(from_ver, to_ver)`

## Constraints

- Migration scripts must be idempotent (`check()` gate prevents double-apply)
- No new external dependencies
- Runner must work offline (no network required)
- State file must be atomic-write safe (write to temp, rename)
- No CLI — this is a library consumed by the deployment handler

## Risks

- **Corrupt migration state**: process dies mid-write. Mitigation: atomic
  writes using temp file + rename.
- **Non-idempotent scripts**: a broken check/migrate pair causes corruption
  on re-run. Mitigation: document the contract, validate in tests.

## Prior Art

Existing `teleclaude/core/migrations/runner.py` has 19 working database
migrations using `importlib.util` + numbered scripts + state tracking.
Same patterns, different domain. No third-party library needed.
