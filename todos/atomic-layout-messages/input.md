# atomic-layout-messages — Input

## Problem
TOGGLE_STICKY posts two separate Textual messages (StickyChanged + PreviewChanged) from one user action. The bridge's call_later flush fires between them due to asyncio pump interleaving, producing two layout renders — the first with stale state.

## Root Cause
call_later on the bridge posts to the bridge's message pump. The bridge's pump interleaves with SessionsView's pump on the asyncio event loop. StickyChanged and PreviewChanged are processed in separate pump iterations with yields between them.

## Fix: Single message for atomic layout state
1. New message LayoutStateChanged(sticky_session_ids, preview_session_id, request_focus) in messages.py
2. Extract _toggle_sticky_state (pure mutation, no message posting) from _toggle_sticky in sessions_actions.py
3. TOGGLE_STICKY handler calls _toggle_sticky_state + posts single LayoutStateChanged
4. Bridge handler on_layout_state_changed sets both sticky and preview atomically before marking dirty
5. App forwarding handler mirrors existing pattern (banner compactness + sky width)
6. Tests for bridge handler and single-message assertion

Existing StickyChanged/PreviewChanged stay for individual use cases. ~6 files, ~40 lines.
