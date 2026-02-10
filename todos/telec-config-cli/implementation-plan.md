# Implementation Plan: telec-config-cli

## Overview

Implement a focused `telec config` CLI surface with three operations:

1. `get` for root-anchored subtree reads by dot path.
2. `patch` for YAML subtree merge + mandatory full-config validation.
3. `validate` for explicit preflight checks.

Keep the implementation minimal by reusing existing config loading/validation code paths
and matching existing `telec` parsing conventions.

## Phase 1: Core Changes

### Task 1.1: Add command surface and parsing in `telec`

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `CONFIG = "config"` to `TelecCommand`.
- [ ] Add completion entries for config subcommands (`get`, `patch`, `validate`).
- [ ] Route `_handle_cli_command()` to new `_handle_config(args)` dispatcher.
- [ ] Extend `_usage()` with config command help text.

### Task 1.2: Implement config command handler module

**File(s):**

- `teleclaude/cli/config_cmd.py` (new)
- [ ] Parse command arguments for:
  - `telec config get [PATH ...] [--project-root PATH] [--format yaml|json]`
  - `telec config patch [--project-root PATH] [--from-file PATH | --yaml STRING | stdin] [--format yaml|json]`
  - `telec config validate [--project-root PATH]`
- [ ] Resolve config path deterministically from explicit project root/path options.
- [ ] Implement dot-path extraction helper for `get` (single and multi-path).
- [ ] Implement deep-merge helper for patch payload application.
- [ ] Implement atomic write helper for successful patch operations.

### Task 1.3: Reusable runtime config validation entrypoint

**File(s):**

- `teleclaude/config/__init__.py`
- `teleclaude/config/loader.py` and/or new focused helper module (as needed)

- [ ] Extract or expose validation routine callable by CLI without daemon restart.
- [ ] Ensure the same validation logic used by runtime config parsing is reused.
- [ ] Return field-aware validation errors consumable by CLI output.

### Task 1.4: Enforce patch validate-before-write contract

**File(s):** `teleclaude/cli/config_cmd.py`

- [ ] Ensure patch flow is: read current config -> merge patch -> validate merged result
      -> atomic write only on success.
- [ ] Ensure failed validation exits non-zero and leaves file unchanged.
- [ ] Ensure malformed YAML / invalid patch structure exits non-zero with actionable errors.
---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Add unit tests in `tests/unit/test_telec_config_cli.py` for:
  - `get` full config and multi-path subtree retrieval.
  - `get` missing-path failure behavior.
  - `patch` success with multi-key YAML snippet.
  - `patch` validation failure (assert no file mutation).
  - `validate` success/failure exit behavior.
  - CWD-independence with explicit `--project-root`.
- [ ] Add/update integration coverage in `tests/integration/test_telec_cli_commands.py`
      for command routing and argument parsing behavior.
- [ ] Run targeted tests for telec/config command changes.
- [ ] Run full `make test`.

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify command help and usage text reflects final command contract.
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Risks and Mitigations

1. Import-time side effects from `teleclaude.config`:
   - Mitigation: isolate validation helper that accepts explicit config path.
2. Ambiguous merge semantics:
   - Mitigation: codify and test deep-merge behavior, document in CLI help.
3. Accidental partial writes:
   - Mitigation: enforce atomic replacement and test failure cases.
