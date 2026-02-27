# Implementation Plan: fix-sticky-removal-layout-issues

## Overview

The fix is a small, targeted state transition change. When TOGGLE_STICKY removes a sticky session, instead of just clearing stale preview, set the removed session as the active preview. This happens in two places: the reducer (state.py) for the state model, and the sessions view (sessions.py) for the message flow to the pane bridge.

## Phase 1: Core Changes

### Task 1.1: Reducer — un-sticky sets preview instead of clearing

**File(s):** `teleclaude/cli/tui/state.py`

- [ ] In `reduce_state`, TOGGLE_STICKY removal branch: change from clearing preview to setting `preview = PreviewState(session_id)` for the removed session

Current code (partial fix already on main):

```python
if existing_idx is not None:
    state.sessions.sticky_sessions.pop(existing_idx)
    if state.sessions.preview and state.sessions.preview.session_id == session_id:
        state.sessions.preview = None
```

Target:

```python
if existing_idx is not None:
    state.sessions.sticky_sessions.pop(existing_idx)
    state.sessions.preview = PreviewState(session_id)
```

### Task 1.2: Sessions view (interaction path) — set preview on un-sticky

**File(s):** `teleclaude/cli/tui/views/sessions.py`

The keyboard-based interaction path (lines ~625-631) uses `decision.clear_preview` which is `True` when un-stickying (`interaction.py:83` sets `clear_preview=is_sticky`). Currently this branch clears the preview — it must instead set it to the un-stickied session:

- [ ] In the `TOGGLE_STICKY` branch, replace the `decision.clear_preview` body: change `self.preview_session_id = None` to `self.preview_session_id = session_id`, and change `PreviewChanged(None, ...)` to `PreviewChanged(session_id, request_focus=False)`

### Task 1.2b: Sessions view (click path) — set preview on un-sticky

**File(s):** `teleclaude/cli/tui/views/sessions.py`

The click-based double-press handler (lines ~525-530) calls `_toggle_sticky(session_id)` and returns without touching preview. This path must also set preview when un-stickying:

- [ ] After `_toggle_sticky(session_id)`, check `if session_id not in self._sticky_session_ids:` — if true (was removed), set `self.preview_session_id = session_id` and post `PreviewChanged(session_id, request_focus=False)`

### Task 1.3: Verify pane bridge ordering

**File(s):** `teleclaude/cli/tui/pane_bridge.py` (read-only verification)

- [ ] Confirm that `on_sticky_changed` followed by `on_preview_changed` results in correct state: `_sticky_session_ids` shortened, `_preview_session_id` set to the removed session
- [ ] Confirm PaneWriter coalescing produces the correct final snapshot

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Update `test_remove_sticky_clears_preview_for_same_session` — preview should be SET to the removed session, not cleared
- [ ] Update `test_remove_sticky_preserves_preview_for_different_session` — removing sticky-A while preview-B is active must now set preview to A (not preserve B)
- [ ] Add test: un-sticky with no prior preview → preview is set to removed session
- [ ] Run `make test-unit`

### Task 2.2: Manual verification

- [ ] Reload TUI with SIGUSR2
- [ ] Test: make 2 sessions sticky, un-sticky one → it becomes preview, layout doesn't rebuild
- [ ] Test: have a preview active, un-sticky a different session → preview switches, layout stable
- [ ] Test: un-sticky last sticky with no preview → session becomes preview, layout stable

### Task 2.3: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
