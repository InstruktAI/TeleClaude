# Requirements: new-bug-key-in-todos-pane

## Goal

Add a `b` keybinding to the TUI todos pane that creates a bug todo and opens `bug.md` for editing, plus a `telec bugs create <slug>` CLI command as the lightweight counterpart to `telec todo create`.

## Problem

There is no quick way to create a bug report from the TUI. The existing `n` key creates a full todo (with `input.md`, `requirements.md`, `implementation-plan.md`, etc.), which is overkill for a bug. Bugs need only `bug.md` + `state.yaml`. The user must currently use the CLI to create bugs, breaking TUI flow.

## In Scope

1. **TUI keybinding** — `b` key in the PreparationView (todos pane) opens a CreateBugModal, calls `create_bug_skeleton()`, and opens `bug.md` in the editor.
2. **CLI command** — `telec bugs create <slug>` scaffolds a bug todo with `bug.md` + `state.yaml` (no orchestrator dispatch, no worktree). Analogous to `telec todo create`.
3. **Modal reuse or adaptation** — Use or adapt `CreateTodoModal` for bug slug entry.

## Out of Scope

- Bug orchestrator dispatch (covered by `bug-delivery-service` → `telec bugs report`).
- Bug listing (covered by `bug-delivery-service` → `telec bugs list`).
- State machine changes for bug detection (covered by `bug-delivery-service`).
- `create_bug_skeleton()` function itself (created by `bug-delivery-service`).

## Success Criteria

- [ ] Pressing `b` in the TUI todos pane opens a slug input modal.
- [ ] After entering a slug, `bug.md` + `state.yaml` are created in `todos/{slug}/`.
- [ ] The editor opens with `bug.md` focused for immediate editing.
- [ ] `telec bugs create my-bug` from CLI creates `todos/my-bug/bug.md` + `state.yaml`.
- [ ] `telec bugs create` with no slug prints usage and exits non-zero.
- [ ] Invalid slug is rejected with a clear error (both TUI and CLI).
- [ ] Duplicate slug is rejected with a clear error (both TUI and CLI).
- [ ] `make lint` passes.
- [ ] Existing tests pass.

## Constraints

- Depends on `bug-delivery-service` for `create_bug_skeleton()` and `templates/todos/bug.md`.
- Must integrate with the existing `BINDINGS` list and action pattern in `PreparationView`.
- Bug modal should be visually consistent with the existing `CreateTodoModal`.
- The `telec bugs` command surface must coexist with `report` and `list` subcommands from `bug-delivery-service`.

## Risks

- If `bug-delivery-service` changes the `create_bug_skeleton()` signature, this code must adapt. Mitigated by the dependency ordering.
