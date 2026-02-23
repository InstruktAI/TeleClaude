# Implementation Plan: deployment-migrations

## Overview

Build a lightweight migration framework: versioned directory of numbered scripts
with check/migrate contract, a runner that orders and executes them, and CLI
access. Simpler than ORM migration frameworks — no SQL, no revision graph, just
ordered idempotent scripts.

---

## Phase 1: Core Changes

### Task 1.1: Migration manifest directory structure

**File(s):** `migrations/`, `migrations/README.md`

- [ ] Create `migrations/` directory with README documenting the format
- [ ] Structure: `migrations/v1.1.0/001_description.py`
- [ ] Each script: `def check() -> bool` (True if already applied),
      `def migrate() -> bool` (True on success)
- [ ] Create an example migration as documentation: `migrations/v1.1.0/001_example.py`

### Task 1.2: Migration runner

**File(s):** `teleclaude/deployment/migration_runner.py`

- [ ] `discover_migrations(from_ver, to_ver)` — scan migrations/ for version
      dirs between from and to, return ordered list
- [ ] `run_migrations(from_ver, to_ver, dry_run=False)` — execute discovered
      migrations in order, skip where check() returns True
- [ ] State tracking: read/write `~/.teleclaude/migration_state.json`
- [ ] Atomic state writes: write to temp file, then rename
- [ ] On failure: halt, return which migration failed plus traceback
- [ ] Version comparison using `packaging.version.Version` (already a dependency)

### Task 1.3: CLI entry point

**File(s):** `teleclaude/cli/` (add subcommand)

- [ ] Add `telec migrate` subcommand
- [ ] Flags: `--dry-run`, `--from VERSION`, `--to VERSION`
- [ ] Default from=current version, to=latest available in migrations/
- [ ] Print migration plan before execution, results after

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: discover_migrations finds correct version range
- [ ] Unit test: migrations run in correct order (version, then script number)
- [ ] Unit test: check() skips already-applied migrations
- [ ] Unit test: failure halts and preserves state
- [ ] Unit test: atomic state write (crash simulation)
- [ ] Unit test: dry-run lists but does not execute
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
