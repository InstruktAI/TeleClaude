# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ✅ Implemented | Ready state supported in roadmap parsing and transitions. |
| R3: State machine owns checkbox transitions | ✅ Implemented | `next_prepare()` marks `[ ] → [.]`; `next_work()` claims `[.] → [>]`. |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ✅ Implemented | Tool validates slug format, existence, self-reference, and cycles. |
| R6: `resolve_slug()` ready-only + dependency gating | ✅ Implemented | Ready-only selection gates on dependency satisfaction. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ✅ Implemented | Unit + integration coverage added. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/core/next_machine.py:933` - Error guidance uses a literal `{slug}` instead of interpolating the requested slug. This produces an invalid command string and can mislead the orchestrator to call `teleclaude__next_prepare` with `{slug}`.
  - Suggested fix: use an f-string: `next_call=f"Call teleclaude__next_prepare(slug='{slug}') to prepare it first."`

## Suggestions (nice to have)

- [tests] `tests/unit/test_next_machine_state_deps.py:35` (and similar) - Multiple assertions per test conflict with the testing directives. Consider splitting into single-assertion tests for clearer failures and better alignment with repo standards.

## Strengths

- Dependency gating is centralized and reused by `next_work()` and `resolve_slug()`.
- State transitions are automated and guarded against downgrades.
- Error paths differentiate “no ready items” vs. “dependencies unsatisfied,” which improves operator guidance.

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Interpolate `slug` in the `ITEM_NOT_READY` next_call guidance.
