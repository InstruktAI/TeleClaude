# Implementation Plan: textual-footer-migration

## Overview

Replace the custom 3-line `ActionBar` with Textual's built-in `Footer(compact=True)`, convert all view `BINDINGS` from tuples to `Binding` objects with groups and Unicode key displays, update TCSS to style the Footer with the existing theme system, and remove the now-unnecessary `CursorContextChanged` message chain. The approach uses only Textual's public API.

## Phase 1: Convert BINDINGS to Binding Objects

### Task 1.1: Convert TelecApp BINDINGS

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] Import `Binding` from `textual.binding`
- [ ] Convert `BINDINGS` list from tuples to `Binding` objects
- [ ] Add `key_display` for tab numbers (1-4), and use Unicode symbols where appropriate
- [ ] Group navigation-like keys if applicable at app level

### Task 1.2: Convert SessionsView BINDINGS

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [ ] Import `Binding` from `textual.binding`
- [ ] Convert all tuples to `Binding` objects
- [ ] Create `Binding.Group(description="Nav", compact=True)` for up/down
- [ ] Create `Binding.Group(description="Fold", compact=True)` for left/right (collapse/expand)
- [ ] Create `Binding.Group(description="Fold", compact=True)` for +/- (expand/collapse all)
- [ ] Add `key_display` with Unicode arrows for up/down/left/right, and +/- symbols
- [ ] Add `Binding("R", "restart_all", "Restart All")` for computer node (research if Shift+A/Shift+R)
- [ ] Override `check_action(self, action, parameters) -> bool | None` to implement rich context:
  - **Computer Node**: Hide `new_session` (n), `kill_session` (k), `restart_session` (R). Show `restart_all` (R).
  - **Project Node**: Hide `kill_session` (k), `restart_session` (R). Show `new_session` (n).
  - **Session Node**: Show `kill_session` (k), `restart_session` (R). Hide `restart_all` (R).
- [ ] In `watch_cursor_index`, call `self.app.refresh_bindings()` to trigger Footer re-evaluation via `check_action`

### Task 1.3: Convert PreparationView BINDINGS

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [ ] Import `Binding` from `textual.binding`
- [ ] Convert all tuples to `Binding` objects
- [ ] Reuse same group pattern as SessionsView for nav and fold keys
- [ ] Add `key_display` with Unicode symbols
- [ ] Override `check_action(self, action, parameters) -> bool | None` to implement rich context:
  - **Project Node**: Hide `remove_todo` (R) and `activate` (Enter). Show `new_todo` (n).
  - **To-do Node**: Show `prepare` (p), `start_work` (s), `remove_todo` (R).
  - **File Node**: Show `preview_file` (space), `activate` (Enter - for edit). Inherit `remove_todo` (R) for parent.
- [ ] Update `action_prepare` and `action_start_work` to open `StartSessionModal` pre-filled with commands
- [ ] In `watch_cursor_index`, call `self.app.refresh_bindings()` to trigger Footer re-evaluation via `check_action`

### Task 1.6: Styling for Default Actions

**File(s):** `teleclaude/cli/tui/telec.tcss`, `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/views/sessions.py`

- [ ] Research how to apply bold styling to "default" bindings in the Footer
- [ ] Strategy: Use a custom ID for default bindings (e.g. `id="default-action"`) or a description prefix
- [ ] Apply CSS rule: `FooterKey#default-action { font-weight: bold; }` (if possible) or use Unicode bold chars in `key_display` and labels if necessary.
- [ ] Indication: Bold the entire binding (key + label) when it is the primary action for that node.
- [ ] Eliminate redundant `[Enter]` hints when the default key is visually indicated by bolding.

### Task 1.4: Convert JobsView BINDINGS

**File(s):** `teleclaude/cli/tui/views/jobs.py`

- [ ] Import `Binding` from `textual.binding`
- [ ] Convert tuples to `Binding` objects
- [ ] Add nav group for up/down with Unicode arrows

