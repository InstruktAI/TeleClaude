# Code Review: worktree-preparation

**Reviewed**: 2026-01-12
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| Worktree arrives ready for workers | ✅ | Preparation hook runs after worktree creation and provisions venv, config, and .env. |
| Project-owned preparation hook called by ensure_worktree() | ⚠️ | Hook name uses `worktree-prepare` instead of required `worktree:prepare`. Add an alias target or align docs. |
| Remove environment instructions from worker commands | ✅ | `~/.agents/commands/next-build.md` no longer contains environment setup steps. |
| Guard install/init scripts from worktree usage | ✅ | install/init scripts refuse worktree execution with clear messaging. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [errors] `teleclaude/core/next_machine.py:907` - `_prepare_worktree` only handles `CalledProcessError`. Missing `make` or `npm` will raise `FileNotFoundError` and bubble as an unhandled exception with unclear messaging.
  - Suggested fix: catch `FileNotFoundError` for both make and npm invocations and raise a `RuntimeError` with a clear, user facing message.

- [requirements] `Makefile:126` - Requirements specify `make worktree:prepare`, but the implementation only provides `worktree-prepare` and `_prepare_worktree` expects that name.
  - Suggested fix: add a `worktree:prepare` alias target that forwards to `worktree-prepare`, or update requirements and detection to match the chosen name.

- [tests] `tests/integration/test_worktree_preparation_integration.py:125` - `test_install_guard_can_be_tested_via_simulation` asserts `returncode in [0, 1]`, which is always true. The guard tests only check for string presence, not real behavior.
  - Suggested fix: create a temporary git repo plus worktree and run `bin/install.sh` or `bin/init.sh` from inside the worktree to assert exit code and error message. If that is too heavy, refactor the guard into a small function and unit test it with controlled inputs.

## Suggestions (nice to have)

- None.

## Strengths

- Worktree preparation hook integration fails fast with clear `RuntimeError` messaging on known failures.
- Guard rails in install/init scripts reduce risk of daemon misconfiguration.
- Unit coverage around `_prepare_worktree` error paths is solid.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical or important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Handle missing make or npm with a clear, user friendly error in `_prepare_worktree`.
2. Resolve the `worktree:prepare` vs `worktree-prepare` mismatch (alias or update requirement docs).
3. Replace the no-op guard simulation test with a meaningful behavior check.
