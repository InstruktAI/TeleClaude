# Implementation Plan: atomic-layout-messages

## Overview

A single user action (TOGGLE_STICKY with clear_preview, double-click on sticky,
batch-toggle-off) posts separate `StickyChanged` + `PreviewChanged` messages. The
bridge's `call_later` flush can fire between them, producing a layout render with
stale state. The fix introduces a `StickyAndPreviewChanged` message that carries
both values atomically. All dual-change call sites switch to this message; the
bridge and app gain a handler that applies both fields before marking layout dirty.

Existing `StickyChanged` and `PreviewChanged` messages remain untouched for
single-concern call sites.

~5 files, ~60 lines of change. One coherent behavior — one session.

## Task 1: Add `StickyAndPreviewChanged` message

**File:** `teleclaude/cli/tui/messages.py`

**What:** Add a new `StickyAndPreviewChanged(Message)` class in the session
interaction messages section, after the existing `StickyChanged` class. The message
carries `sticky_session_ids: list[str]`, `preview_session_id: str | None`, and
`request_focus: bool` (defaulting to `False`).

**Why:** The bridge needs a single message to atomically set both sticky and
preview state before a single `_mark_layout_dirty` call. Two separate messages
get interleaved by asyncio pump scheduling. The `request_focus` field preserves
the existing preview semantics (Space = no focus, click = focus).

**Verification:** Confirm that `StickyAndPreviewChanged` can be imported from
`teleclaude.cli.tui.messages`. (R1 and R3 xfail markers are removed only after
their respective handler and call-site tasks complete — not at this step.)

- [x] Define `StickyAndPreviewChanged` with constructor taking
      `sticky_session_ids`, `preview_session_id`, and `request_focus` kwargs
- [x] Add to the import block where `StickyChanged` is defined

## Task 2: Extract `_toggle_sticky_state` pure mutation helper

**File:** `teleclaude/cli/tui/views/sessions_actions.py`

**What:** Extract the mutation logic from `_toggle_sticky` into a new
`_toggle_sticky_state(self, session_id: str) -> None` method. This method:

1. Adds/removes `session_id` from `self._sticky_session_ids` (with MAX_STICKY guard)
2. Updates `SessionRow.is_sticky` flags on `self._nav_items`

It does NOT call `post_message` or `_notify_state_changed`. The existing
`_toggle_sticky` becomes a thin wrapper: calls `_toggle_sticky_state` then posts
`StickyChanged` and calls `_notify_state_changed` — preserving behavior for
single-concern callers (non-clear_preview TOGGLE_STICKY, single-toggle paths).

**Why:** Dual-change call sites need to mutate sticky state without triggering a
message, so they can compose the combined state into a single
`StickyAndPreviewChanged` post. Extracting the pure mutation enables this without
duplicating logic.

**Verification:** Remove xfail marker on R2 spec
(`test_toggle_sticky_state_mutation_does_not_call_post_message`) — calling
`_toggle_sticky_state` must not trigger `post_message` and must update
`_sticky_session_ids` and `SessionRow.is_sticky`.

- [x] Add `_toggle_sticky_state` with the mutation-only logic
- [x] Refactor `_toggle_sticky` to call `_toggle_sticky_state` then post/notify
- [x] Verify existing `_toggle_sticky` callers (non-clear_preview paths) are
      unchanged in behavior

## Task 3: Update `action_toggle_preview` TOGGLE_STICKY+clear_preview path

**File:** `teleclaude/cli/tui/views/sessions_actions.py`

**What:** In the `TOGGLE_STICKY` branch of `action_toggle_preview`, when
`decision.clear_preview` is `True`: replace the current `_toggle_sticky` +
`PreviewChanged` post with:

1. Call `_toggle_sticky_state(session_id)` (pure mutation)
2. Set `self.preview_session_id = session_id`
3. Post `StickyAndPreviewChanged(sticky_session_ids=self._sticky_session_ids.copy(), preview_session_id=session_id, request_focus=False)`
4. Call `self._notify_state_changed()`

