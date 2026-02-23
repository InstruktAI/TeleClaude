# Implementation Plan: deployment-auto-update

## Overview

Create an update executor that watches for the version watcher's signal file and
orchestrates the full update sequence. Wire it into the daemon lifecycle. Reuses
existing restart mechanism (exit code 42) and Redis status reporting.

---

## Phase 1: Core Changes

### Task 1.1: Update executor

**File(s):** `teleclaude/deployment/update_executor.py`

- [ ] `check_for_update()` — reads `~/.teleclaude/update_available.json`, returns
      update info or None
- [ ] `execute_update(update_info)` — full sequence:
  1. Log update start
  2. Update Redis status to "updating"
  3. Fetch code:
     - Alpha: `git pull --ff-only origin main`
     - Beta/Stable: `git fetch --tags && git checkout v{version}`
  4. Run migration runner: `migration_runner.run_migrations(current, target)`
  5. Run `make install` (subprocess)
  6. Remove signal file
  7. Update Redis status to "restarting"
  8. Trigger restart via `sys.exit(42)`
- [ ] On any step failure: log error, update Redis status to "update_failed",
      do NOT restart, preserve state for retry
- [ ] Handle ff-only failure gracefully (log, skip, don't force)

### Task 1.2: Wire into daemon lifecycle

**File(s):** `teleclaude/daemon.py` or background task registration

- [ ] Register periodic check (reuse cron interval or daemon background loop)
- [ ] On signal file detected: call execute_update()
- [ ] Log update lifecycle events at INFO level

### Task 1.3: Redis status integration

**File(s):** `teleclaude/deployment/update_executor.py`

- [ ] Use same Redis status key pattern as deploy_service.py:
      `system_status:{computer_name}:deploy`
- [ ] Status payloads: "checking", "updating", "migrating", "installing",
      "restarting", "update_failed"

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: check_for_update reads signal file correctly
- [ ] Unit test: execute_update alpha path (mock git, make install)
- [ ] Unit test: execute_update beta path (mock git fetch + checkout)
- [ ] Unit test: migration failure halts update (no restart triggered)
- [ ] Unit test: signal file removed after successful update
- [ ] Integration test: mock full sequence signal -> update -> restart
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
