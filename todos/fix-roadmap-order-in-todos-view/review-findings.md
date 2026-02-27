# Review Findings: fix-roadmap-order-in-todos-view

Review round: 2

## Summary

Bug fix removes two `sorted()` calls in `preparation.py` that discarded `trusted_dirs` insertion order from config. Replaced with first-seen tracking (`computer_order` list) for computers and passthrough iteration for projects. Test updated to assert insertion order instead of alphabetical. Code is correct and paradigm-aligned. Previous round's finding (empty bug.md sections) remains unaddressed.

## Paradigm-Fit Assessment

1. **Data flow**: Fix aligns the preparation view with the established data flow (config → trusted_dirs → API → cache → view). The sessions view (`tree.py:94,128`) already iterates `all_computers` in input order — this fix brings the preparation view into consistency. **Pass.**
2. **Component reuse**: No new components or duplication. The `computer_order` list is a 4-line inline pattern — no abstraction warranted. **Pass.**
3. **Pattern consistency**: Sessions view uses `all_computers = list(computers)` then `for computer in all_computers` (tree.py:94,128). Preparation view now uses the same pattern via `computer_order`. Projects iterate as-provided in both views. **Pass.**

## Critical

(none)

## Important

1. **bug.md Investigation/Root Cause/Fix Applied sections still empty** — `todos/fix-roadmap-order-in-todos-view/bug.md` still contains only `<!-- Fix worker fills this -->` placeholder comments in all three sections. This was the sole finding in round 1 and remains unaddressed. Per DoD documentation requirements and the review procedure ("Verify: Investigation and documentation sections are complete"), these must be filled before delivery.

## Suggestions

(none)

## Manual Verification

Not possible in review environment (no TUI rendering). The test (`test_preparation_tree_groups_by_computer`) provides structural verification: feeds `[beta, alpha]` input order and asserts `["beta", "alpha"]` output order, proving insertion order is preserved.

Verdict: REQUEST CHANGES
