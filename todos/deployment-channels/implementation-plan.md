# Implementation Plan: deployment-channels

## Overview

Add deployment channel config and a version watcher cron job. Follows existing
job patterns (`jobs/base.py`, `teleclaude.yml` scheduling). The watcher produces
a signal file consumed by the future auto-update executor.

---

## Phase 1: Core Changes

### Task 1.1: Config schema for deployment channels

**File(s):** `teleclaude/config/schema.py`, `teleclaude.yml`

- [ ] Add `deployment` section to config schema:
  ```yaml
  deployment:
    channel: alpha # alpha | beta | stable
    pinned_minor: '' # required when channel=stable (e.g. "1.3")
  ```
- [ ] Validate: `pinned_minor` required when `channel=stable`, ignored otherwise
- [ ] Default: `channel: alpha`, `pinned_minor: ""`
- [ ] Add validation in config loading (daemon startup)

### Task 1.2: Version watcher job

**File(s):** `jobs/version_watcher.py`

- [ ] Create `VersionWatcherJob(Job)` with `name = "version_watcher"`
- [ ] `run()` reads channel from config, dispatches to channel-specific check:
  - Alpha: `git ls-remote origin HEAD` → compare with `git rev-parse HEAD`
  - Beta: GitHub API `GET /repos/{owner}/{repo}/releases/latest` → compare with `__version__`
  - Stable: GitHub API `GET /repos/{owner}/{repo}/releases` → filter patches within pinned minor
- [ ] On newer version found: write `~/.teleclaude/update_available.json`
- [ ] On current: remove signal file if it exists
- [ ] Handle network errors: log warning, skip cycle, do not write stale data

### Task 1.3: Register job in teleclaude.yml

**File(s):** `teleclaude.yml`

- [ ] Add version_watcher job with `schedule: "*/5 * * * *"` (every 5 minutes)
- [ ] Register in `jobs/__init__.py`

### Task 1.4: Update `telec version` to show configured channel

**File(s):** `teleclaude/cli/` (version subcommand from deployment-versioning)

- [ ] Read `deployment.channel` from config instead of hardcoded "alpha"
- [ ] Display pinned minor for stable channel

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: config validation accepts valid channel values, rejects invalid
- [ ] Unit test: stable channel requires pinned_minor
- [ ] Unit test: version watcher alpha check (mock git ls-remote)
- [ ] Unit test: version watcher beta check (mock GitHub API)
- [ ] Unit test: signal file written/removed correctly
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
