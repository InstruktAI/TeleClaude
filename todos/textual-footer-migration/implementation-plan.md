# Implementation Plan: textual-footer-migration

## Overview

Replace the custom 3-line `ActionBar` with Textual's built-in `Footer(compact=True)`, convert all view `BINDINGS` from tuples to `Binding` objects with groups and Unicode key displays, update TCSS to style the Footer with the existing theme system, and remove the now-unnecessary `CursorContextChanged` message chain. The approach uses only Textual's public API.

## Phase 1: Convert BINDINGS to Binding Objects

### Task 1.1: Convert TelecApp BINDINGS

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Import `Binding` from `textual.binding`
- [x] Convert `BINDINGS` list from tuples to `Binding` objects
- [x] Add `key_display` for tab numbers (1-4), and use Unicode symbols where appropriate
- [x] Group navigation-like keys if applicable at app level

### Task 1.2: Convert SessionsView BINDINGS

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [x] Import `Binding` from `textual.binding`
- [x] Convert all tuples to `Binding` objects
- [x] Create `Binding.Group(description="Nav", compact=True)` for up/down
- [x] Create `Binding.Group(description="Fold", compact=True)` for left/right (collapse/expand)
- [x] Create `Binding.Group(description="Fold", compact=True)` for +/- (expand/collapse all)
- [x] Add `key_display` with Unicode arrows for up/down/left/right, and +/- symbols
- [x] Add `Binding("R", "restart_all", "Restart All")` for computer node (research if Shift+A/Shift+R)
- [x] Override `check_action(self, action, parameters) -> bool | None` to implement rich context:
  - **Computer Node**: Hide `new_session` (n), `kill_session` (k), `restart_session` (R). Show `restart_all` (R).
  - **Project Node**: Hide `kill_session` (k), `restart_session` (R). Show `new_session` (n).
  - **Session Node**: Show `kill_session` (k), `restart_session` (R). Hide `restart_all` (R).
- [x] In `watch_cursor_index`, call `self.app.refresh_bindings()` to trigger Footer re-evaluation via `check_action`

### Task 1.3: Convert PreparationView BINDINGS

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] Import `Binding` from `textual.binding`
- [x] Convert all tuples to `Binding` objects
- [x] Reuse same group pattern as SessionsView for nav and fold keys
- [x] Add `key_display` with Unicode symbols
- [x] Override `check_action(self, action, parameters) -> bool | None` to implement rich context:
  - **Project Node**: Hide `remove_todo` (R) and `activate` (Enter). Show `new_todo` (n).
  - **To-do Node**: Show `prepare` (p), `start_work` (s), `remove_todo` (R).
  - **File Node**: Show `preview_file` (space), `activate` (Enter - for edit). Inherit `remove_todo` (R) for parent.
- [x] Update `action_prepare` and `action_start_work` to open `StartSessionModal` pre-filled with commands
- [x] In `watch_cursor_index`, call `self.app.refresh_bindings()` to trigger Footer re-evaluation via `check_action`

### Task 1.6: Styling for Default Actions

**File(s):** `teleclaude/cli/tui/telec.tcss`, `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/views/sessions.py`

- [x] Research how to apply bold styling to "default" bindings in the Footer
- [x] Strategy: Use a custom ID for default bindings (e.g. `id="default-action"`) or a description prefix
- [x] Apply CSS rule: `FooterKey#default-action { font-weight: bold; }` (if possible) or use Unicode bold chars in `key_display` and labels if necessary.
- [x] Indication: Bold the entire binding (key + label) when it is the primary action for that node.
- [x] Eliminate redundant `[Enter]` hints when the default key is visually indicated by bolding.

### Task 1.4: Convert JobsView BINDINGS

**File(s):** `teleclaude/cli/tui/views/jobs.py`

- [x] Import `Binding` from `textual.binding`
- [x] Convert tuples to `Binding` objects
- [x] Add nav group for up/down with Unicode arrows

### Task 1.5: Convert ConfigView BINDINGS

