# Implementation Plan: mature-deployment

## Overview

This is a large initiative that should be decomposed into 5 sequential sub-todos.
Each phase is independently deliverable and builds on the previous. The plan below
describes the full scope; the DOR report will recommend splitting before build.

---

## Phase 1: Versioning Foundation

Establish proper semantic versioning and CI pipeline as the base everything else
depends on.

### Task 1.1: Runtime version access

**File(s):** `pyproject.toml`, `teleclaude/__init__.py`

- [ ] Update pyproject.toml version to a meaningful starting point (e.g. `1.0.0`)
- [ ] Expose `__version__` in teleclaude package (read from pyproject.toml metadata)
- [ ] Add a `telec version` subcommand that prints current version

### Task 1.2: GitHub Actions CI

**File(s):** `.github/workflows/ci.yml`

- [ ] Create CI workflow that runs on push to main and PRs
- [ ] Run `make lint` and `make test`
- [ ] Cache uv/pip dependencies for speed

### Task 1.3: GitHub Actions release workflow

**File(s):** `.github/workflows/release.yml`

- [ ] Create release workflow triggered by version tags (`v*`)
- [ ] Create GitHub Release with changelog from commit messages
- [ ] Attach migration manifest directory listing (if migrations exist for that version)

---

## Phase 2: Channel Config + Version Watcher

### Task 2.1: Deployment channel config schema

**File(s):** `config.yml`, `teleclaude/config.py`

- [ ] Add `deployment.channel` to config schema (enum: alpha | beta | stable)
- [ ] Add `deployment.pinned_minor` for stable channel (e.g. "1.3")
- [ ] Default to `alpha` for backward compatibility during rollout
- [ ] Validate config on daemon startup

### Task 2.2: Version watcher background job

**File(s):** `jobs/version_watcher.py`, `teleclaude.yml`, `docs/project/spec/jobs/version-watcher.md`

- [ ] Create a script job (not agent job — this is deterministic)
- [ ] Schedule: every 5 minutes (matches cron runner interval)
- [ ] Alpha channel: `git ls-remote origin HEAD` and compare with current HEAD
- [ ] Beta channel: query GitHub API for latest release, compare with current version
- [ ] Stable channel: query GitHub API for latest patch within pinned minor
- [ ] If newer version available: write signal file (e.g. `~/.teleclaude/update_available.json`)
- [ ] Signal file contains: `{ "current": "1.2.0", "available": "1.3.0", "channel": "beta" }`
- [ ] Optional: broadcast version-available notification via Redis for faster propagation

---

## Phase 3: Migration Framework

### Task 3.1: Migration manifest format

**File(s):** `migrations/README.md`

- [ ] Define directory structure: `migrations/v{major}.{minor}.{patch}/`
- [ ] Each migration is a numbered Python script: `001_description.py`
- [ ] Each script exposes `def migrate() -> bool` and `def check() -> bool`
- [ ] `check()` returns True if migration was already applied (idempotency gate)
- [ ] `migrate()` performs the change, returns True on success

### Task 3.2: Migration runner

**File(s):** `teleclaude/deployment/migration_runner.py`

- [ ] Discover migrations between current version and target version
- [ ] Run migrations in version order, then script order within each version
- [ ] Skip migrations where `check()` returns True (already applied)
- [ ] Record completed migrations in `~/.teleclaude/migration_state.json`
- [ ] On failure: halt, report which migration failed, preserve state for resume
- [ ] CLI entry point: `telec migrate [--dry-run] [--from VERSION] [--to VERSION]`

### Task 3.3: Migration authoring guide

**File(s):** `docs/project/procedure/authoring-migrations.md`

- [ ] Document how to write a migration
- [ ] Document idempotency requirements
- [ ] Document the check/migrate pattern
- [ ] Include examples (config key rename, schema change, file move)

---

## Phase 4: Auto-Deploy Integration

### Task 4.1: Update executor

**File(s):** `teleclaude/deployment/update_executor.py`

- [ ] Watch for signal file from version watcher
- [ ] Execute update sequence: fetch → checkout/pull → migrate → install → restart
- [ ] Alpha: `git pull --ff-only origin main`
- [ ] Beta/Stable: `git fetch --tags && git checkout v{version}`
- [ ] Run migration runner for version gap
- [ ] Run `make install`
- [ ] Trigger daemon restart (exit code 42, same as current mechanism)
- [ ] Update deploy status in Redis (same key pattern as current)

### Task 4.2: Wire into daemon lifecycle

**File(s):** `teleclaude/daemon.py` or background worker registration

- [ ] Register update check as a background worker (or use cron job signal)
- [ ] On signal file detection: schedule update during low-activity window
- [ ] Or: run immediately if no sessions are actively processing input
- [ ] Log update lifecycle events

---

## Phase 5: Cleanup

### Task 5.1: Remove telec deploy command

**File(s):** MCP handlers, telec CLI, deploy_service.py

- [ ] Remove `teleclaude__deploy` from MCP tool definitions and handlers
- [ ] Remove `telec deploy` CLI subcommand
- [ ] Delete `teleclaude/services/deploy_service.py`
- [ ] Remove deploy-related Redis system command handling
- [ ] Update `docs/project/procedure/deploy.md` to reflect new automated flow
- [ ] Update README.md deploy references
- [ ] Update AGENTS.md / agent artifacts if they reference deploy

### Task 5.2: Update documentation

**File(s):** docs, specs, procedures

- [ ] Update `docs/project/spec/teleclaude-config.md` with deployment config
- [ ] Update `docs/project/design/architecture/system-overview.md`
- [ ] Update `docs/project/spec/mcp-tool-surface.md`
- [ ] Write `docs/project/design/architecture/deployment-pipeline.md`

---

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Unit tests for migration runner
- [ ] Unit tests for version watcher
- [ ] Unit tests for update executor
- [ ] Integration test: mock version check → signal → update sequence
- [ ] Run `make test`

### Task 6.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
