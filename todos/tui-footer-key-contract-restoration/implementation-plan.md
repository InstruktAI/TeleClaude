# Implementation Plan: tui-footer-key-contract-restoration

## Overview

This plan covers remaining gaps against the target key contract. The unified 3-row footer baseline, `check_action()` infrastructure, and most per-node actions already exist. Work focuses on: (1) changing Enter on computer to open path-mode session modal, (2) adding R-on-project restart, (3) creating the New Project modal, (4) adding path validation to StartSessionModal, (5) restoring computer grouping in the preparation tree, and (6) tests.

## Phase 1: Sessions key/action contract completion

### Task 1.1: Change Enter on ComputerHeader from restart_all to path-mode new session

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [ ] In `action_focus_pane()`, change the `isinstance(item, ComputerHeader)` branch from calling `self.action_restart_all()` to calling `self.action_new_session()` with a flag indicating path-input mode (e.g., `path_mode=True`).
- [ ] In `_default_footer_action()`, change the `ComputerHeader` return from `"restart_all"` to `"focus_pane"` (so Enter shows as default in footer for computer nodes).
- [ ] In `check_action()`, keep `focus_pane` enabled on `ComputerHeader` (already true). Ensure `new_session` remains enabled only on `ProjectHeader` (the computer-level Enter uses `focus_pane`, not `new_session` binding).

### Task 1.2: Add restart-project capability

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [ ] Add `action_restart_project()` method: collect all session IDs under the current `ProjectHeader`, show `ConfirmModal`, post `RestartSessionRequest` for each.
- [ ] Add a `BINDINGS` entry for `restart_project` bound to `R` with `show=True`.
- [ ] Update `check_action()`: `restart_session` enabled on `SessionRow`, `restart_all` enabled on `ComputerHeader`, `restart_project` enabled on `ProjectHeader`. The `R` key binding should be overloaded via three separate action names, each guarded by `check_action()`.
- [ ] Alternatively, use a single `restart` action that dispatches by node type in the action handler (simpler binding, same `check_action` gating).

### Task 1.3: Global visibility audit

**Files:** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/widgets/telec_footer.py`

- [ ] Verify app-level `BINDINGS`: `q` (Quit), `r` (Refresh), `t` (Cycle Theme) have `show=True`. Tab switches `1/2/3/4` have `show=False`.
- [ ] Verify `TelecFooter` Row 3 renders `s` (Speech) and `a` (Animation) as toggle pills (not as standard bindings).
- [ ] Ensure no hidden navigation keys leak into footer rows. This is an audit task — fix only if regressions found.

## Phase 2: Todo tree and key contract completion

### Task 2.1: Restore computer grouping in Preparation tree

**Files:** `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/widgets/computer_header.py`

- [ ] Reuse the existing `ComputerHeader` widget from sessions view.
- [ ] Update the tree-building logic in preparation view to group projects under their computer node (Computer → Project → Todo → TodoFile), matching the sessions tree pattern.
- [ ] The data source already has `_slug_to_computer` mapping — use it to group todos by computer in `_mount_node()` or equivalent builder.
- [ ] Update `_nav_items` depth tracking to account for the added computer tier.
- [ ] Preserve sort/group ordering: computers alphabetical, projects alphabetical within computer, todos by roadmap order within project.

### Task 2.2: Update Preparation check_action for computer nodes

**Files:** `teleclaude/cli/tui/views/preparation.py`

- [ ] Import `ComputerHeader` and add it to `check_action()`.
- [ ] Computer node enables: `new_project` (shared `n` binding), `expand_all`, `collapse_all`.
- [ ] Computer node disables: `new_todo`, `new_bug`, `remove_todo`, `activate`, `preview_file`, `prepare`, `start_work`.
- [ ] Verify existing project/todo/file node gating still works after adding the computer tier.

## Phase 3: Modal/path validation contract completion

### Task 3.1: Add path-input mode to StartSessionModal

**Files:** `teleclaude/cli/tui/widgets/modals.py`

- [ ] Add an optional `path_mode: bool = False` parameter to `StartSessionModal.__init__()`.
- [ ] When `path_mode=True`, render an additional `Input` widget for project path between the computer label and agent selector.
- [ ] Path validation: on Enter, call `os.path.expanduser()` on the path input value, then check `os.path.isdir()`.
- [ ] On invalid path: keep modal open, set an inline error label on the path input (e.g., "Path does not exist" or "Not a directory").
- [ ] On valid path: include the resolved path in the `CreateSessionRequest` result.
- [ ] When `path_mode=False` (default), behavior is unchanged — no path input shown.

### Task 3.2: Create NewProjectModal

**Files:** `teleclaude/cli/tui/widgets/modals.py`

- [ ] Create `NewProjectModal(ModalScreen[NewProjectResult | None])` with fields: name (`Input`), description (`Input`), path (`Input`).
- [ ] Path validation: same `~`-resolution and `isdir()` check as Task 3.1. Share the validation helper.
- [ ] Dedupe check: compare name and resolved path against existing `computer.trusted_dirs` entries. Show inline error if duplicate found.
- [ ] On success: return `NewProjectResult(name, description, path)`.
- [ ] The caller (sessions/preparation view) handles persistence: call `telec config patch --yaml '...'` to append to `computer.trusted_dirs`, then refresh the tree.

### Task 3.3: Wire New Project action into views

**Files:** `teleclaude/cli/tui/views/sessions.py`, `teleclaude/cli/tui/views/preparation.py`

- [ ] Add `action_new_project()` method to both views (or a shared mixin).
- [ ] On `NewProjectResult`: invoke `telec config patch` to update `computer.trusted_dirs`, then call tree refresh.
- [ ] Add `BINDINGS` entry for `new_project` bound to `n` on computer nodes. Guard with `check_action()`.
- [ ] In sessions view: `n` on computer → `NewProjectModal`. `n` on project → currently `new_session` — verify no conflict (use separate action names if needed).

## Phase 4: Tests and verification

### Task 4.1: Key visibility and behavior tests

**Files:** `tests/unit/cli/tui/` (new test file or extend existing)

- [ ] Test `SessionsView.check_action()` returns correct enabled/disabled for each action × node type combination.
- [ ] Test `PreparationView.check_action()` returns correct enabled/disabled including the new computer tier.
- [ ] Test hidden-but-active keys: `1/2/3/4` have `show=False` but are bound. Todo-row `Enter` (`activate`) has `show=False` on todo nodes.
- [ ] Test `_default_footer_action()` returns `focus_pane` for computer, `new_session` for project, `focus_pane` for session.

### Task 4.2: Modal validation tests

**Files:** `tests/unit/cli/tui/` (new test file or extend existing)

- [ ] Test `StartSessionModal` path-mode: `~` resolves, invalid path shows error, valid path returns in result.
- [ ] Test `NewProjectModal`: duplicate name/path rejected, valid input returns `NewProjectResult`.
- [ ] Test `NewProjectModal` path validation: `~` resolution, non-directory rejected.

### Task 4.3: Preparation tree structure test

**Files:** `tests/unit/cli/tui/`

- [ ] Test that preparation tree builds Computer → Project → Todo → TodoFile hierarchy.
- [ ] Test sort order: computers alphabetical, projects alphabetical, todos by roadmap order.

## Rollout Notes

- Ship as small focused commits by phase.
- Reuse existing footer/modal infrastructure; avoid another footer architecture change.
- Treat the current 3-row footer as fixed baseline and regressions as bugs.
- The `n` key has dual meaning: `new_session` on project nodes, `new_project` on computer nodes. Use separate action names guarded by `check_action()` to avoid conflict.
