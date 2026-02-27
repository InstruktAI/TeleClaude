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

### Task 1.2: Sessions view — post PreviewChanged with new session after un-sticky

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [ ] In the TOGGLE_STICKY handler, after `_toggle_sticky(session_id)`, set `self.preview_session_id = session_id` and post `PreviewChanged(session_id, request_focus=False)` when the session was removed (not added)
- [ ] Ensure `decision.clear_preview` logic still works correctly (it fires when the un-stickied session was also previewed — now the preview is being set explicitly, so this branch may need adjustment)

### Task 1.3: Verify pane bridge ordering

**File(s):** `teleclaude/cli/tui/pane_bridge.py` (read-only verification)

- [ ] Confirm that `on_sticky_changed` followed by `on_preview_changed` results in correct state: `_sticky_session_ids` shortened, `_preview_session_id` set to the removed session
- [ ] Confirm PaneWriter coalescing produces the correct final snapshot

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Update `test_remove_sticky_clears_preview_for_same_session` in `tests/unit/test_tui_state.py` — now the preview should be SET to the removed session, not cleared
- [ ] Add test: un-sticky with no prior preview → preview is set to removed session
- [ ] Add test: un-sticky with different session previewed → preview changes to removed session
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
