# Input: tso-adapters

Parent: test-suite-overhaul

## Problem

The adapter layer has zero dedicated unit tests (per audit). Existing adapter-related tests are cross-cutting orphans that don't map to specific source files.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/adapters/` (6 files)
- `teleclaude/adapters/discord/` (2 files)
- `teleclaude/adapters/qos/` (3 files)
- `teleclaude/adapters/telegram/` (6 files)
- `teleclaude/transport/` (2 files)

Total: ~19 source files

## Worker procedure

For each source file:
1. Read the source file's public interface (exports, public methods, class contracts)
2. Find any existing test coverage (search `tests/` for imports/references to the source)
3. Triage existing tests: keep (behavioral), rewrite (implementation-coupled), delete (junk)
4. Create `tests/unit/<mirror-path>/test_<name>.py` with behavioral contract tests
5. Each test function gets a docstring stating the behavioral contract it verifies

## Constraints

- No source files modified — tests only
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions — use constants, fixtures, or computed values
- Mock at adapter boundaries (network, external APIs), not internal call chains
- Preserve genuinely valuable cross-cutting tests by migrating them to `tests/integration/`

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
