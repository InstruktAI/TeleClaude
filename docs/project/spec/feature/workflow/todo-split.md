---
id: 'project/spec/feature/workflow/todo-split'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Split a Todo into child Todos persisted under the parent''s group, set the parent''s breakdown so it is treated as a container, and route subsequent prepare/work requests against the container to a runnable direct child.'
---

# Todo Split — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo split <slug> --into <child> [--into <child2> ...]` (and the matching `POST /todos/split` route) decomposes one Todo into N child Todos in a single transaction. Each child is added to the Roadmap with its `group_slug` pointing at the parent and is bootstrapped with a fresh default state; the parent's `breakdown` aggregate records `assessed=True` and the full list of child slugs. From that point on, the parent functions as a **holder** — a container Todo whose role is to group its children — and any prepare or work request against the parent's slug is re-routed by the slug-resolution layer to a runnable direct child. If the parent's `input` artifact is present at split time, it is cloned to every child as starter material; no other artifacts, approvals, verdicts, or lifecycle stamps are inherited.

## Canonical fields

### Use cases

```
Given a Todo "parent-slug" exists with an "input" artifact
When `telec todo split parent-slug --into child-a --into child-b` is run
Then a single transaction adds "child-a" and "child-b" to the roadmap with group_slug="parent-slug"
And each child's state is bootstrapped via default_state() with lifecycle_phase="draft"
And the parent's input artifact is cloned to each child under updated_by="api.todo.split.clone_input"
And the parent's breakdown is persisted as {assessed: true, todos: ["child-a", "child-b"]} via the StateWriter boundary
And the daemon notifies "todo_updated"
```

```
Given a parent Todo whose breakdown.todos lists ["child-a", "child-b"]
And both children are in the roadmap with group_slug="parent-slug"
When a caller asks the slug-resolution layer for the parent's runnable children
Then `resolve_holder_children_db` returns the union of roadmap children (group_slug match) and breakdown.todos, in roadmap-order then breakdown-order
And `resolve_runnable_holder_children_db` filters to children that are still active, not delivered, and ready for the requested mode (PREPARE or WORK)
```

```
Given a holder Todo whose direct children all have unsatisfied dependencies
When `resolve_next_work_queue_db` scans the roadmap and reaches the holder
Then the holder is skipped (no runnable child) with reason DEPS_UNSATISFIED
And the scan continues to the next roadmap entry rather than stalling on the holder
```

```
Given `telec todo split parent-slug --into child-a` is invoked but "child-a" already exists in todos.db
When `POST /todos/split` enters the children loop
Then the request fails with HTTP 409 and detail "Child todo 'child-a' already exists"
And the surrounding transaction rolls back, so no partial children are persisted and the parent's breakdown is unchanged
```

```
Given `telec todo split missing-parent --into child-a` is invoked
When `POST /todos/split` reads the parent state
Then `read_state` returns None
And the request fails with HTTP 404 and detail "Parent todo 'missing-parent' not found"
And no child rows are written
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:353-407` — `_handle_todo_split` argv adapter; enforces a single parent slug and at least one `--into` child, then POSTs to `/todos/split`
- `teleclaude/api/todo_routes.py:571-621` — `POST /todos/split` reads the parent, validates each child does not already exist, adds child roadmap entries with `group_slug=<parent>`, bootstraps child state via `default_state()`, clones the parent's `input` artifact to each child, and commits the parent's `BreakdownState(assessed=True, todos=children)` through `StateWriter`
- `teleclaude/types/todos.py:58-63` — `BreakdownState` aggregate (`assessed: bool`, `todos: list[str]`) — the field that marks a Todo as a container
- `teleclaude/core/next_machine/_types.py:173-175` — `default_state()` returns a fresh `TodoState` (children always start at `lifecycle_phase="draft"`; no inheritance from the parent)
- `teleclaude/core/next_machine/slug_resolution.py:189-212` — `resolve_holder_children_db` derives children from the roadmap `group_slug` index unioned with `state.breakdown.todos`; **never** infers parentage from slug prefixes
- `teleclaude/core/next_machine/slug_resolution.py:215-282` — `resolve_runnable_holder_children_db` reduces holder children to the runnable subset for the requested `HolderResolutionMode` (PREPARE or WORK), tagging the outcome with a `HolderResolutionReason`
- `teleclaude/core/next_machine/slug_resolution.py:285-331` — `resolve_next_work_queue_db` walks the roadmap and skips holders whose children are blocked, so a stuck container cannot starve later ready Todos

### Cross-context references

- `operations` — `POST /todos/split` is a synchronous write; unlike `remove` it does not go through the receipt-backed operations queue.

## Known caveats

- A Todo is recognised as a holder **only** through `roadmap.group_slug` + `state.breakdown.todos`. There is no `kind="holder"` enum value; `state.kind` is unchanged by split, and slug-prefix or `roadmap.after` relationships are never used to infer parentage.
- Children are bootstrapped with `default_state()` (`lifecycle_phase="draft"`). No prepare-lane progress, approvals, verdicts, drift stamps, or skip stamps are inherited from the parent — only the `input` artifact is cloned, and only if present at split time.
- The split transaction is all-or-nothing: a single conflict on any child slug (HTTP 409) aborts the whole batch, leaving the parent's `breakdown` untouched.
- Later refinements on the parent (new artifacts, approvals, edits to `input`) do not auto-propagate to existing children; the clone happens exactly once, at split time.
- A holder is itself a Todo with state. Its `lifecycle_phase` reflects its container role and is not advanced by child progress; the holder's own buildable phases are effectively bypassed because prepare/work requests against it are redirected to a runnable direct child.
- A holder with no runnable direct child (all delivered, all blocked, or all not-yet-ready) is **skipped** by `resolve_next_work_queue_db`, ensuring it cannot starve later ready work in the roadmap.
