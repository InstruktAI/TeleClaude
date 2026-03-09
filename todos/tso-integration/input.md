# Input: tso-integration

Parent: test-suite-overhaul

## Problem

After all workers complete, `tests/integration/` needs triage. Some integration tests are actually unit tests in disguise. Some unit tests are genuinely cross-module and belong in integration. The boundary must be clean.

## Scope

- All files under `tests/integration/` (currently 29 files)
- Any cross-cutting orphan tests from `tests/unit/` that workers flagged for migration
- `tests/integration/conftest.py`
- Integration test documentation (`USE_CASE_COVERAGE.md`, `INTERACTION_COVERAGE_MAP.md`, etc.)

## Worker procedure

1. Audit each file in `tests/integration/`:
   - Does it import from 2+ teleclaude subpackages? Genuine integration test, keep
   - Does it test a single module's behavior with mocks? Unit test, migrate to `tests/unit/<module>/`
   - Is it obsolete/broken? Delete with rationale
2. Receive flagged cross-module tests from worker todos and place in `tests/integration/`
3. Ensure integration test docstrings describe the cross-module workflow being tested
4. Update `tests/integration/USE_CASE_COVERAGE.md` to reflect current state
5. Verify all integration tests pass

## Constraints

- No source files modified
- Integration tests must import from 2+ teleclaude subpackages (the definition)
- Preserve genuinely valuable cross-module workflow tests
- Do not create new integration tests — only organize existing ones

## Success criteria

- Every test in `tests/integration/` is genuinely cross-module
- No unit-level tests remain in `tests/integration/`
- All integration tests pass
- Coverage documentation is updated
