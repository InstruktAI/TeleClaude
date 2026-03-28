# Demo: atomic-layout-messages

## Validation

```bash
# Verify all xfail specs now pass (markers removed during build)
python -m pytest tests/unit/cli/tui/test_pane_bridge.py::test_on_sticky_and_preview_changed_applies_both_state_and_marks_layout_dirty_once -v
python -m pytest tests/unit/cli/tui/test_app_actions.py::test_app_on_sticky_and_preview_changed_delegates_to_bridge_updates_banner_and_schedules_sky_width -v
python -m pytest tests/unit/cli/tui/views/test_sessions_actions.py::test_toggle_sticky_state_mutation_does_not_call_post_message -v
python -m pytest tests/unit/cli/tui/views/test_sessions_actions.py::test_action_toggle_preview_toggle_sticky_with_clear_preview_posts_single_atomic_message -v
python -m pytest tests/unit/cli/tui/views/test_sessions_actions.py::test_action_toggle_sticky_sessions_scope_off_posts_single_atomic_message -v
python -m pytest tests/unit/cli/tui/views/test_sessions.py::test_on_session_row_pressed_double_click_sticky_posts_single_atomic_message -v
```

```bash
# Verify backward compatibility — existing StickyChanged/PreviewChanged tests still pass
python -m pytest tests/unit/cli/tui/test_pane_bridge.py -v
python -m pytest tests/unit/cli/tui/views/test_sessions_actions.py -v
python -m pytest tests/unit/cli/tui/views/test_sessions.py -v
python -m pytest tests/unit/cli/tui/test_app_actions.py -v
```

```bash
# Verify no paired StickyChanged+PreviewChanged posts remain in dual-change paths
grep -n "StickyChanged\|PreviewChanged" teleclaude/cli/tui/views/sessions_actions.py teleclaude/cli/tui/views/sessions.py
# Expected: StickyChanged only in _toggle_sticky (single-concern wrapper)
# Expected: PreviewChanged only in single-preview paths (action_toggle_preview PREVIEW, action_focus_pane, single-click)
# No dual posts in any TOGGLE_STICKY+clear_preview, scope-off, or double-click path
```

## Guided Presentation

### Step 1 — The new message

Open `teleclaude/cli/tui/messages.py` and find `StickyAndPreviewChanged`. This is
the atomic carrier — it holds `sticky_session_ids`, `preview_session_id`, and
`request_focus` in a single Textual message. It sits alongside the existing
`StickyChanged` and `PreviewChanged` messages, which remain for single-concern use.

### Step 2 — The pure mutation helper

Open `teleclaude/cli/tui/views/sessions_actions.py` and find `_toggle_sticky_state`.
This is the extracted mutation logic from `_toggle_sticky` — it updates
`_sticky_session_ids` and `SessionRow.is_sticky` flags without posting any message.
Compare it to `_toggle_sticky` directly below, which is now a thin wrapper that
calls `_toggle_sticky_state` then posts `StickyChanged`.

### Step 3 — Dual-change call sites

In the same file, find `action_toggle_preview`. In the TOGGLE_STICKY branch,
the `clear_preview` path now calls `_toggle_sticky_state` then posts a single
`StickyAndPreviewChanged`. The non-clear_preview path still calls `_toggle_sticky`.

Find `action_toggle_sticky_sessions`. The scope-off path (removing stickies while
preview is active) now posts a single `StickyAndPreviewChanged` instead of separate
`PreviewChanged` + `StickyChanged`.

Open `teleclaude/cli/tui/views/sessions.py` and find the double-click block in
`on_session_row_pressed`. Same pattern: `_toggle_sticky_state` + atomic message
when sticky was removed and preview is being set.

### Step 4 — Bridge and app handlers

Open `teleclaude/cli/tui/pane_bridge.py` and find `on_sticky_and_preview_changed`.
It sets both `_sticky_session_ids` and `_preview_session_id` before calling
`_mark_layout_dirty` once. No intermediate flush is possible.

Open `teleclaude/cli/tui/app.py` and find `on_sticky_and_preview_changed`. It
forwards to the bridge, updates banner compactness, and schedules sky width
invalidation — mirroring the existing `on_sticky_changed` handler.

### Step 5 — Verify no regressions

Run the full TUI test suite. All existing tests pass. The 6 xfail specs now pass
with their markers removed. No paired `StickyChanged`/`PreviewChanged` posts
remain in any dual-change handler.
