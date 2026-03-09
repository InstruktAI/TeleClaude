# Input: tso-api

Parent: test-suite-overhaul

## Problem

API and services tests exist but many are implementation snapshots with hard-coded string assertions and over-mocking.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/api/` (8 files)
- `teleclaude/services/` (8 files)

Total: ~16 source files

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Find existing test coverage in `tests/`
3. Triage: keep behavioral tests, rewrite implementation-coupled ones, delete junk
4. Create/migrate to `tests/unit/api/test_<name>.py` and `tests/unit/services/test_<name>.py`
5. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- Mock at HTTP/network boundaries, not internal service calls
- API route tests should test request-response contracts, not middleware internals

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
