# Input: tso-infra

Parent: test-suite-overhaul

## Problem

The test suite has no structural enforcement — 253 orphan test files, no 1:1 source-to-test mapping, and flat `tests/unit/` directory that doesn't mirror the source tree. Before any worker can restructure module tests, the infrastructure must exist.

## Scope

1. **Feature branch**: Create `feat/test-suite-overhaul` branch from main
2. **Directory scaffold**: Create `tests/unit/<module>/` directories mirroring every `teleclaude/<module>/` directory (including nested: `adapters/discord/`, `core/next_machine/`, `cli/tui/views/`, etc.)
3. **Conftest restructure**: Audit `tests/conftest.py` and `tests/integration/conftest.py`. Extract shared fixtures that workers will need (mock adapters, fake sessions, test config). Create module-level conftest files where fixtures are module-specific.
4. **CI enforcement script**: Create a script/pytest plugin that validates the 1:1 mapping: every `.py` file under `teleclaude/` must have a corresponding `tests/unit/<mirror-path>/test_<name>.py` OR be listed in `tests/ignored.md`. Fails CI if unmapped files exist.
5. **ignored.md framework**: Update `tests/ignored.md` with a machine-parseable format (consistent heading + reason pattern) that the CI script can validate against. Preserve existing entries.
6. **Shared test constants**: If hard-coded string assertions are common, create `tests/constants.py` or `tests/fixtures/` entries for frequently asserted values (version strings, config defaults, error messages).

## Constraints

- No source files under `teleclaude/` are modified
- Existing tests must still pass after restructuring
- The scaffold is additive — create directories and files, don't move existing tests (workers handle migration)
- conftest changes must not break existing test imports

## Success criteria

- `tests/unit/` directory tree mirrors `teleclaude/` directory tree
- CI enforcement script runs and reports current mapping gaps (expected to fail until workers complete)
- `tests/ignored.md` has machine-parseable format
- All existing tests still pass after infrastructure changes
