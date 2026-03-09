# Input: tso-cli

Parent: test-suite-overhaul

## Problem

CLI tests exist but are scattered across the flat `tests/unit/` directory. The non-TUI CLI includes the `telec` command surface, config handling, and entrypoints.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/cli/` top-level (13 files, excluding `tui/` subtree)
- `teleclaude/config/` (4 files)
- `teleclaude/entrypoints/` (4 files)

Total: ~21 source files

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Find existing test coverage in `tests/`
3. Triage: keep behavioral tests, rewrite implementation-coupled ones, delete junk
4. Create/migrate to `tests/unit/cli/test_<name>.py`, `tests/unit/config/test_<name>.py`, `tests/unit/entrypoints/test_<name>.py`
5. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- CLI tests should test command parsing and output contracts, not subprocess internals
- Config tests should test validation and merge behavior, not file I/O details

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
