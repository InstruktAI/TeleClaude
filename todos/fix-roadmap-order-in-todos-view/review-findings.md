# Review Findings: fix-roadmap-order-in-todos-view

## Summary

Bug fix removes two explicit `sorted()` calls in `preparation.py` that discarded `trusted_dirs` insertion order from config. Replaced with first-seen tracking for computers and passthrough iteration for projects. Test updated to assert insertion order instead of alphabetical.

## Paradigm-Fit Assessment

1. **Data flow**: Fix aligns the preparation view with the established data flow (config → API → cache → view). The upstream chain already preserved `trusted_dirs` order; only the view layer broke it. The sessions view (`tree.py:build_tree`) already iterated in input order — this fix brings consistency. **Pass.**
2. **Component reuse**: No new components or duplication introduced. The `computer_order` list is a minimal inline pattern. **Pass.**
3. **Pattern consistency**: The sessions view uses list-order iteration for computers (line 128) and filter-order for projects (line 155). The preparation view now matches this pattern. **Pass.**

## Critical

(none)

## Important

(none)

## Suggestions

(none)

## Why No Issues

1. **Paradigm-fit verified**: Traced the data chain from `config.computer.trusted_dirs` through `command_handlers.list_projects()` → cache → API → client → `_projects_with_todos`. The upstream chain preserves insertion order; the fix removes the two callsites that broke it. Sessions view already follows this pattern (`tree.py:128`, `tree.py:155`).
2. **Requirements validated**: `bug.md` symptom is "preparation view shows incorrect order; `trusted_dirs` order should be preserved." The fix removes both `sorted()` calls (computers at line 201, projects at line 223) that caused the reordering. The `computer_order` list correctly tracks first-seen insertion order.
3. **Copy-paste duplication checked**: No code was duplicated. The `computer_order` pattern is 4 lines of straightforward first-seen tracking — no abstraction warranted.
4. **Test validates the fix**: `test_preparation_tree_groups_by_computer` feeds `[beta, alpha]` and asserts `["beta", "alpha"]` output order, proving insertion order is preserved and alphabetical sorting is gone.
5. **Bug.md completeness**: Investigation, Root Cause, and Fix Applied sections are all filled with accurate, specific detail referencing line numbers and code paths.
6. **All 22 TUI key contract tests pass** with no regressions.

## Manual Verification

Not possible in review environment (no TUI rendering). The test provides structural verification that `_nav_items` computer headers appear in insertion order rather than alphabetical order.

Verdict: APPROVE
