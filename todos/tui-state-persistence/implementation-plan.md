# Implementation Plan: tui-state-persistence

## Overview

Replace the surgical per-field TUI state persistence with a generalized `Persistable` protocol. Widgets declare their own persistable state; the app auto-discovers and collects it with debounced auto-save. Also fix the todo metadata refresh bug.

Two existing widgets already implement `get_persisted_state()` / `load_persisted_state()` — we formalize the protocol, extend it to `StatusBar` and app-level state, and replace the manual `_save_state()` call sites with event-driven auto-save.

## Phase 1: Core Changes

### Task 1.1: Define Persistable protocol and StateChanged message

**File(s):** `teleclaude/cli/tui/persistence.py` (new), `teleclaude/cli/tui/messages.py`

- [x] Create `teleclaude/cli/tui/persistence.py` with `Persistable` as a `Protocol` (or simple mixin) defining `get_persisted_state() -> dict` and `load_persisted_state(data: dict) -> None`
- [x] Add `StateChanged` message to `messages.py` — lightweight, no payload needed (the app collects from all widgets on save)

### Task 1.2: Rewrite state_store.py to generic namespaced dict

**File(s):** `teleclaude/cli/tui/state_store.py`

- [x] Replace `PersistedState` dataclass with simple `load_state() -> dict` / `save_state(state: dict)` that read/write the full namespaced dict
- [x] Add backward compat migration: detect old flat format (has `sticky_sessions` at top level), convert to namespaced format `{"sessions": {...}, "preparation": {...}, "status_bar": {...}, "app": {...}}`
- [x] Keep atomic write with lock (existing logic)

### Task 1.3: Add Persistable to StatusBar

**File(s):** `teleclaude/cli/tui/widgets/status_bar.py`

- [x] Implement `get_persisted_state()` returning `{"animation_mode": ..., "pane_theming_mode": ...}`
- [x] Implement `load_persisted_state(data)` restoring both values
- [x] Post `StateChanged` when `animation_mode` or `pane_theming_mode` reactive changes (via watch methods)

### Task 1.4: Adapt SessionsView to dict-based interface

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [x] Change `load_persisted_state()` to accept a single `dict` parameter instead of kwargs
- [x] Extract fields from dict internally (defensive: `.get()` with defaults)
- [x] `get_persisted_state()` already returns dict — no change needed
- [x] Post `StateChanged` on user mutations (sticky toggle, collapse, highlight, preview change)

### Task 1.5: Adapt PreparationView to post StateChanged

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] `get_persisted_state()` and `load_persisted_state()` already match the protocol — no signature change needed
- [x] Post `StateChanged` on expand/collapse

### Task 1.6: Debounced auto-save in app.py

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Add `on_state_changed()` handler that starts/resets a debounce timer (~500ms)
- [x] Timer fires: walk Persistable widgets, collect namespaced state, add app-level state (active_tab), call `save_state()`
- [x] Remove ALL manual `self._save_state()` calls (currently ~8 call sites)
- [x] Keep synchronous save in `_sigusr2_reload()` — flush immediately before exit, bypassing debounce
- [x] Keep synchronous save in `action_quit()` — same reason

### Task 1.7: Restore state on mount

**File(s):** `teleclaude/cli/tui/app.py`

- [x] In `on_mount()`: load state dict, distribute slices to each Persistable widget
- [x] Restore active tab from `state.get("app", {}).get("active_tab", "sessions")` — respect CLI `--view` override
- [x] Apply persisted `pane_theming_mode` via `theme.set_pane_theming_mode()` — this is the fix for the revert bug
- [x] Apply correct initial app theme (dark/light + agent/peaceful) based on persisted pane theming level

### Task 1.8: Decouple pane theming from daemon API (TUI side)

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/messages.py`

- [x] Remove `pane_theming_mode` from `DataRefreshed` message
- [x] In `_refresh_data()`: stop reading `pane_theming_mode` from daemon settings
- [x] In `on_data_refreshed()`: stop writing `pane_theming_mode` to status bar from daemon data
- [x] In `action_cycle_pane_theming()`: remove any daemon API patch_settings call (there isn't one currently, but ensure none is added)

### Task 1.9: Fix todo metadata refresh

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] Replace slug-only comparison in `update_data()` with a fingerprint that includes metadata fields (status, build_status, review_status, dor_score, deferrals_status, findings_count, has_requirements, has_impl_plan)
- [x] Rebuild view when fingerprint changes, not just when slug set changes

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Update `test_tui_footer_widget.py` if footer constructor changes
- [x] Verify `test_runtime_settings.py` still passes (daemon API untouched)
- [x] Add test for backward compat migration in state_store.py (old flat format → new namespaced format)
- [x] Add test for Persistable protocol (widget returns state, restores state)
- [x] Run `make test`

### Task 2.2: Manual verification

- [x] Edit `todos/*/state.yaml`, verify TUI todo view updates without `r` key
- [x] Cycle pane theming, SIGUSR2 reload, verify mode survives
- [x] Switch tab, SIGUSR2 reload, verify tab restored
- [x] Toggle animation, SIGUSR2 reload, verify animation mode survives
- [x] Pin sessions, collapse sessions, SIGUSR2 reload, verify all survive
- [x] Verify `~/.teleclaude/tui_state.json` has namespaced structure
- [x] Delete `tui_state.json`, verify TUI starts clean with defaults
- [x] Verify TTS toggle unaffected

### Task 2.3: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
