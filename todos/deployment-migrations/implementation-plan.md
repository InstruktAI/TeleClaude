# Implementation Plan: deployment-migrations

## Overview

Lightweight migration framework: versioned directory of numbered scripts with
check/migrate contract, a runner that orders and executes them. Internal library
only. Follows patterns from existing `teleclaude/core/migrations/runner.py`.

---

## Phase 1: Core Changes

### Task 1.1: Deployment package and version utilities

**File(s):** `teleclaude/deployment/__init__.py`

- [ ] Create `teleclaude/deployment/` package
- [ ] `parse_version(ver: str) -> tuple[int, ...]` — strips leading 'v', splits, converts
- [ ] `version_cmp(a: str, b: str) -> int` — -1/0/1 comparison
- [ ] `version_in_range(ver: str, from_ver: str, to_ver: str) -> bool`
- [ ] Stdlib only — no external deps

### Task 1.2: Migration manifest directory

**File(s):** `migrations/`, `migrations/README.md`, `migrations/v1.1.0/001_example.py`

- [ ] Create `migrations/` directory with README documenting the contract
- [ ] Structure: `migrations/v1.1.0/NNN_description.py`
- [ ] Contract: `def check() -> bool`, `def migrate() -> bool`
- [ ] Example migration as documentation (config key rename scenario)

### Task 1.3: Migration runner

**File(s):** `teleclaude/deployment/migration_runner.py`

- [ ] `discover_migrations(from_ver, to_ver)` — scan `migrations/` for version
      dirs in range, return ordered list of (version, script_path) tuples
- [ ] `run_migrations(from_ver, to_ver, dry_run=False)` — execute in order,
      skip where `check()` returns True
- [ ] Dynamic loading via `importlib.util.spec_from_file_location` (same
      pattern as `teleclaude/core/migrations/runner.py`)
- [ ] State: read/write `~/.teleclaude/migration_state.json`
- [ ] Atomic writes: temp file + `os.rename`
- [ ] On failure: halt, return error with migration name + traceback
- [ ] Return result object: `{migrations_run, migrations_skipped, error}`

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: `parse_version` handles "1.2.3", "v1.2.3", edge cases
- [ ] Unit test: `discover_migrations` finds correct version range
- [ ] Unit test: migrations run in correct order (version, then script number)
- [ ] Unit test: `check()` skips already-applied migrations
- [ ] Unit test: failure halts and preserves state
- [ ] Unit test: atomic state write
- [ ] Unit test: `dry_run` returns plan without executing
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`

---

## Phase 3: Review Readiness

- [ ] Confirm requirements reflected in code
- [ ] All tasks marked `[x]`
