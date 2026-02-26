# Implementation Plan: deployment-versioning

## Overview

Small, focused change: expose version at runtime and add a CLI command. CI and
release pipelines already exist and require no changes.

---

## Phase 1: Core Changes

### Task 1.1: Bump pyproject.toml version

**File(s):** `pyproject.toml`

- [x] Change `version = "0.1.0"` to `version = "1.0.0"`

### Task 1.2: Expose `__version__` at runtime

**File(s):** `teleclaude/__init__.py`

- [x] Add `__version__` using `importlib.metadata.version("teleclaude")`
- [x] Add fallback: if `PackageNotFoundError`, parse version from pyproject.toml
- [x] Export `__version__` in `__all__` if one exists

### Task 1.3: Add `telec version` command

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `VERSION = "version"` to `TelecCommand` enum
- [x] Add `"version": CommandDef(desc="Print version, channel, and commit")` to `CLI_SURFACE`
- [x] Add handler function that prints: `TeleClaude v{version} (channel: alpha, commit: {short_hash})`
- [x] Get commit hash via `git rev-parse --short HEAD` (subprocess, graceful fail)
- [x] Channel defaults to "alpha" (hardcoded until deployment-channels ships)

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: `from teleclaude import __version__` returns a semver string
- [ ] Unit test: `telec version` CLI output matches expected format
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