The `else` branch (TOGGLE_STICKY without clear_preview) still calls `_toggle_sticky`
unchanged.

**Why:** This is the primary race site — double-space on a sticky session. The
current code posts `StickyChanged` (from `_toggle_sticky`) followed by
`PreviewChanged`, allowing a flush between them. The atomic message eliminates
the interleaving window.

**Verification:** Remove xfail marker on R3 spec
(`test_action_toggle_preview_toggle_sticky_with_clear_preview_posts_single_atomic_message`).

- [x] Import `StickyAndPreviewChanged` in the import block
- [x] Replace the clear_preview branch with the atomic pattern
- [x] Keep the non-clear_preview branch calling `_toggle_sticky` as-is
- [x] Preserve `self._interaction.mark_double_press_guard(session_id, now)` — it is called unconditionally after the if/else block (outside both branches) and must remain there in the refactored version

## Task 4: Update `action_toggle_sticky_sessions` scope-off path

**File:** `teleclaude/cli/tui/views/sessions_actions.py`

**What:** `action_toggle_sticky_sessions` has **two** sites that post
`PreviewChanged(None)` in the scope-off path:

1. **Global scope `else:` block** (when `_current_item()` is neither
   `ProjectHeader` nor `ComputerHeader`): if stickies are non-empty, the block
   posts `PreviewChanged(None)` at lines ~405-407 — before `sticky_in_scope` is
   even computed. By the time `sticky_in_scope` is reached, `preview_session_id`
   is already `None` for the global path.
2. **`if sticky_in_scope:` branch**: for project/computer scopes, if
   `preview_session_id is not None` it posts `PreviewChanged(None)`.

Additionally, `StickyChanged` is currently posted **unconditionally** at line
~454, after both `sticky_in_scope` and toggle-ON branches.

The fix for the scope-off (`sticky_in_scope=True`) path:

1. Remove the `post_message(PreviewChanged(None, request_focus=False))` call
   from the global scope `else:` block (keep the `self.preview_session_id = None`
   state mutation — it is still needed)
2. Remove the `post_message(PreviewChanged(None, request_focus=False))` call
   from inside `sticky_in_scope` (keep `self.preview_session_id = None`)
3. Remove sticky IDs from `self._sticky_session_ids`
4. Update `SessionRow.is_sticky` flags
5. Post `StickyAndPreviewChanged(sticky_session_ids=self._sticky_session_ids.copy(), preview_session_id=None, request_focus=False)`
6. Call `self._notify_state_changed()`

Move the unconditional `StickyChanged` post (currently line ~454) and its
`_notify_state_changed` call (currently line ~455) into the toggle-ON `else:`
block so they only fire when stickies are being added.

The toggle-ON branch and the global clear-preview-only-no-stickies path remain
unchanged — they only touch one concern.

**Why:** The scope-off path is the batch-toggle race site. When toggling stickies
off while a preview is active, the current code posts `PreviewChanged(None)` then
`StickyChanged([])`, allowing a flush between them.

**Verification:** Remove xfail marker on R3 spec
(`test_action_toggle_sticky_sessions_scope_off_posts_single_atomic_message`).

- [x] In the global scope `else:` block: for the has-stickies sub-path, remove the `post_message(PreviewChanged(None, request_focus=False))` call; keep `self.preview_session_id = None`
- [x] In the `if sticky_in_scope:` block: remove the `post_message(PreviewChanged(None, request_focus=False))` call; keep `self.preview_session_id = None`
- [x] Inside the `if sticky_in_scope:` block: post `StickyAndPreviewChanged` and call `_notify_state_changed`
- [x] Move the unconditional `StickyChanged` post and `_notify_state_changed` from the end of the function into the toggle-ON `else:` block
- [x] Keep toggle-ON path calling `StickyChanged` (unchanged semantics)
- [x] Keep global-no-stickies path unchanged (only posts `PreviewChanged`)

## Task 5: Update `on_session_row_pressed` double-click path

**File:** `teleclaude/cli/tui/views/sessions.py`

