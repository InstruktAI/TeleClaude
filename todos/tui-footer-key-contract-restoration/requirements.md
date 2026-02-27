# Requirements: tui-footer-key-contract-restoration

## Goal

Complete the remaining footer/key-contract work without redoing already delivered layout migration.

Baseline already delivered and not part of this todo:

1. Unified 3-row footer exists (Row 1: context actions, Row 2: global actions dimmed, Row 3: agent pills + toggles).
2. View-switch keys (`1/2/3/4`) are hidden from footer via `show=False`.
3. Arrow/navigation hints are hidden from footer.
4. Sessions view has a working `check_action()` that gates actions per node type.
5. Preparation view has a working `check_action()` with node-aware action gating.
6. `StartSessionModal` exists with agent/mode selectors and prompt/title inputs.
7. `CreateSlugModal` exists for todo/bug creation with slug validation.

This todo focuses on missing behavior and correctness gaps against the target key contract.

## In Scope

### Sessions tab contract

#### Computer node

- `Enter`: Open `StartSessionModal` in **path-input mode** (new behavior — currently Enter on computer triggers `restart_all`).
  - The modal gains a text input for project path when opened from a computer node.
  - Path resolves `~` via `os.path.expanduser()` before validation.
  - Invalid path keeps modal open and shows inline field error on the path input.
  - **Code change**: `action_focus_pane()` must route `ComputerHeader` to the path-mode modal instead of `action_restart_all()`.
  - **Code change**: `check_action()` must enable `focus_pane` on `ComputerHeader` (already true) and the footer default action for computer must change from `restart_all` to `focus_pane`.
- `n`: Open **New Project modal** (entirely new — no modal exists for this).
  - Modal fields: name, description, path.
  - Path validation uses the same `~`-resolution and inline-error pattern as the session path input.
  - Rejects duplicate project name or path (check against existing `computer.trusted_dirs`).
  - On success: persist new entry to `computer.trusted_dirs` via the config patch layer (`telec config patch`) and refresh the tree.
- `R`: Restart all sessions for that computer (already works via `action_restart_all()`).
- `+/-`: Collapse/Expand computer sessions (already works).

#### Project node

- `Enter`: New Session in selected project (already works via `action_new_session()`).
- `R`: Restart all sessions for that project (new — currently `R`/`restart_all` only triggers on `ComputerHeader`). Needs a new `action_restart_project()` or scoped variant.
- `+/-`: Collapse/Expand selected project sessions (already works).

#### Session node

- `Space`: Preview/Sticky (already works via `action_toggle_preview()` with double-press detection).
- `Enter`: Focus (already works via `action_focus_pane()`).
- `k`: Kill (already works via `action_kill_session()` with `ConfirmModal`).
- `R`: Restart (already works via `action_restart_session()`).

### Todo tab contract

Computer grouping must be restored in the preparation tree (computer -> project -> todo/files).

Currently the prep view only has Project → Todo → TodoFile. The `ComputerHeader` widget from sessions view should be reused to add the computer tier.

#### Computer node

- `n`: New Project (same modal as Sessions tab — shared `NewProjectModal`).
- `+/-`: Collapse/Expand computer todos.

#### Project node

- `t`: New Todo (already works via `action_new_todo()` + `CreateSlugModal`).
- `Enter`: New Todo (default action, visible in footer — already works via `action_activate()` routing to `action_new_todo()` on project nodes).
- `b`: New Bug (already works via `action_new_bug()` + `CreateSlugModal`).
- `+/-`: Collapse/Expand project todos (already works).

#### Todo node

- `t`: New Todo (already works).
- `p`: Prepare — prefill `/next-prepare <slug>` in `StartSessionModal` (already works via `action_prepare()`).
- `s`: Start — prefill `/next-work <slug>` in `StartSessionModal` (already works via `action_start_work()`).
- `R`: Remove (already works via `action_remove_todo()` + `ConfirmModal`).
- `Enter`: Collapse/Expand selected todo (already works, `show=False` in footer).

#### Todo file node

- `Space`: Preview (already works via `action_preview_file()`).
- `Enter`: Edit (already works via `action_activate()` routing to file edit).

### Global row contract

Footer Row 2 visible globals (app-level bindings with `show=True`):

- `q`: Quit
- `r`: Refresh
- `t`: Cycle Theme

Footer Row 3 toggle controls (rendered by `TelecFooter` as pills, not as standard bindings):

- `s`: Speech toggle
- `a`: Animation toggle

Hidden but active globals (app-level bindings with `show=False`):

- `1/2/3/4` tab switching

## Out of Scope

- Rebuilding or redesigning the 3-row footer layout.
- Reverting to ActionBar or multi-widget footer stacks.
- Removing refresh behavior (`r`) in this todo.
- Broader navigation redesign outside this key contract.
- Config wizard changes for trusted_dirs management.

## Success Criteria

- [ ] Sessions Enter on computer node opens path-mode session modal (not restart_all).
- [ ] Sessions R on project node restarts all sessions for that project.
- [ ] New Project modal creates project, validates dedupe, writes `trusted_dirs`.
- [ ] StartSessionModal path-input mode resolves `~` and shows inline validation errors.
- [ ] Todo tree computer grouping is restored with Computer → Project → Todo hierarchy.
- [ ] Todo node and file-node behavior matches contract exactly.
- [ ] Hidden bindings remain executable where specified (`1/2/3/4`, todo-row Enter).
- [ ] Footer Row 1 hints reflect only context-specific visible actions per node.
- [ ] Footer Row 2 shows exactly `q`, `r`, `t` as global actions.
- [ ] Footer Row 3 shows toggle controls (`s`, `a`) and agent pills.
- [ ] Targeted tests covering node key visibility, hidden-active keys, and modal validation pass.
