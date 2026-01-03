# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ✅ Implemented | Ready state supported in roadmap parsing and transitions. |
| R3: State machine owns checkbox transitions | ⚠️ Partial | `next_prepare()` can downgrade `[>]` to `[.]` (see Important issue). |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ✅ Implemented | Tool validates slug format, existence, self-reference, and cycles. |
| R6: `resolve_slug()` ready-only + dependency gating | ✅ Implemented | Ready-only selection gates on dependency satisfaction. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git-commit side effect. |
| Tests per requirements | ✅ Implemented | Unit + integration coverage added. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/core/next_machine.py:854` - `next_prepare()` unconditionally calls `update_roadmap_state(..., ".")` once requirements + implementation plan exist. If the item is already `[>]` (in progress), this downgrades it back to `[.]`, allowing other workers to claim it and breaking the state model.
  - Suggested fix: Read the current state from `todos/roadmap.md` and only transition `[ ] -> [.]` (or no-op if already `[.]`). Avoid changing `[>]` or `[x]`.

## Suggestions (nice to have)

- [tests] `tests/unit/test_next_machine_state_deps.py:35` - Tests use multiple assertions per test, which conflicts with the repo’s testing directive (“one assertion per test”).
  - Reason: Increases failure ambiguity; splitting assertions into focused tests would align with project standards.

## Strengths

- Dependency gating is centralized and reused by `next_work()`.
- Error messaging distinguishes “no ready items” vs. “dependencies unsatisfied.”
- Roadmap state transitions are automated as required.

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Prevent `next_prepare()` from downgrading `[>]` items to `[.]`.
