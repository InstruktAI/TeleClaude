<!-- from-main: inline work delivered under human supervision -->
# Implementation Plan: pylint-cleanup-2

## Task 1: Fix pylint violations
- [x] Run pylint on assigned paths
- [x] Fix all violations
- [x] Verify clean exit
- [x] Run tests
- [x] Commit

## Notes

- `pylint teleclaude/adapters/discord teleclaude/adapters/qos` now exits 0.
- Focused regression coverage passes with `pytest tests/unit/adapters/discord tests/unit/adapters/qos`.
- `make lint` is blocked by existing guardrail failures in unrelated files outside this todo's scope.
- `make test` is blocked by existing failing tests in unrelated files outside this todo's scope.
