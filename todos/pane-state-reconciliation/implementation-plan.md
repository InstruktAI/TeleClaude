# Implementation Plan: pane-state-reconciliation

## Overview

Replace the fragile 7-field PaneState with a 2-field source of truth plus a reconciliation step that queries tmux for actual panes before every layout operation. This eliminates three corruption paths: external pane death, stale layout signatures, and destructive reload adoption.

The approach is additive-then-subtractive: first add reconciliation, then simplify state, then remove dead reload code. Each phase is independently testable.

## Phase 1: Add reconciliation to PaneManager

### Task 1.1: Add `_reconcile()` method

**File(s):** `teleclaude/cli/tui/pane_manager.py`

- [x] Add `_reconcile()` that calls `list-panes -F "#{pane_id}"` once, builds a set of live pane IDs, and removes entries from `session_to_pane` where the pane is dead
- [x] Also prune `sticky_pane_ids`, `sticky_session_to_pane`, `session_pane_ids` in sync
- [x] Clear `parent_pane_id` / `parent_session` / `parent_spec_id` if the parent pane is dead
- [x] Call `_reconcile()` at the top of `apply_layout()` before any signature checks

### Task 1.2: Replace `_adopt_existing_panes()` with reconciling adoption

**File(s):** `teleclaude/cli/tui/pane_manager.py`

- [ ] Add `is_reload: bool = False` parameter to `TmuxPaneManager.__init__()`
- [ ] When `is_reload=True`: skip `_adopt_existing_panes()`, instead call `_adopt_for_reload()` which discovers existing non-TUI panes and pre-populates `session_pane_ids` (without session-to-pane mapping yet — that happens when data arrives)
- [ ] When `is_reload=False` (cold start): keep existing behavior of killing orphaned panes
- [ ] Delete `_adopt_existing_panes()` — replace both paths with `_init_panes(is_reload)`

### Task 1.3: Pass reload flag through the chain

**File(s):** `teleclaude/cli/tui/pane_bridge.py`, `teleclaude/cli/tui/app.py`

- [ ] `PaneManagerBridge.__init__` accepts `is_reload: bool` and passes to `TmuxPaneManager(is_reload=is_reload)`
- [ ] `TelecApp` passes `self._is_reload` when constructing PaneManagerBridge (in compose)
- [ ] Remove `TELEC_RELOAD` env var from `telec.py` — pass reload state through the widget tree instead

---

## Phase 2: Simplify PaneState

### Task 2.1: Reduce PaneState to 2 fields

**File(s):** `teleclaude/cli/tui/pane_manager.py`

- [ ] Replace 7-field PaneState with:
  ```python
  @dataclass
  class PaneState:
      session_to_pane: dict[str, str] = field(default_factory=dict)
      active_session_id: str | None = None
  ```
- [ ] Add derived properties / helper methods:
  - `get_active_pane_id()` → `session_to_pane.get(active_session_id)`
  - `get_sticky_panes(sticky_ids)` → filtered dict
  - `get_active_tmux_session()` → look up from session catalog
- [ ] Update all call sites that read `parent_pane_id`, `parent_session`, `parent_spec_id`, `sticky_pane_ids`, `sticky_session_to_pane`, `session_pane_ids` to use the new derived helpers

### Task 2.2: Update layout signature computation

**File(s):** `teleclaude/cli/tui/pane_manager.py`

- [ ] `_compute_layout_signature()` uses `active_session_id` from state instead of `parent_spec_id`
- [ ] `_layout_is_unchanged()` still works correctly with the simplified state
- [ ] `_compute_bg_signature()` still works correctly

### Task 2.3: Update `_render_layout` and `_update_active_pane`

**File(s):** `teleclaude/cli/tui/pane_manager.py`

- [ ] `_render_layout()` writes to `state.session_to_pane` and `state.active_session_id` only
- [ ] `_update_active_pane()` updates `state.session_to_pane` mapping and `state.active_session_id`
- [ ] `_cleanup_all_session_panes()` clears `state.session_to_pane` and `state.active_session_id`
- [ ] `_track_session_pane()` writes only to `state.session_to_pane`

---

## Phase 3: Remove dead reload code

### Task 3.1: Remove `seed_layout_for_reload`

**File(s):** `teleclaude/cli/tui/pane_bridge.py`, `teleclaude/cli/tui/app.py`

- [ ] Delete `PaneManagerBridge.seed_layout_for_reload()` method
- [ ] Delete the `elif self._is_reload:` branch in `TelecApp.on_data_refreshed()`
- [ ] Delete `_is_reload` field from `TelecApp.__init__`
- [ ] Remove `_make_spec` static method from PaneManagerBridge (only used by seed_layout_for_reload)

### Task 3.2: Clean up reload env var

**File(s):** `teleclaude/cli/telec.py`, `teleclaude/cli/tui/app.py`

- [ ] Remove `os.environ["TELEC_RELOAD"] = "1"` from `telec.py:_run_tui`
- [ ] Remove `os.environ.pop("TELEC_RELOAD", "")` from `TelecApp.__init__`
- [ ] The reload signal is now: app exits with RELOAD_EXIT, telec.py re-execs, compose passes `is_reload=True` to PaneManagerBridge based on whether the prior run returned RELOAD_EXIT

### Task 3.3: Simplify reload state propagation

**File(s):** `teleclaude/cli/telec.py`, `teleclaude/cli/tui/app.py`

- [ ] `_run_tui()` accepts `is_reload: bool = False` parameter
- [ ] On RELOAD_EXIT, recursive call: `_run_tui(is_reload=True)` instead of `os.execvp`
- [ ] Wait — `os.execvp` is needed to reload Python modules from disk. Keep `os.execvp` but pass reload flag via env var (simpler than the current approach, but keep it as `_TELEC_INTERNAL_RELOAD` to signal it's not user-facing)
- [ ] OR: keep `os.execvp` + env var but only use it for the PaneManager init, not for the elaborate seed_layout machinery

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Update `tests/unit/test_sessions_view.py` if it references PaneState fields
- [ ] Add unit test: `_reconcile()` prunes dead pane IDs from `session_to_pane`
- [ ] Add unit test: `_reconcile()` clears `active_session_id` when active pane is dead
- [ ] Add unit test: cold-start init kills orphaned panes
- [ ] Add unit test: reload init preserves existing panes
- [ ] Run `make test`

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

### Task 4.3: Manual verification

- [ ] Open TUI, pin 2 sticky sessions, send SIGUSR2 — panes survive
- [ ] Open TUI, preview a session, externally `tmux kill-pane` it, click another session — no crash, dead pane pruned
- [ ] Cold start TUI with leftover panes from crashed process — orphans killed cleanly

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
