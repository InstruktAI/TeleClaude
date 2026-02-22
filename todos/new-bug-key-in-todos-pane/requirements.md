# Requirements: new-bug-key-in-todos-pane

## Goal

Add a `b` keybinding to the TUI todos pane that creates a bug todo and opens `bug.md` for editing, plus a `telec bugs create <slug>` CLI command as the lightweight counterpart to `telec todo create`. Also fix the dependency tree rendering bug and add `roadmap.yaml` as a first-class tree entry.

## Problem

There is no quick way to create a bug report from the TUI. The existing `n` key creates a full todo (with `input.md`, `requirements.md`, `implementation-plan.md`, etc.), which is overkill for a bug. Bugs need only `bug.md` + `state.yaml`. The user must currently use the CLI to create bugs, breaking TUI flow.

## In Scope

1. **TUI keybinding** — `b` key in the PreparationView (todos pane) opens a CreateBugModal, calls `create_bug_skeleton()`, and opens `bug.md` in the editor.
2. **CLI command** — `telec bugs create <slug>` scaffolds a bug todo with `bug.md` + `state.yaml` (no orchestrator dispatch, no worktree). Analogous to `telec todo create`.
3. **Modal reuse or adaptation** — Use or adapt `CreateTodoModal` for bug slug entry.
4. **Roadmap entry in tree** — Surface `roadmap.yaml` as the very first entry in the todo preparation pane's tree node, before any slug entries. Selecting it follows the same file-open routine as any other file in the tree.
5. **Unscoped file viewer** — The file viewer/opener in the preparation pane must not be scoped to a specific slug directory. Any file node in the tree view is a potential file to open. The open-file routine must work uniformly regardless of where the file lives.
6. **Fix dependency tree rendering** — The TUI must build the visual tree from the `after` dependency graph, not from list position. `roadmap.yaml` ordering is irrelevant to tree structure — the user can reorder items freely and the tree must still render correct parent-child relationships. The `after` field is the sole source of truth for nesting. Items with no `after` (or unresolvable `after`) are roots. `assemble_roadmap()` returns a flat list — the rendering layer is responsible for building the tree from the `after` graph on each item. No reliance on list ordering, no reordering hacks.

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
- [ ] `roadmap.yaml` appears as the first entry in the PreparationView tree, before any todo slug nodes.
- [ ] Selecting `roadmap.yaml` opens it via the same routine as any other file in the tree.
- [ ] The file viewer is not scoped to slug directories — any file node in the tree can be opened uniformly.
- [ ] Tree connectors reflect actual `after` dependencies, not list position. An item with `after: [X]` is visually nested under X, not under whatever item happens to precede it.
- [ ] Items with no `after` (or unresolvable `after`) render at root depth with no misleading nesting.
- [ ] `make lint` passes.
- [ ] Existing tests pass.

## Constraints

- Depends on `bug-delivery-service` for `create_bug_skeleton()` and `templates/todos/bug.md`.
- Must integrate with the existing `BINDINGS` list and action pattern in `PreparationView`.
- Bug modal should be visually consistent with the existing `CreateTodoModal`.
- The `telec bugs` command surface must coexist with `report` and `list` subcommands from `bug-delivery-service`.

## Risks

- If `bug-delivery-service` changes the `create_bug_skeleton()` signature, this code must adapt. Mitigated by the dependency ordering.
