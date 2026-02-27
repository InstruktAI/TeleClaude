# Implementation Plan: tui-footer-key-contract-restoration

## Overview

This plan covers remaining gaps against the target key contract. The unified 3-row footer baseline, `check_action()` infrastructure, and most per-node actions already exist. Work focuses on: (1) changing Enter on computer to open path-mode session modal, (2) adding R-on-project restart, (3) creating the New Project modal, (4) adding path validation to StartSessionModal, (5) restoring computer grouping in the preparation tree, and (6) tests.

## Phase 1: Sessions key/action contract completion

### Task 1.1: Change Enter on ComputerHeader from restart_all to path-mode new session

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [x] In `action_focus_pane()`, change the `isinstance(item, ComputerHeader)` branch from calling `self.action_restart_all()` to calling `self.action_new_session()` with a flag indicating path-input mode (e.g., `path_mode=True`).
- [x] In `_default_footer_action()`, change the `ComputerHeader` return from `"restart_all"` to `"focus_pane"` (so Enter shows as default in footer for computer nodes).
- [x] In `check_action()`, keep `focus_pane` enabled on `ComputerHeader` (already true). Ensure `new_session` remains enabled only on `ProjectHeader` (the computer-level Enter uses `focus_pane`, not `new_session` binding).

### Task 1.2: Add restart-project capability

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [x] Add `action_restart_project()` method: collect all session IDs under the current `ProjectHeader`, show `ConfirmModal`, post `RestartSessionRequest` for each.
- [x] Add a `BINDINGS` entry for `restart_project` bound to `R` with `show=True`.
- [x] Update `check_action()`: `restart_session` enabled on `SessionRow`, `restart_all` enabled on `ComputerHeader`, `restart_project` enabled on `ProjectHeader`. The `R` key binding is overloaded via three separate action names, each guarded by `check_action()`.

### Task 1.3: Global visibility audit

**Files:** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] Verify app-level `BINDINGS`: `q` (Quit), `r` (Refresh), `t` (Cycle Theme) have `show=True`. Tab switches `1/2/3/4` have `show=False`. ✓ Already correct — no changes needed.
- [x] Verify `TelecFooter` Row 3 renders `s` (Speech) and `a` (Animation) as toggle pills (not as standard bindings). ✓ Already correct — icons rendered in `_render_controls_line()`.
- [x] Ensure no hidden navigation keys leak into footer rows. ✓ No regressions found.

## Phase 2: Todo tree and key contract completion

### Task 2.1: Restore computer grouping in Preparation tree

**Files:** `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/widgets/computer_header.py`

- [x] Reuse the existing `ComputerHeader` widget from sessions view.
- [x] Update the tree-building logic in preparation view to group projects under their computer node (Computer → Project → Todo → TodoFile), matching the sessions tree pattern.
- [x] Group by `p.computer` on each `ProjectWithTodosInfo`; computers sorted alphabetically, projects sorted alphabetically within computer.
- [x] `_nav_items` includes `ComputerHeader` entries; click handler `on_computer_header_pressed` added.
- [x] Preserve sort/group ordering: computers alphabetical, projects alphabetical within computer, todos by roadmap order within project.

### Task 2.2: Update Preparation check_action for computer nodes

**Files:** `teleclaude/cli/tui/views/preparation.py`

- [x] Import `ComputerHeader` and add it to `check_action()`.
- [x] Computer node enables: `new_project` (shared `n` binding), `expand_all`, `collapse_all`.
- [x] Computer node disables: `new_todo`, `new_bug`, `remove_todo`, `activate`, `preview_file`, `prepare`, `start_work`.
- [x] Existing project/todo/file node gating verified unchanged after adding computer tier.

## Phase 3: Modal/path validation contract completion

### Task 3.1: Add path-input mode to StartSessionModal

**Files:** `teleclaude/cli/tui/widgets/modals.py`

- [x] Add an optional `path_mode: bool = False` parameter to `StartSessionModal.__init__()`.
- [x] When `path_mode=True`, render an additional `Input` widget for project path between the computer label and agent selector.
- [x] Path validation: on Enter, call `os.path.expanduser()` on the path input value, then check `os.path.isdir()`.
- [x] On invalid path: keep modal open, set an inline error label on the path input ("Path does not exist or is not a directory").
- [x] On valid path: include the resolved path in the `CreateSessionRequest` result.
- [x] When `path_mode=False` (default), behavior is unchanged — no path input shown.

### Task 3.2: Create NewProjectModal

**Files:** `teleclaude/cli/tui/widgets/modals.py`

- [x] Create `NewProjectModal(ModalScreen[NewProjectResult | None])` with fields: name (`Input`), description (`Input`), path (`Input`).
- [x] Path validation: same `~`-resolution and `isdir()` check as Task 3.1.
- [x] Dedupe check: compare name and resolved path against caller-provided `existing_names`/`existing_paths`. Show inline error if duplicate found.
- [x] On success: return `NewProjectResult(name, description, path)`.
- [x] Caller handles persistence via `telec config patch --yaml`.
- [x] Added `NewProjectResult` dataclass to `modals.py`.

### Task 3.3: Wire New Project action into views

**Files:** `teleclaude/cli/tui/views/sessions.py`, `teleclaude/cli/tui/views/preparation.py`

- [x] Add `action_new_project()` to both views.
- [x] On `NewProjectResult`: invoke `telec config patch` to update `computer.trusted_dirs`, notify user, refresh follows on next data poll.
- [x] Add `BINDINGS` entry for `new_project` bound to `n` in both views. Guarded by `check_action()` (computer node only).
- [x] `n` on project → `new_session` (sessions view) / `new_todo` (prep view). `n` on computer → `new_project`. Separate action names, no conflict.

## Phase 4: Tests and verification

### Task 4.1: Key visibility and behavior tests

**Files:** `tests/unit/test_tui_key_contract.py` (new file)

- [x] Test `SessionsView.check_action()` returns correct enabled/disabled for each action × node type combination.
- [x] Test `PreparationView.check_action()` returns correct enabled/disabled including the new computer tier.
- [x] Test hidden-but-active keys: arrow keys have `show=False` but are bound.
- [x] Test `_default_footer_action()` returns `focus_pane` for computer, `new_session` for project, `focus_pane` for session.
- [x] Test that default action is always enabled for its node type.

### Task 4.2: Modal validation tests

**Files:** `tests/unit/test_tui_key_contract.py`

- [x] Test `StartSessionModal` path-mode: `~` resolves, invalid path shows error, valid path returns in result, no path_mode leaves modal unchanged.
- [x] Test `NewProjectModal`: duplicate name rejected, duplicate path rejected, invalid path rejected, valid input returns `NewProjectResult`.

### Task 4.3: Preparation tree structure test

**Files:** `tests/unit/test_tui_key_contract.py`

- [x] Test that preparation tree `_nav_items` includes `ComputerHeader` before `ProjectHeader`.
- [x] Test that each project appears under its computer node.
- [x] Test sort order: computers alphabetical.
- [x] Test single-computer case still renders a `ComputerHeader`.

## Rollout Notes

- Ship as small focused commits by phase.
- Reuse existing footer/modal infrastructure; avoid another footer architecture change.
- Treat the current 3-row footer as fixed baseline and regressions as bugs.
- The `n` key has dual meaning: `new_session` on project nodes, `new_project` on computer nodes. Use separate action names guarded by `check_action()` to avoid conflict.
