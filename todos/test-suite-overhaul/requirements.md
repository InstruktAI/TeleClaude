# Requirements: test-suite-overhaul

## Goal

Build a new test suite from scratch against the refactored codebase. Every source file gets exactly one corresponding test file. Every test describes a behavioral contract — not an implementation snapshot. No salvaging from the old suite.

## Context

The previous test suite (1,106 functions, 280 files) was deleted entirely. Audit showed ~60% were junk (string snapshots, trivial mock-return assertions). The remaining ~40% tested behavior against module boundaries that no longer exist after the refactor-large-files work.

This todo depends on `refactor-large-files` completing first. The module structure will be different — all test paths, imports, and conftest scaffolding must be built against the new layout.

## Scope

### In scope:
- All source files under `teleclaude/` (post-refactor module structure)
- New `tests/unit/` directory mirroring the refactored source tree
- New `tests/integration/` for cross-module workflow tests
- Pytest configuration updates in `pyproject.toml`
- Conftest fixtures (root + per-module where needed)
- `tests/ignored.md` exemption list for files that don't need unit tests
- CI enforcement of 1:1 mapping via `tools/lint/test_mapping.py`

### Out of scope:
- Source code behavior changes — this writes tests only
- E2E test infrastructure
- Test performance optimization

## Success Criteria

- [ ] Every source file under `teleclaude/` has exactly one test file at `tests/unit/<mirror-path>/test_<name>.py`, or is listed in `tests/ignored.md` with a valid reason
- [ ] Zero orphan test files
- [ ] Zero hard-coded string assertions — all comparisons use constants, fixtures, enums, or computed values
- [ ] No test function uses more than 5 `@patch` decorators
- [ ] Every test function has a docstring stating the behavioral contract it verifies
- [ ] All tests pass (`pytest tests/` exits 0)
- [ ] Integration tests test cross-module workflows (imports from 2+ teleclaude subpackages)
- [ ] CI check validates 1:1 mapping
- [ ] `make lint` passes with no regressions

## Constraints

- Feature branch per child work item — no direct commits to main
- Workers must not modify source files under `teleclaude/` — tests only
- The `tests/ignored.md` exemption list is the only path to skip 1:1 coverage
- Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- tso-infra scaffold must be regenerated against the new module structure before module workers begin

## Risks

- **Stale tso-infra scaffold**: The previous tso-infra delivery created conftest.py stubs for the old module structure. Those were deleted with the old tests. The infra scaffold must be regenerated after refactoring completes.
- **Scale**: Post-refactor file count will be higher (more, smaller files). Mitigation: the smaller files are simpler to test.
- **No reference**: Starting from scratch means no old tests to crib from. Mitigation: workers read the source file's public interface and write behavioral contracts from first principles.