### Task 1.5: Convert ConfigView BINDINGS

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] Import `Binding` from `textual.binding`
- [ ] Convert tuples to `Binding` objects
- [ ] Add `key_display` with tab symbol for Tab/Shift+Tab, arrows for left/right

---

## Phase 2: Replace ActionBar with Footer

### Task 2.1: Update app.py compose

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] Import `Footer` from `textual.widgets`
- [ ] Remove `ActionBar` import
- [ ] In `compose()`, replace `yield ActionBar(id="action-bar")` with `yield Footer(compact=True, show_command_palette=False)`
- [ ] Update `#footer` Vertical to use `id="footer-area"` (avoid name collision with Footer widget)

### Task 2.2: Remove CursorContextChanged handling

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/views/sessions.py`, `teleclaude/cli/tui/messages.py`

- [ ] Remove `on_cursor_context_changed` method from `TelecApp`
- [ ] Remove `CursorContextChanged` import from `app.py`
- [ ] Remove `CursorContextChanged` posts from `sessions.py` `watch_cursor_index`
- [ ] Remove `CursorContextChanged` import from `sessions.py`
- [ ] Remove `CursorContextChanged` class from `messages.py`

### Task 2.3: Remove ActionBar references from tab switching

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] Remove `action_bar.active_view = tab_id` from `action_switch_tab`
- [ ] Remove `action_bar.active_view = tab_id` from `on_tabbed_content_tab_activated`

### Task 2.4: Delete ActionBar widget file

**File(s):** `teleclaude/cli/tui/widgets/action_bar.py`

- [ ] Delete the file entirely

### Task 2.5: Delete legacy footer widget file

**File(s):** `teleclaude/cli/tui/widgets/footer.py`

- [ ] Delete the file if it exists (legacy curses stub)

---

## Phase 3: Update TCSS

### Task 3.1: Update footer CSS

**File(s):** `teleclaude/cli/tui/telec.tcss`

- [ ] Change `#footer` to `#footer-area` (or match new container id)
- [ ] Set `#footer-area { dock: bottom; height: 2; }` (was 4)
- [ ] Remove `ActionBar { height: 3; }` rule
- [ ] Add `Footer` styling using design token variables:
  - `Footer { background: $panel; }` (or transparent to inherit)
  - `FooterKey .footer-key--key { ... }` — bold accent for key labels
  - `FooterKey .footer-key--description { ... }` — dimmed for descriptions
  - `FooterKey.-compact { ... }` — if padding adjustment needed
- [ ] Ensure styling works with all 4 theme variants (dark, light, dark-agent, light-agent)

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Run `make test` — all existing tests must pass
- [ ] Verify no imports reference `ActionBar` or `CursorContextChanged`

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

### Task 4.3: Visual Verification

- [ ] Send SIGUSR2 to reload TUI
- [ ] Verify footer shows bindings for each tab (switch through all 4)
- [ ] Verify bindings change when switching tabs (Footer auto-discovers from focused view)
- [ ] Verify grouped keys render with Unicode symbols
- [ ] Verify footer is 1 line (compact)
- [ ] Verify dark/light theme styling

### Task 4.4: Footer Logic Tests

**File(s):** `tests/unit/test_tui_footer_migration.py`

- [ ] Create new test file using Textual's `App.run_test`
- [ ] Verify `TelecApp` has `Footer` widget
- [ ] Verify `check_action` logic for `SessionsView`:
  - Selected `ComputerNode`: `restart_all` is visible, `new_session` is hidden.
  - Selected `ProjectNode`: `new_session` is visible.
  - Selected `SessionNode`: `kill_session`, `restart_session` are visible.
- [ ] Verify `check_action` logic for `PreparationView`:
  - Selected `ProjectNode`: `new_todo` is visible, `remove_todo` is hidden.
  - Selected `TodoRow`: `prepare`, `start_work`, `remove_todo` are visible.
  - Selected `TodoFileRow`: `preview_file`, `activate` are visible, `remove_todo` is visible (inherited).

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
