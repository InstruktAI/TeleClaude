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
| R6: `resolve_slug()` ready-only + dependency gating | ✅ Implemented | Ready-only selection gates on dependency satisfaction when provided. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ⚠️ Partial | No new `tests/integration/` coverage; “integration” test is placed in unit tests. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [tests] `tests/unit/test_mcp_set_dependencies.py:16` - Unused import `Db` will trigger lint failures.
  - Suggested fix: remove the unused import.
- [tests] `tests/integration/` - Required integration coverage is missing; the workflow/dependency test is implemented in `tests/unit/` instead of `tests/integration/`.
  - Suggested fix: add/relocate the full workflow and dependency-blocking tests to `tests/integration/` as specified in requirements.

## Suggestions (nice to have)

- [tests] `tests/unit/test_next_machine_state_deps.py` - Many tests use multiple assertions, which conflicts with the “one assertion per test” directive. Consider splitting for clearer failures.
- [repo] `todos/state-machine-refinement/state.json` - This appears to be a worktree-local artifact; consider removing it from the main repo if it isn’t intentionally tracked.

## Strengths

- Dependency gating is centralized in `resolve_slug()` and consistently applied by `next_work()`.
- Clear user-facing errors for “no ready items” vs. “deps unsatisfied.”
- Roadmap state transitions are automated as required.

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Remove the unused `Db` import in `tests/unit/test_mcp_set_dependencies.py`.
2. Add/relocate integration tests into `tests/integration/` to satisfy the required coverage.
