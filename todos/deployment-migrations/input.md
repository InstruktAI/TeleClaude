# Input: deployment-migrations

## Context

Parent todo: `mature-deployment` (decomposed). Phase 2 of 4 (parallel with versioning).
No dependencies — can build in parallel with `deployment-versioning` and `inbound-hook-service`.

## Brain dump

Every release that introduces incompatibilities ships migration manifests that
auto-reconcile. No human intervention, no manual upgrade steps.

### Migration manifest format

- Directory: `migrations/v{major}.{minor}.{patch}/`
- Each migration: numbered Python script `001_description.py`
- Each script exposes:
  - `def check() -> bool` — returns True if already applied (idempotency gate)
  - `def migrate() -> bool` — performs the change, returns True on success

### Migration runner

- Internal library — no CLI entry point
- Called by the deployment handler during update sequence
- Discovers migrations between current and target version
- Runs in version order, then script order within each version
- Skips where `check()` returns True
- Records completed migrations in `~/.teleclaude/migration_state.json`
- On failure: halts, reports which migration failed, state preserved for resume

### Shared version utilities

- `parse_version()`, `version_cmp()` — used by both migration runner and
  deployment handler. Lives in `teleclaude/deployment/__init__.py`.

### Prior art

The existing `teleclaude/core/migrations/runner.py` has 19 working database
migrations using `importlib.util` + numbered scripts + state tracking. Same
dynamic-loading and ordering patterns, different domain (filesystem vs database).