**File(s):** `teleclaude/cli/tui/views/config.py`

- [x] Import `Binding` from `textual.binding`
- [x] Convert tuples to `Binding` objects
- [x] Add `key_display` with tab symbol for Tab/Shift+Tab, arrows for left/right

---

## Phase 2: Replace ActionBar with Footer

### Task 2.1: Update app.py compose

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Import `Footer` from `textual.widgets`
- [x] Remove `ActionBar` import
- [x] In `compose()`, replace `yield ActionBar(id="action-bar")` with `yield Footer(compact=True, show_command_palette=False)`
- [x] Update `#footer` Vertical to use `id="footer-area"` (avoid name collision with Footer widget)

### Task 2.2: Remove CursorContextChanged handling

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/views/sessions.py`, `teleclaude/cli/tui/messages.py`

- [x] Remove `on_cursor_context_changed` method from `TelecApp`
- [x] Remove `CursorContextChanged` import from `app.py`
- [x] Remove `CursorContextChanged` posts from `sessions.py` `watch_cursor_index`
- [x] Remove `CursorContextChanged` import from `sessions.py`
- [x] Remove `CursorContextChanged` class from `messages.py`

### Task 2.3: Remove ActionBar references from tab switching

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Remove `action_bar.active_view = tab_id` from `action_switch_tab`
- [x] Remove `action_bar.active_view = tab_id` from `on_tabbed_content_tab_activated`

### Task 2.4: Delete ActionBar widget file

**File(s):** `teleclaude/cli/tui/widgets/action_bar.py`

- [x] Delete the file entirely

### Task 2.5: Delete legacy footer widget file

**File(s):** `teleclaude/cli/tui/widgets/footer.py`

- [x] Delete the file if it exists (legacy curses stub)

---

## Phase 3: Update TCSS

### Task 3.1: Update footer CSS

**File(s):** `teleclaude/cli/tui/telec.tcss`

- [x] Change `#footer` to `#footer-area` (or match new container id)
- [x] Set `#footer-area { dock: bottom; height: 2; }` (was 4)
- [x] Remove `ActionBar { height: 3; }` rule
- [x] Add `Footer` styling using design token variables:
  - `Footer { background: $panel; }` (or transparent to inherit)
  - `FooterKey .footer-key--key { ... }` — bold accent for key labels
  - `FooterKey .footer-key--description { ... }` — dimmed for descriptions
  - `FooterKey.-compact { ... }` — if padding adjustment needed
- [x] Ensure styling works with all 4 theme variants (dark, light, dark-agent, light-agent)

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Run `make test` — all existing tests must pass
- [x] Verify no imports reference `ActionBar` or `CursorContextChanged`

### Task 4.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

### Task 4.3: Visual Verification

- [x] Send SIGUSR2 to reload TUI
- [x] Verify footer shows bindings for each tab (switch through all 4)
- [x] Verify bindings change when switching tabs (Footer auto-discovers from focused view)
- [x] Verify grouped keys render with Unicode symbols
- [x] Verify footer is 1 line (compact)
- [x] Verify dark/light theme styling

### Task 4.4: Footer Logic Tests

**File(s):** `tests/unit/test_tui_footer_migration.py`

- [x] Create new test file using Textual's `App.run_test`
- [x] Verify `TelecApp` has `Footer` widget
- [x] Verify `check_action` logic for `SessionsView`:
  - Selected `ComputerNode`: `restart_all` is visible, `new_session` is hidden.
  - Selected `ProjectNode`: `new_session` is visible.
  - Selected `SessionNode`: `kill_session`, `restart_session` are visible.
- [x] Verify `check_action` logic for `PreparationView`:
  - Selected `ProjectNode`: `new_todo` is visible, `remove_todo` is hidden.
  - Selected `TodoRow`: `prepare`, `start_work`, `remove_todo` are visible.
  - Selected `TodoFileRow`: `preview_file`, `activate` are visible, `remove_todo` is visible (inherited).

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
