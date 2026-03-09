# Input: tso-core-logic

Parent: test-suite-overhaul

## Problem

Core behavioral logic (state machines, orchestration, routing, integration bridges) has tests that are heavily over-mocked — some files have 15+ `@patch` decorators. Tests confirm mock wiring rather than behavioral contracts.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/core/` top-level behavioral files (~27 files: tmux_io, roadmap, agent_*, orchestrat*, rout*, dispatch*, process_message, etc.)
- `teleclaude/core/next_machine/` (4 files)
- `teleclaude/core/operations/` (2 files)
- `teleclaude/core/integration/` (11 files)

Total: ~44 files

The split between this todo and `tso-core-data` is: this todo covers behavioral orchestration, routing, and integration. `tso-core-data` covers data definitions, persistence, and session state.

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Find existing test coverage in `tests/`
3. Triage: keep behavioral tests, rewrite implementation-coupled ones (especially over-mocked ones), delete junk
4. Create/migrate to `tests/unit/core/test_<name>.py`, `tests/unit/core/next_machine/test_<name>.py`, etc.
5. Each test function gets a behavioral contract docstring
6. Specifically target files with 15+ `@patch` decorators — these are the worst offenders

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- State machine tests: test transition contracts (given state X and event Y, expect state Z), not internal method calls
- Integration bridge tests: test the bridge contract, mock the external side only
- If a function is hard to test without excessive mocking, note it for `tso-integration`

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- Zero files with >5 `@patch` decorators per test function
- All new tests pass
- All tests have behavioral docstrings
