# Implementation Plan: rlf-tui

## Overview

Decompose six oversized TUI files using the mixin pattern (for class methods) and
direct class extraction (for standalone classes like animations). Each target file
gets 1-3 focused submodules. All external import paths remain backward-compatible
via re-exports.

Pattern for class-based splits: extract method groups into Mixin classes in separate
files. The original class inherits from the mixins. No behavior changes.

Pattern for standalone class splits: move classes to new files, re-export from
original module for backward compat.

---

## Phase 1: Core Changes

### Task 1.1: Split `animations/general.py`

**File(s):** `teleclaude/cli/tui/animations/general.py`,
`teleclaude/cli/tui/animations/sky.py` (new),
`teleclaude/cli/tui/animations/particles.py` (new),
`teleclaude/cli/tui/animations/__init__.py` (new)

- [x] Create `animations/sky.py`: move `SkyEntity` TypedDict + `GlobalSky` class (lines 27–422)
- [x] Create `animations/particles.py`: move `MatrixRain`, `FireBreath`, `SearchlightSweep`, `CinematicPrismSweep`, `Bioluminescence` classes (lines 836–1114)
- [x] Update `animations/general.py`: remove moved classes, add re-imports from `sky.py` and `particles.py` for backward compat; keep remaining banner animations + `GENERAL_ANIMATIONS`
- [x] Create `animations/__init__.py` re-exporting `GlobalSky`, `GENERAL_ANIMATIONS`
- [x] Verify `animations/general.py` ≤800 lines (505 lines)

### Task 1.2: Split `views/config.py`

**File(s):** `teleclaude/cli/tui/views/config.py`,
`teleclaude/cli/tui/views/config_editing.py` (new),
`teleclaude/cli/tui/views/config_render.py` (new)

- [x] Create `views/config_editing.py`: `ConfigContentEditingMixin` with cursor/edit/guided-mode methods (approx lines 554–820 of `ConfigContent`)
- [x] Create `views/config_render.py`: `ConfigContentRenderMixin` with `_render_*`, `render`, `on_click`, `watch_*` methods (approx lines 821–1086)
- [x] Update `views/config.py`: `ConfigContent` inherits from both mixins; remove moved methods
- [x] Verify `views/config.py` ≤800 lines (439 lines)

### Task 1.3: Split `views/preparation.py`

**File(s):** `teleclaude/cli/tui/views/preparation.py`,
`teleclaude/cli/tui/views/preparation_actions.py` (new)

- [x] Create `views/preparation_actions.py`: `PreparationViewActionsMixin` with all `action_*` methods, `check_action`, `watch_cursor_index`, `on_focus`, `_default_footer_action`, `_sync_default_footer_action`, `_find_root_todo_neighbors`, `_next_command` (approx lines 516–993)
- [x] Update `views/preparation.py`: `PreparationView` inherits from mixin; remove moved methods; keep tree-building, data mgmt, click handlers, display node classes
- [x] Verify `views/preparation.py` ≤800 lines (579 lines)

### Task 1.4: Split `views/sessions.py`

**File(s):** `teleclaude/cli/tui/views/sessions.py`,
`teleclaude/cli/tui/views/sessions_actions.py` (new),
`teleclaude/cli/tui/views/sessions_highlights.py` (new)

- [x] Create `views/sessions_actions.py`: `SessionsViewActionsMixin` with all `action_*` methods, `check_action`, `watch_cursor_index`, `on_focus`, `_default_footer_action`, `_sync_default_footer_action` (approx lines 631–1080)
- [x] Create `views/sessions_highlights.py`: `SessionsViewHighlightsMixin` with highlight management + `update_session`, `update_activity`, `get_persisted_state`, `optimistically_hide_session`, `confirm_session_closed` (approx lines 1083–1256)
- [x] Update `views/sessions.py`: `SessionsView` inherits from both mixins; remove moved methods; keep tree-building, data management, mouse click handlers, cursor helpers
- [x] Verify `views/sessions.py` ≤800 lines (623 lines)

### Task 1.5: Split `pane_manager.py`

**File(s):** `teleclaude/cli/tui/pane_manager.py`,
`teleclaude/cli/tui/pane_layout.py` (new),
`teleclaude/cli/tui/pane_theming.py` (new)

- [x] Create `pane_layout.py`: `PaneLayoutMixin` with `apply_layout`, `_build_session_specs`, `_compute_layout_signature`, `_compute_bg_signature`, `invalidate_bg_cache`, `_clear_active_state_if_sticky`, `_refresh_session_pane_backgrounds`, `_update_active_pane`, `_layout_is_unchanged`, `_render_layout`, `_track_session_pane`, `_is_tree_selected_session` (approx lines 336–1031)
- [x] Create `pane_theming.py`: `PaneThemingMixin` with `_apply_no_color_policy`, `_clear_session_pane_style`, `_set_pane_background`, `_set_tui_pane_background`, `_set_doc_pane_background`, `reapply_agent_colors` (approx lines 1032–1197)
- [x] Update `pane_manager.py`: `TmuxPaneManager` inherits from both mixins; remove moved methods; data classes extracted to `_pane_specs.py`, re-exported for backward compat
- [x] Verify `pane_manager.py` ≤800 lines (656 lines)

### Task 1.6: Split `app.py`

**File(s):** `teleclaude/cli/tui/app.py`,
`teleclaude/cli/tui/app_ws.py` (new),
`teleclaude/cli/tui/app_actions.py` (new),
`teleclaude/cli/tui/app_media.py` (new)

- [x] Create `app_ws.py`: `TelecAppWsMixin` with WS event handling + session message handlers (`_on_ws_event`, `_on_ws_connected`, `_handle_ws_connected`, `_handle_ws_event`, `on_session_started`, `on_session_updated`, `on_session_closed`, `on_agent_activity`) (approx lines 557–743)
- [x] Create `app_actions.py`: `TelecAppActionsMixin` with user-initiated action handlers + tab switching + pane theming (`on_create_session_request`, `on_kill_session_request`, `on_restart_session_request`, `on_restart_sessions_request`, `on_settings_changed`, `action_clear_layout`, all tab/theme actions) (approx lines 744–990)
- [x] Create `app_media.py`: `TelecAppMediaMixin` with animation/TTS/ChipTunes management (`action_cycle_animation`, `_force_spawn_sky`, `action_spawn_ufo`, `action_spawn_car`, `action_toggle_tts`, `action_chiptunes_play_pause`, all chiptunes/animation methods) (approx lines 990–1381)
- [x] Update `app.py`: `TelecApp` inherits from all three mixins; remove moved methods; keep init, compose, data refresh, pane bridge forwarding, state persistence, signals, lifecycle
- [x] Verify `app.py` ≤800 lines (658 lines)

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Run `make test` — 139 passed

### Task 2.2: Quality Checks

- [x] Run `make lint` — ruff/mypy/pylint clean on all TUI files; guardrail failures are 21 pre-existing files outside task scope (none in teleclaude/cli/tui/)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — no deferrals
