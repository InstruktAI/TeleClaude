# Input: tso-hooks

Parent: test-suite-overhaul

## Problem

The hooks subsystem (23 files including adapters, normalizers, and utils) processes events through a pipeline. Tests exist but are scattered and don't consistently map to source files.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/hooks/` top-level (14 files)
- `teleclaude/hooks/adapters/` (5 files)
- `teleclaude/hooks/normalizers/` (3 files)
- `teleclaude/hooks/utils/` (1 file)

Total: ~23 source files

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Find existing test coverage in `tests/`
3. Triage: keep behavioral tests, rewrite implementation-coupled ones, delete junk
4. Create/migrate to `tests/unit/hooks/test_<name>.py`, `tests/unit/hooks/adapters/test_<name>.py`, etc.
5. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- Hook tests should test the hook contract (input to output transformation), not the registration mechanism
- Normalizer tests should test normalization rules with diverse inputs

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
