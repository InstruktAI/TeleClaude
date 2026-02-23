# Input: deployment-migrations

## Context

Parent todo: `mature-deployment` (decomposed). Phase 3 of 5.
Depends on: `deployment-channels`.

## Brain dump

The key innovation of the mature deployment pipeline. Every release that
introduces incompatibilities ships migration manifests that auto-reconcile.
No human intervention, no manual upgrade steps.

### Migration manifest format

- Directory: `migrations/v{major}.{minor}.{patch}/`
- Each migration: numbered Python script `001_description.py`
- Each script exposes:
  - `def check() -> bool` — returns True if already applied (idempotency gate)
  - `def migrate() -> bool` — performs the change, returns True on success

### Migration runner

- Discovers migrations between current and target version
- Runs in version order, then script order within each version
- Skips where `check()` returns True
- Records completed migrations in `~/.teleclaude/migration_state.json`
- On failure: halts, reports which migration failed, state preserved for resume
- CLI: `telec migrate [--dry-run] [--from VERSION] [--to VERSION]`

### Use cases

- Config key rename
- Schema changes in state files
- File/directory moves
- New required config values with sensible defaults

### Research needed

Migration patterns (Alembic, Django, Flyway) should be researched and indexed
before building. The check/migrate pattern is well-established but specifics
need validation.

### Open questions

- How to handle downgrades? Proposal: don't support them. Rollback is manual.
