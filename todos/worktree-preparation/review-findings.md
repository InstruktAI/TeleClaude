# Code Review: worktree-preparation

**Reviewed**: 2026-01-12
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| Worktree arrives ready for workers | ✅ | Worktree creation triggers preparation hook and provisions venv, config, and .env. |
| Project-owned preparation hook called by ensure_worktree() | ⚠️ | Hook is called, but config generation uses an absolute DB path instead of the required relative `teleclaude.db`. |
| Remove environment instructions from worker commands | ✅ | `~/.agents/commands/next-build.md` contains no environment setup steps. |
| Guard install/init scripts from worktree usage | ✅ | install/init scripts refuse worktree execution with clear messaging. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [requirements] `bin/worktree-prepare.sh:92` - Worktree config sets `database.path` to an absolute path, but requirements call for a relative `teleclaude.db` path.
  - Suggested fix: set `config['database']['path'] = "teleclaude.db"` (or equivalent relative path) when generating the worktree config.

- [tests] `tests/integration/test_worktree_preparation_integration.py:125` - `test_install_guard_can_be_tested_via_simulation` accepts both success and failure (`returncode in [0, 1]`), so it never validates guard behavior.
  - Suggested fix: create a temporary git repo plus worktree and run `bin/install.sh` or `bin/init.sh` from inside the worktree to assert exit code and error message, or refactor the guard into a callable function and unit test it with explicit inputs.

## Suggestions (nice to have)

- None.

## Strengths

- `_prepare_worktree` integrates cleanly into `ensure_worktree()` and fails fast on missing hooks.
- Install/init guards prevent accidental daemon hijacking from worktrees.
- Tests cover hook execution and error propagation for Makefile and package.json paths.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical or important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Use a relative `teleclaude.db` path in the generated worktree config.
2. Replace the no-op guard simulation test with a real behavior check.
