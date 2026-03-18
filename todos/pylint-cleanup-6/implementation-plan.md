<!-- from-main: inline work delivered under human supervision -->
# Implementation Plan: pylint-cleanup-6

## Task 1: Fix pylint violations
- [x] Run pylint on assigned paths
- [x] Fix all violations
- [x] Verify clean exit
- [x] Run tests
- [x] Commit

## Notes

- Scoped `pylint` now passes for all paths listed in `requirements.md`.
- `make test` still fails only in out-of-scope areas: `tests/unit/install/test_git_wrapper_permissions.py` and `tests/unit/test_todo_from_main.py`.
- `make lint` still fails only in out-of-scope guardrail hits under `teleclaude/daemon_session.py`, `teleclaude/cli/session_auth.py`, `teleclaude/core/next_machine/`, and `scripts/helpers/nano_banana_helper.py`.
