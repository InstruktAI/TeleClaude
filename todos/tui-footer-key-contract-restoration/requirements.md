# Requirements: tui-footer-key-contract-restoration

## Goal

Complete the remaining footer/key-contract work without redoing already delivered layout migration.

Baseline already delivered and not part of this todo:

1. Unified 3-row footer exists.
2. View-switch keys (`1/2/3/4`) are hidden from footer.
3. Arrow/navigation hints are hidden from footer.

This todo now focuses only on missing behavior and correctness gaps.

## In Scope

### Sessions tab contract

#### Computer node

- `Enter`: New Session modal with an additional project-path input.
- Path resolves `~` before validation.
- Invalid path keeps modal open and shows inline field error.
- `n`: New Project modal.
- New Project modal fields: name, description, path.
- New Project fails if project/path already exists.
- Successful create adds the new path to `trusted_dirs`.
- `R`: Restart all sessions for that computer.
- `+/-`: Collapse/Expand computer sessions.

#### Project node

- `Enter`: New Session in selected project.
- `R`: Restart all sessions for that project.
- `+/-`: Collapse/Expand selected project sessions.

#### Session node

- `Space`: Preview/Sticky.
- `Enter`: Focus.
- `k`: Kill.
- `R`: Restart.

### Todo tab contract

Computer grouping must be restored in the todo/preparation tree (computer -> project -> todo/files).

#### Computer node

- `n`: New Project (same behavior as Sessions tab).
- `+/-`: Collapse/Expand computer todos.

#### Project node

- `t`: New Todo.
- `Enter`: New Todo (default action, visible in footer).
- `b`: New Bug.
- `+/-`: Collapse/Expand project todos.

#### Todo node

- `t`: New Todo.
- `p`: Prepare (prefill `/next-prepare <slug>` in StartSession modal).
- `s`: Start (prefill `/next-work <slug>` in StartSession modal).
- `R`: Remove.
- `Enter`: Collapse/Expand selected todo.
- Todo-row `Enter` stays active but hidden from footer.

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

Hidden but active globals:

- `1/2/3/4` tab switching

## Out of Scope

- Rebuilding or redesigning the 3-row footer layout.
- Reverting to ActionBar or multi-widget footer stacks.
- Removing refresh behavior (`r`) in this todo.
- Broader navigation redesign outside this key contract.

## Success Criteria

- [ ] Sessions node behavior matches contract exactly.
- [ ] Todo tree computer grouping is restored with expected ordering.
- [ ] Todo node and file-node behavior matches contract exactly.
- [ ] Hidden bindings remain executable where specified (`1/2/3/4`, todo-row Enter).
- [ ] New Session modal path validation behaves as specified (including `~` resolution and inline errors).
- [ ] New Project behavior enforces dedupe and updates `trusted_dirs` on success.
- [ ] Footer hints reflect only the intended visible actions per node/global contract.
- [ ] Targeted tests covering node key visibility, hidden-active keys, and modal validation pass.
