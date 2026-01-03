# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ✅ Implemented | Ready state supported in roadmap parsing and transitions. |
| R3: State machine owns checkbox transitions | ✅ Implemented | `next_prepare()`/`next_work()` call `update_roadmap_state()`. |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ✅ Implemented | Tool validates slug format, existence, self-reference, and cycles. |
| R6: `resolve_slug()` ready-only + dependency gating | ⚠️ Partial | `resolve_slug(..., ready_only=True)` does not enforce dependency gating; `next_work()` reimplements selection logic. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ⚠️ Partial | Missing tool-validation tests and a true integration test under `tests/integration/`. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/core/next_machine.py:521` - `check_dependencies_satisfied()` ignores the “done/*-slug indicates completion” rule when a dependency is still listed in `roadmap.md` but has an archive directory. This can block work items even though the dependency is effectively completed.
  - Suggested fix: if `get_archive_path(cwd, dep)` returns a path, treat the dependency as satisfied regardless of roadmap state.
- [code] `teleclaude/core/next_machine.py:287` - `resolve_slug(..., ready_only=True)` does not enforce dependency gating, contrary to R6. `next_work()` duplicates slug-selection logic, which risks inconsistent behavior if `resolve_slug` is used elsewhere.
  - Suggested fix: move dependency checks into `resolve_slug` (accept deps or read internally) and have `next_work()` call it for ready-only selection.
- [tests] `tests/unit/test_mcp_set_dependencies.py:1` - No tests cover `teleclaude__set_dependencies()` validation rules (invalid slug format, missing slug in roadmap, missing dependency slug, self-reference, circular graph). This is required by R5/R6 test requirements.
  - Suggested fix: add focused validation tests (unit or integration) that call the tool or its validation path directly.
- [repo] `.venv` - A symlink to a local virtualenv is added to version control. This is machine-specific and should not be tracked.
  - Suggested fix: remove the file from the repo and add `.venv` to `.gitignore` if not already ignored.

## Suggestions (nice to have)

- [tests] `tests/unit/test_next_machine_state_deps.py:1` - Many tests include multiple assertions, which conflicts with the “one assertion per test” directive. Consider splitting them for clearer failures.
- [docs] `todos/state-machine-refinement/state.json:1` - This appears to be a worktree-local artifact; consider removing from main repo if it isn’t intentionally tracked.

## Strengths

- Clear error messaging for “no ready items” and “dependencies unsatisfied” scenarios.
- Dependency helpers are cleanly factored and reusable.
- Roadmap state transitions are centralized and consistently invoked.

---

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| `check_dependencies_satisfied()` ignores archived dependencies | Added check for `get_archive_path(cwd, dep)` before validating roadmap state. If archived, treat as satisfied. | 0e1307e |
| `resolve_slug(..., ready_only=True)` doesn't enforce dependency gating (R6) | Added `dependencies` parameter to `resolve_slug()`. When `ready_only=True` and dependencies provided, skip slugs with unsatisfied deps. Updated `next_work()` to use refactored `resolve_slug()` instead of duplicating logic. | fa196f1 |
| Missing validation tests for `teleclaude__set_dependencies()` | Added 5 comprehensive MCP tool validation tests covering invalid slug format, slug not in roadmap, dependency not in roadmap, self-reference, and circular dependencies. | ff5d89f |
| `.venv` symlink tracked in repo (machine-specific) | Removed `.venv` from git tracking. Added `.venv` (without trailing slash) to `.gitignore` to ignore symlinks. Recreated symlink locally (ignored by git). | 41af68a |

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. ~~Honor archived `done/*-slug` completion when dependencies are still present in `roadmap.md`.~~ ✅ Fixed
2. ~~Add validation tests for `teleclaude__set_dependencies()` and move dependency gating into `resolve_slug(..., ready_only=True)` as required.~~ ✅ Fixed
3. ~~Remove the tracked `.venv` symlink from the repo.~~ ✅ Fixed
