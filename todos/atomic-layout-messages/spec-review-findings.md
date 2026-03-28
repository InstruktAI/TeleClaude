# Test Spec Review Findings — atomic-layout-messages

**Verdict:** needs_work
**Reviewed at:** 2026-03-28T14:00:00Z
**Unresolved findings:** 2

---

## Summary

5 xfail specs were delivered covering R1, R2, R3 (two call sites), R4, and R5
(acknowledged via comment). The specs use the correct `@pytest.mark.xfail(strict=True)`
convention and follow existing test patterns. Most requirements have adequate
coverage. Two findings require remediation before approval.

---

## Critical Findings

### F1 — R3: double-click call site uncovered

**Severity:** Critical
**Requirement:** R3 — All dual-change call sites updated.

R3 explicitly lists three call sites that must be converted to the atomic
notification:

1. `action_toggle_preview` (TOGGLE_STICKY + `clear_preview` path) — **COVERED**
2. Sessions double-click handler — **NOT COVERED**
3. `action_toggle_sticky_sessions` (scope-off batch path) — **COVERED**

The double-click handler in `sessions.py` (lines 604–615) calls
`_toggle_sticky(session_id)` — which posts `StickyChanged` — and then, when
`was_sticky` is True, posts `PreviewChanged(session_id, request_focus=False)`.
This is the same dual-message pattern as the keyboard handler. An implementation
that converts call sites 1 and 3 but leaves the click handler unconverted would
pass all current specs while violating R3.

**Required spec:** A test in `tests/unit/cli/tui/views/test_sessions.py`
(the corresponding test file for `sessions.py`) that stubs the click handler
path with `was_sticky=True` (double-click on a sticky session), captures
posted messages, and asserts exactly one `StickyAndPreviewChanged` is emitted —
not a `StickyChanged` + `PreviewChanged` pair.

---

## Important Findings

### F2 — R2 spec does not verify SessionRow.is_sticky flag updates

**Severity:** Important
**Requirement:** R2 — Pure state mutation for toggle-sticky.

The R2 spec (`test_toggle_sticky_state_mutation_does_not_call_post_message`) uses
`view._nav_items = []`. The current `_toggle_sticky` implementation iterates
`_nav_items` to update `widget.is_sticky` for each `SessionRow`. With an empty
list, this loop never executes.

R2 explicitly states the pure mutation must update `SessionRow.is_sticky` flags.
An extracted helper that only modifies `_sticky_session_ids` but skips row-flag
updates would pass the current test. The test asserts the right primary contract
(no `post_message`) but misses the secondary mutation completeness requirement.

**Required improvement:** Add at least one `SessionRow`-like stub to `_nav_items`
(a `SimpleNamespace` with `session_id` and `is_sticky` attributes) and assert
that `widget.is_sticky` reflects the toggled state after calling
`_toggle_sticky_state`.

---

## Resolved Findings (from prior review)

| Finding                              | Prior status | Current status                                                                                                       |
| ------------------------------------ | ------------ | -------------------------------------------------------------------------------------------------------------------- |
| F1-prev: R1 uncovered                | Critical     | RESOLVED — `test_on_sticky_and_preview_changed_applies_both_state_and_marks_layout_dirty_once` added                 |
| F2-prev: R2 uncovered                | Critical     | PARTIALLY RESOLVED — test exists, gap in row-flag coverage (→ new F2)                                                |
| F3-prev: R3 all call sites uncovered | Critical     | PARTIALLY RESOLVED — 2 of 3 sites covered (→ new F1)                                                                 |
| F4-prev: R4 uncovered                | Critical     | RESOLVED — `test_app_on_sticky_and_preview_changed_delegates_to_bridge_updates_banner_and_schedules_sky_width` added |
| F5-prev: R5 unacknowledged           | Important    | RESOLVED — explicit comment added in `test_pane_bridge.py` naming the two covering tests                             |

---

## Spec Quality Assessment

### R1 — `test_on_sticky_and_preview_changed_applies_both_state_and_marks_layout_dirty_once`

**File:** `tests/unit/cli/tui/test_pane_bridge.py`
**Quality:** GOOD

- `mark_layout_dirty.assert_called_once()` correctly proves atomic dispatch.
- Assertions on both `_sticky_session_ids` and `_preview_session_id` verify
  both fields are applied.
- Would catch: implementation that calls `_mark_layout_dirty` twice (once per
  field), or that updates one field but not the other.

### R2 — `test_toggle_sticky_state_mutation_does_not_call_post_message`

**File:** `tests/unit/cli/tui/views/test_sessions_actions.py`
**Quality:** ACCEPTABLE with gap (see F2)

- `post_message.assert_not_called()` is the right primary assertion.
- `assert "session-1" in view._sticky_session_ids` confirms state mutation.
- Gap: does not verify `SessionRow.is_sticky` flag update (see F2).

### R3 call site 1 — `test_action_toggle_preview_toggle_sticky_with_clear_preview_posts_single_atomic_message`

**File:** `tests/unit/cli/tui/views/test_sessions_actions.py`
**Quality:** GOOD

- Intercepts all `post_message` calls via lambda.
- Asserts absence of `StickyChanged` and `PreviewChanged` by type name.
- Asserts exactly one `StickyAndPreviewChanged` with correct payload:
  `preview_session_id == "session-1"` and `"session-1" not in atomic.sticky_session_ids`.
- Would catch: implementation that posts the old pair instead of the atomic message.

### R3 call site 2 — `test_action_toggle_sticky_sessions_scope_off_posts_single_atomic_message`

**File:** `tests/unit/cli/tui/views/test_sessions_actions.py`
**Quality:** GOOD

- Tests the batch-toggle scope-off path with preview active.
- Asserts exact payload: `preview_session_id is None` and `sticky_session_ids == []`.
- Strong behavioral assertions on the clearing semantics.
- Would catch: implementation that posts `PreviewChanged(None)` + `StickyChanged([])` pair.

### R3 call site 3 (double-click) — MISSING

**File:** `tests/unit/cli/tui/views/test_sessions.py`
**Quality:** NOT PRESENT — see F1.

### R4 — `test_app_on_sticky_and_preview_changed_delegates_to_bridge_updates_banner_and_schedules_sky_width`

**File:** `tests/unit/cli/tui/test_app_actions.py`
**Quality:** GOOD

- Verifies all three delegation steps: bridge handler, banner compactness, sky-width.
- `update_banner.assert_called_once_with(2)` uses the actual list length, not a
  hardcoded count — would catch a constant-folded wrong implementation.
- Pattern mirrors existing `on_sticky_changed` tests.

### R5 — acknowledged via comment

**File:** `tests/unit/cli/tui/test_pane_bridge.py` (lines 230–235)
**Quality:** ACCEPTABLE

- Comment names both covering tests explicitly.
- No new xfail spec required for backward-compatibility guard.
- The existing tests `test_set_preview_schedules_layout_with_snapshot_state` and
  `test_on_data_refreshed_updates_cached_state_and_seeds_reload_when_needed`
  remain active (non-xfail) and will continue to pass after implementation.
