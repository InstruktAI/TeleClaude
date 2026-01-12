# Code Review: worktree-preparation

**Reviewed**: 2026-01-12
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| Worktree arrives ready for workers | ✅ | Preparation hook runs after worktree creation. |
| Project-owned preparation hook called by ensure_worktree() | ✅ | Makefile and package.json hooks detected and executed. |
| Remove environment instructions from worker commands | ✅ | `~/.agents/commands/next-build.md` no longer includes environment setup steps. |
| Guard install/init scripts from worktree usage | ✅ | install/init scripts refuse worktree execution with clear messaging. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [tests] `tests/integration/test_worktree_preparation_integration.py:40` - Test executes `npm run` directly, which will fail on environments without Node installed (likely in Python-only CI), causing false negatives.
  - Suggested fix: guard with `shutil.which("npm")` and `pytest.skip(...)`, or mock the `npm` invocation and assert it was called instead of executing it.

## Suggestions (nice to have)

- [comments] `bin/worktree-prepare.sh:6` - Script header says config generation shares the main repo database, but it writes a worktree-local `teleclaude.db` path.
  - Suggested fix: update the comment to match actual behavior.

- [comments] `bin/worktree-prepare.sh:124` - Final output claims a shared database, but the script configures a worktree-local database path.
  - Suggested fix: update the message to reflect the worktree-local DB or change the config to actually share the main DB.

## Strengths

- Worktree preparation hook integration is explicit and fails fast with clear errors.
- Guard rails in install/init scripts reduce risk of daemon misconfiguration.
- Unit coverage around `_prepare_worktree` error paths is solid.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Make the npm-based integration test resilient when npm is not installed (skip or mock).
