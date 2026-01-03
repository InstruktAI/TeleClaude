# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ✅ Implemented | Ready state supported in roadmap parsing and transitions. |
| R3: State machine owns checkbox transitions | ✅ Implemented | `next_prepare()`/`next_work()` update roadmap via `update_roadmap_state()`. |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ✅ Implemented | Tool validates slug format, existence, self-reference, and cycles. |
| R6: `resolve_slug()` ready-only + dependency gating | ✅ Implemented | Ready-only selection gates on dependency satisfaction. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ✅ Implemented | Unit + integration coverage added for workflow/deps. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/core/next_machine.py:877` - Explicit `next_work(slug=...)` bypasses ready-state gating and can start work on `[ ]` items, leaving roadmap state unchanged (no `[.]` → `[>]` transition) and violating the “only [.] items” requirement.
  - Suggested fix: when `slug` is provided, read the roadmap state for that slug and require `[.]` or `[>]` (error with `NOT_PREPARED`/`ITEM_NOT_READY` for `[ ]`), or normalize via `resolve_slug` before proceeding.

## Suggestions (nice to have)

- [tests] `tests/integration/test_state_machine_workflow.py:140` - The assertion `assert "ERROR:" not in result or "DEPS_UNSATISFIED" not in result` is too weak and can pass on unrelated errors.
  - Reason: It allows other error states to slip through; prefer asserting an expected tool call or explicitly ensuring no error prefix.

## Strengths

- Dependency gating is centralized and reused by `next_work()`.
- Clear error messaging distinguishes “no ready items” vs. “dependencies unsatisfied.”
- Roadmap state transitions are automated as required.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| **Important:** Explicit `next_work(slug=...)` bypasses ready-state gating | Added roadmap state check when explicit slug provided. Now rejects `[ ]` (pending) items with `ITEM_NOT_READY` error. Only allows `[.]` (ready) or `[>]` (in-progress) items. Added test coverage. | a5be7ea |
| **Suggestion:** Weak test assertion in dependency blocking test | Changed from compound OR assertion to two explicit assertions to catch all error conditions. | 3cb667d |

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Enforce ready-state gating for explicit `next_work(slug=...)` so `[ ]` items cannot be claimed without preparation.
