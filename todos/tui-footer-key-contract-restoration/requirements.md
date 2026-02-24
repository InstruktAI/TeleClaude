# Requirements: tui-footer-key-contract-restoration

## Goal

Restore and lock a deterministic 3-row footer contract in the TUI with binding-driven hints and node-context behavior, while preserving TeleClaude's bottom control row (agents + toggles) and reducing visible hint noise.

Footer hard requirement:

1. Row 1: context-aware actions for selected node
2. Row 2: global actions
3. Row 3: agent availability + controls (speech/theme/animation)

## In Scope

- Keep one unified footer widget rendering all three rows.
- Drive row-1 and row-2 hints from real active bindings (no manual string drift).
- Keep `1/2/3/4` tab switch keys active but hidden from footer.
- Implement exact node-specific key visibility/behavior below.

### Sessions tab contract

#### Computer node

- `Enter`: New Session modal with additional inline project-path field.
- Path field validates on submit.
- Tilde paths resolve before validation.
- Invalid path keeps modal open and shows inline field error.
- `n`: New Project modal.
- New Project modal captures name, description, and path (same validation component).
- Project create fails if project/path already exists.
- Successful create adds project path to `trusted_dirs`.
- `R`: Restart All (all sessions for that computer).
- `+/-`: Collapse/Expand computer sessions.

#### Project node

- `Enter`: New Session in selected project.
- `R`: Restart All (project sessions only).
- `+/-`: Collapse/Expand selected project sessions.

#### Session node

- `Space`: Preview/Sticky.
- `Enter`: Focus.
- `k`: Kill.
- `R`: Restart.

### Todo tab contract

Computer grouping must be visible again in todo/preparation tree (same computer -> project grouping pattern).

#### Computer node

- `n`: New Project (same behavior and validation contract as Sessions tab).
- `+/-`: Collapse/Expand computer todos.

#### Project node

- `t`: New Todo.
- `Enter`: New Todo (default action; visually highlighted in footer).
- `b`: New Bug.
- `+/-`: Collapse/Expand project todos.

#### Todo node

- `t`: New Todo.
- `p`: Prepare (opens StartSession modal prefilled with `/next-prepare <slug>`).
- `s`: Start (opens StartSession modal prefilled with `/next-work <slug>`).
- `R`: Remove.
- `Enter`: collapse/expand selected todo.
- `Enter` remains active but hidden from footer on todo rows.

#### Todo file node

- `Space`: Preview.
- `Enter`: Edit.

### Global row contract

Visible globals:

- `q`: Quit
- `r`: Refresh
- `t`: Cycle Theme
- `s`: Speech toggle
- `a`: Animation toggle

Hidden globals:

- `1/2/3/4` tab switching stays active but hidden.

## Out of Scope

- Removing refresh behavior (`r`) in this todo.
- Broader navigation redesign beyond described keymap.
- Non-footer TUI redesign unrelated to this key contract.

## Success Criteria

- [ ] Footer always renders exactly 3 rows in running TUI.
- [ ] Row 1 only shows context actions for current node.
- [ ] Row 2 only shows global actions listed above.
- [ ] Row 3 shows agents and controls; no clipping or row replacement.
- [ ] Hidden bindings remain executable where specified (`1/2/3/4`, todo-row Enter).
- [ ] Sessions node behavior matches contract exactly.
- [ ] Todo node behavior matches contract exactly.
- [ ] New Session modal path validation behaves as specified.
- [ ] New Project creation behavior (validation + dedupe + trusted_dirs update) behaves as specified.
- [ ] Targeted tests covering node key visibility, hidden-active keys, and modal validation pass.
