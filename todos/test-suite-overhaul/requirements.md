# Requirements: test-suite-overhaul

## Goal

Replace the current test suite with a TDD-first, behaviorally specified test suite where every source file has exactly one corresponding test file, and every test describes a behavioral contract — not an implementation snapshot.

## Scope

### In scope:
- All test files under `tests/unit/` and `tests/integration/`
- All source files under `teleclaude/` (~354 files)
- Pytest configuration in `pyproject.toml`
- Conftest fixtures (`tests/conftest.py`, `tests/integration/conftest.py`)
- `tests/ignored.md` (update with current exemptions)
- CI enforcement (1:1 mapping check) [inferred: not mentioned in input]

### Out of scope:
- Source code behavior changes — this refactor changes tests only, never source logic
- E2E test infrastructure (`tests/E2E_USE_CASES.md` stays as documentation)
- Test performance optimization (parallelism config stays as-is)

## Success Criteria

- [ ] Every source file under `teleclaude/` has exactly one test file at `tests/unit/<mirror-path>/test_<name>.py` [inferred: mirror-path naming convention], or is listed in `tests/ignored.md` with a valid reason
- [ ] Zero orphan test files — every test file maps to exactly one source file, or lives in `tests/integration/` with a clear cross-module scope
- [ ] Zero hard-coded string assertions — all string comparisons use constants, fixtures, enums, or computed values [inferred: zero threshold from input's 81.6% problem statement]
- [ ] No test function uses more than 5 `@patch` decorators [inferred: threshold of 5 from input's 15+ problem statement]
- [ ] Every test function has a docstring stating the behavioral contract it verifies [inferred: docstring requirement not in input — derived from "TDD behavioral contracts" intent]
- [ ] All tests pass (`pytest tests/` exits 0)
- [ ] No source file behavior is changed — only test files are created/modified/deleted
- [ ] Integration tests in `tests/integration/` test cross-module workflows, not unit-level behavior

## Constraints

- Feature branch `feat/test-suite-overhaul` — no commits to main until integrated
- Workers must not modify source files under `teleclaude/` — tests only
- The `tests/ignored.md` exemption list is the only path to skip 1:1 coverage
- Existing integration tests that are genuinely valuable (cross-module workflows) migrate to `tests/integration/` — they are not deleted
- Async tests use `pytest-asyncio` with `asyncio_mode = "auto"` (existing config)

## Risks

- **Scale**: 351 source files, 266 test files, 3,438 test functions. Workers may hit context limits on large modules. Mitigation: break `core/` and `cli/tui/` into sub-scopes.
- **False deletions**: A test categorized as "junk" might actually catch a real edge case. Mitigation: workers must read the source file's public interface before triaging its tests. If uncertain, keep and mark for review.
- **Merge conflicts**: Multiple workers touching conftest or shared fixtures. Mitigation: conftest changes are orchestrator-only, workers don't modify shared fixtures.
- **Test count drop**: The suite will likely shrink from 3,438 to ~1,500-2,000 functions. This is expected — fewer, better tests that actually catch regressions.
