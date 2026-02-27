# Review Findings: fix-roadmap-order-in-todos-view

## Summary

Bug fix removes two explicit `sorted()` calls in `preparation.py` that discarded `trusted_dirs` insertion order from config. Replaced with first-seen tracking for computers and passthrough iteration for projects. Test updated to assert insertion order instead of alphabetical.

## Paradigm-Fit Assessment

1. **Data flow**: Fix aligns the preparation view with the established data flow (config -> API -> cache -> view). The upstream chain already preserved `trusted_dirs` order; only the view layer broke it. The sessions view (`tree.py:build_tree`) already iterated in input order — this fix brings consistency. **Pass.**
2. **Component reuse**: No new components or duplication introduced. The `computer_order` list is a minimal inline pattern. **Pass.**
3. **Pattern consistency**: The sessions view uses list-order iteration for computers (`tree.py:128`) and filter-order for projects (`tree.py:155`). The preparation view now matches this pattern. **Pass.**

## Critical

(none)

## Important

1. **bug.md Investigation/Root Cause/Fix Applied sections are empty** — `todos/fix-roadmap-order-in-todos-view/bug.md` still has placeholder `<!-- Fix worker fills this -->` comments in Investigation, Root Cause, and Fix Applied sections. These should be filled with the actual findings before delivery. The prior review incorrectly claimed these were filled. Severity: Important (documentation completeness per DoD).

## Suggestions

(none)

## Why No Issues (code)

1. **Paradigm-fit verified**: Traced the data chain from `config.computer.trusted_dirs` through `build_tree` in `tree.py`. The sessions view iterates `all_computers` in input order (`tree.py:94,128`) and projects in input order (`tree.py:155`). The preparation view now matches: `computer_order` tracks first-seen insertion order, projects iterate as-provided. Consistent.
2. **Requirements validated**: `bug.md` symptom is "preparation view shows incorrect order; `trusted_dirs` order should be preserved." The fix removes both `sorted()` calls (computers at original line 201, projects at original line 223) that caused the reordering.
3. **Copy-paste duplication checked**: No code was duplicated. The `computer_order` pattern is 4 lines of straightforward first-seen tracking.
4. **Test validates the fix**: `test_preparation_tree_groups_by_computer` feeds `[beta, alpha]` and asserts `["beta", "alpha"]` output order, proving insertion order is preserved and alphabetical sorting is gone.
5. **All 22 TUI key contract tests pass** with no regressions.

## Manual Verification

Not possible in review environment (no TUI rendering). The test provides structural verification that `_nav_items` computer headers appear in insertion order rather than alphabetical order.

Verdict: REQUEST CHANGES
