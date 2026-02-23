# Review Findings: fix-todos-watcher-not-notifying-websocket

## Verdict: APPROVE

## Critical

(none)

## Important

(none)

## Suggestions

- **Fingerprint missing 3 display-relevant fields** (`preparation.py:84-101`): `_todo_fingerprint` omits `description`, `has_requirements`, and `has_impl_plan`, which are all used in `_rebuild()` (lines 150-152). If a todo's description text or requirements/plan existence changes without affecting `files`, the view stays stale. Pre-existing gap (the old slug-set comparison had the same blind spot). Low priority — these fields rarely change in isolation, and the reported bug was about state.yaml-derived fields which are all covered.

## Paradigm-Fit Assessment

1. **Data flow**: The fix stays within the existing `update_data()` → `_rebuild()` pipeline. It replaces a coarse change detector (slug set comparison) with a fine-grained one (data fingerprint). No bypass of the data layer. The `@staticmethod` fingerprint method is pure computation with no side effects.
2. **Component reuse**: No duplication. The fingerprint fields align with the `TodoItem` constructor parameters in `_rebuild()`. No copy-paste of existing logic.
3. **Pattern consistency**: Using a static method for pure computation follows good practice. Tuple comparison for change detection is a standard pattern. The method signature accepts the same `list[ProjectWithTodosInfo]` type used throughout the view.

## Bug Fix Verification

- **Symptom addressed**: state.yaml edits (DOR score, build status, review status, phase transitions, deferrals, findings count) now trigger `_rebuild()` because all these fields are in the fingerprint.
- **Root cause analysis sound**: The old code compared `{t.slug for ...}` — only slug identity, not data content. Any change that preserves the slug set was invisible. The bug.md correctly identifies this.
- **Fix minimal and targeted**: 1 new static method (18 lines), 4 changed lines in `update_data()`. No other files touched beyond bug.md and state.yaml documentation updates.
- **Investigation and documentation complete**: bug.md has full Investigation, Root Cause, and Fix Applied sections with correct TUI terminology.

## Requirements Verification (via bug.md)

1. **state.yaml changes refresh the view**: Verified. All state.yaml-derived fields (`status`, `dor_score`, `build_status`, `review_status`, `deferrals_status`, `findings_count`) are in the fingerprint. Changes to any of these trigger `_rebuild()`.
2. **File list changes refresh the view**: Verified. `files` and `after` are in the fingerprint via `,`.join().
3. **Group changes refresh the view**: Verified. `group` is in the fingerprint.
4. **No unnecessary rebuilds**: Verified. When data is identical, `old_fp == new_fp` and `_rebuild()` is skipped, preserving the optimization.

## Test Coverage Note

All existing PreparationView test files (`test_tui_preparation_view.py`, `test_preparation_view.py`) are marked `pytest.mark.skip` — they reference pre-Textual curses APIs that no longer exist. The new `_todo_fingerprint` method has no unit test. This is consistent with the current test status for this module and not a regression introduced by this change.

## Manual Verification Evidence

The change is in view change detection logic. Manual verification would require:

1. Running the TUI, editing a todo's state.yaml, and observing the view refresh.
2. This cannot be automated in the review environment (requires live TUI + filesystem watcher + WebSocket chain).
3. The logic is structurally correct: the fingerprint includes all state.yaml-derived fields, and tuple inequality triggers rebuild.