**What:** In `on_session_row_pressed`, the double-click detection block currently
calls `_toggle_sticky(session_id)` then, if `was_sticky`, posts
`PreviewChanged(session_id)`. Replace with:

1. Call `_toggle_sticky_state(session_id)` (pure mutation)
2. If `was_sticky`: set `self.preview_session_id = session_id`, post
   `StickyAndPreviewChanged(sticky_session_ids=self._sticky_session_ids.copy(), preview_session_id=session_id, request_focus=False)`
3. If not `was_sticky`: post `StickyChanged(self._sticky_session_ids.copy())`
   (single-concern — only sticky changed)
4. Call `self._notify_state_changed()`

**Why:** The double-click path is the click-based race site — same interleaving
bug as the Space path, but via mouse.

**Verification:** Remove xfail marker on R3 spec
(`test_on_session_row_pressed_double_click_sticky_posts_single_atomic_message`).

- [x] Import `StickyAndPreviewChanged` in the import block
- [x] Replace the double-click block with the atomic pattern
- [x] Keep single-click preview path unchanged

## Task 6: Add bridge handler `on_sticky_and_preview_changed`

**File:** `teleclaude/cli/tui/pane_bridge.py`

**What:** Add `on_sticky_and_preview_changed(self, message: StickyAndPreviewChanged)`
handler to `PaneManagerBridge`. It must:

1. Set `self._sticky_session_ids = message.sticky_session_ids`
2. Set `self._preview_session_id = message.preview_session_id`
3. Set `self._active_doc_preview = None` (preview changed — clear doc preview)
4. Call `self._mark_layout_dirty(focus=message.request_focus)`

All four steps happen before `_mark_layout_dirty`, ensuring both fields are
consistent when `_flush_layout` fires.

**Why:** Without a dedicated handler, the atomic message has no effect. The bridge
must apply both fields in one handler invocation — if it decomposed into separate
`on_sticky_changed` + `on_preview_changed` calls, the same interleaving bug
would exist at the handler level.

**Verification:** Remove xfail marker on R1 spec
(`test_on_sticky_and_preview_changed_applies_both_state_and_marks_layout_dirty_once`).

- [x] Import `StickyAndPreviewChanged` in the import block
- [x] Add `on_sticky_and_preview_changed` handler

## Task 7: Add app-level forwarding handler

**File:** `teleclaude/cli/tui/app.py`

**What:** Add `on_sticky_and_preview_changed(self, message: StickyAndPreviewChanged)`
handler to `TelecApp`. It must:

1. Forward to `pane_bridge.on_sticky_and_preview_changed(message)`
2. Call `self._update_banner_compactness(len(message.sticky_session_ids))`
3. Call `self._schedule_sky_width_invalidation()`

This mirrors the existing `on_sticky_changed` forwarding pattern.

**Why:** Textual messages bubble UP through ancestors, not sideways.
`PaneManagerBridge` is a sibling of `TabbedContent`, so it never receives
messages from `SessionsView`. The app must forward them, same as for every
other bridge-bound message.

**Verification:** Remove xfail marker on R4 spec
(`test_app_on_sticky_and_preview_changed_delegates_to_bridge_updates_banner_and_schedules_sky_width`).

- [x] Import `StickyAndPreviewChanged` in the import block (alongside existing
      `StickyChanged` import)
- [x] Add `on_sticky_and_preview_changed` handler after `on_sticky_changed`

## Task 8: Verify backward compatibility (R5)

**What:** Run the full test suite. Existing tests for individual `StickyChanged`
and `PreviewChanged` handling must pass without modification.

**Why:** R5 requires that single-concern call sites are unaffected. The existing
characterization tests in `test_pane_bridge.py` for `on_sticky_changed` and
`on_preview_changed` serve as R5 coverage.

**Verification:** All existing tests pass. No xfail markers to remove — R5 is
verified by the continued passing of existing specs.

- [x] Run pre-commit hooks (tests + lint + type-check)
- [x] Confirm no regressions in existing test files
