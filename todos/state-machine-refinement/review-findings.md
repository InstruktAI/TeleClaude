# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ✅ Implemented | Ready state supported in code; roadmap legend already includes `[.]`. |
| R3: State machine owns checkbox transitions | ✅ Implemented | `next_prepare()`/`next_work()` call `update_roadmap_state()`. |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ✅ Implemented | Tool validates slug format, existence, self-reference, and cycles. |
| R6: `resolve_slug()` ready-only + dependency gating | ⚠️ Partial | Dependency gating lives in `next_work()`; `resolve_slug()` ready-only mode does not enforce deps. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ⚠️ Partial | Some unit tests added, but missing ready-only `resolve_slug` tests, set-dependencies validation tests, and the integration workflow test. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/core/next_machine.py:520` - `check_dependencies_satisfied()` treats a dependency that is missing from `roadmap.md` as **unsatisfied** unless a `done/*-slug` directory exists. This violates the requirement that “not present in roadmap” implies completion, and will block valid work items after roadmap cleanup.
  - Suggested fix: if `dep` not in `roadmap_items`, treat it as satisfied without requiring a `done/` entry.
- [tests] `tests/unit/test_mcp_set_dependencies.py:1` - Empty test file with unused imports; will fail linting and does not validate the MCP tool behavior.
  - Suggested fix: remove the file or add the required tests for `teleclaude__set_dependencies()` validation rules.
- [tests] `tests/unit/test_next_machine_state_deps.py:1` - Missing required tests for `resolve_slug(..., ready_only=True)` and full workflow integration (R6 + integration requirements).
  - Suggested fix: add focused unit tests for ready-only slug resolution and a lightweight integration test that exercises `[ ] → [.] → [>] → archived` plus dependency gating.

## Suggestions (nice to have)

- [simplify] `teleclaude/core/next_machine.py:287` - Consider moving dependency gating into `resolve_slug(..., ready_only=True)` so selection logic isn’t split across helpers and `next_work()`.
- [tests] `tests/unit/test_next_machine_state_deps.py:1` - Several tests use multiple assertions; consider splitting for single-assertion clarity in line with testing directives.
- [docs] `todos/state-machine-refinement/state.json:1` - Verify this artifact belongs in the main repo; state is typically worktree-local (`trees/{slug}/todos/{slug}/state.json`).

## Strengths

- Clear, actionable error messages for “no ready items” and “dependencies unsatisfied” scenarios.
- Dependency helpers are cleanly factored and easy to reuse.
- Roadmap state transitions are centralized and consistently invoked.

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Align dependency satisfaction with the requirement: missing roadmap items must count as completed.
2. Add/repair tests: eliminate empty `test_mcp_set_dependencies.py` and cover ready-only slug resolution + integration flow.
