# Code Review: worktree-preparation

**Reviewed**: 2026-01-12
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| Worktree arrives ready for workers | ⚠️ | Prep hook exists, but config generation uses system Python and a new worktree database path. |
| Project-owned preparation hook called by ensure_worktree() | ✅ | Hook detection and invocation added. |
| Remove environment instructions from worker commands | ✅ | `~/.agents/commands/next-build.md` contains no environment setup step. |
| Guard install/init scripts from worktree usage | ⚠️ | Guards added, but error message points to `make worktree:prepare` which does not exist. |

## Critical Issues (must fix)

- [code] `bin/worktree-prepare.sh:91` - Worktree prep rewrites `config.yml` to use `teleclaude.db` inside the worktree, creating additional databases and violating the single database rule.
  - Suggested fix: keep the database path pointing at the main repo database (for example `${WORKING_DIR}/teleclaude.db` or absolute path to repo root) and avoid creating per worktree DB files.

## Important Issues (should fix)

- [errors] `bin/worktree-prepare.sh:77` - Config generation runs with system `python3`, which will fail if PyYAML is not installed globally. This breaks worktree preparation on clean machines.
  - Suggested fix: run the script with the worktree venv python after `uv sync` (for example `"$WORKTREE_DIR/.venv/bin/python"`) or use `uv run python`.

- [tests] `teleclaude/core/next_machine.py:848` - New worktree preparation behavior and install/init guards lack tests, so failures can slip through.
  - Suggested fix: add targeted unit tests that validate `_prepare_worktree` invocation and error propagation, plus shell level tests for install/init guard behavior.

## Suggestions (nice to have)

- [comments] `bin/install.sh:24` - Error message points to `make worktree:prepare`, but the Makefile target is `worktree-prepare`.
  - Suggested fix: update the message to `make worktree-prepare` for accurate guidance.

- [comments] `bin/init.sh:23` - Same incorrect `make worktree:prepare` reference.
  - Suggested fix: update to `make worktree-prepare`.

## Strengths

- Worktree preparation hook is integrated into `ensure_worktree()` and provides clear failure reporting.
- Guard rails in install and init protect the main daemon from accidental worktree installs.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Stop creating per worktree databases in `bin/worktree-prepare.sh` and align with the single database rule.
2. Ensure worktree prep uses the worktree venv for config generation, and add tests for the new worktree prep and guard behavior.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Critical: Per-worktree databases created | Removed database path modification; config now preserves `${WORKING_DIR}/teleclaude.db` | 60c21fd |
| Important: System Python used for config generation | Changed to use `$WORKTREE_DIR/.venv/bin/python` after uv sync | 2134989 |
| Important: Missing tests for worktree prep and guards | Added unit tests for `_prepare_worktree` (7 tests), integration tests for full flow (7 tests) | 1f9dc57 |
| Suggestion: Incorrect make target in install.sh | Fixed `make worktree:prepare` → `make worktree-prepare` | 1f9dc57 |
| Suggestion: Incorrect make target in init.sh | Fixed `make worktree:prepare` → `make worktree-prepare` | 1f9dc57 |
