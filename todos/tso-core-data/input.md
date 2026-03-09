# Input: tso-core-data

Parent: test-suite-overhaul

## Problem

`core/` is the largest module (103 files) and the most critical. The data model layer (models, events, metadata, session management, database, config) underpins everything. Current tests over-mock internal state instead of testing behavioral contracts.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/core/` top-level data-oriented files (~27 files: models, events, metadata, session*, state*, db*, config*, message*, notification*, etc.)
- `teleclaude/core/migrations/` (32 files)

Total: ~59 files (but many migrations may be exempt)

The split between this todo and `tso-core-logic` is: this todo covers data definitions, persistence, and session state. `tso-core-logic` covers behavioral orchestration, routing, and integration.

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Determine if the file is testable or should be in `ignored.md` (migrations, pure dataclasses, enum definitions)
3. Find existing test coverage in `tests/`
4. Triage: keep behavioral tests, rewrite implementation-coupled ones, delete junk
5. Create/migrate to `tests/unit/core/test_<name>.py` and `tests/unit/core/migrations/test_<name>.py`
6. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- Migration files: test only if they contain non-trivial transform logic. Simple schema migrations go to `ignored.md`
- Pure dataclasses/enums with no business logic go to `ignored.md` (already partially documented)
- Database tests mock at the DB boundary, not at query internals

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- Migration exemptions are documented with rationale
- All new tests pass
- All tests have behavioral docstrings
