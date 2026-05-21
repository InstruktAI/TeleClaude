---
id: 'project/spec/feature/workflow/todo-split'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Split a Todo into child Todos persisted under the parent''s group, convert the parent roadmap row into a stateless holder with frozen input, and route subsequent prepare/work requests against the holder to a runnable direct child.'
---

# Todo Split — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo split <slug> --into <child> [--into <child2> ...]` (and the matching `POST /todos/split` route) decomposes one Todo into N child Todos in a single transaction. Each child is added to the Roadmap with its `group_slug` pointing at the parent and is bootstrapped with a fresh default state. From that point on, the parent roadmap row functions as a **holder** - structural grouping only, not an implementation Todo. The holder MUST NOT have a `todo_state` row. Its artifact set is stripped to the original `input` artifact only, and that retained input is frozen: it can be read and cloned into children, but not edited or removed through artifact-write/remove paths. Any prepare or work request against the holder slug is re-routed by the slug-resolution layer to a runnable direct child. If the parent's `input` artifact is present at split time, it is cloned to every child as starter material; no other artifacts, approvals, verdicts, or lifecycle stamps are inherited.

## Canonical fields

### Use cases

```
Given a Todo "parent-slug" exists with an "input" artifact
When `telec todo split parent-slug --into child-a --into child-b` is run
Then a single transaction adds "child-a" and "child-b" to the roadmap with group_slug="parent-slug"
And each child's state is bootstrapped via default_state() with lifecycle_phase="draft"
And the parent's input artifact is cloned to each child under updated_by="api.todo.split.clone_input"
And the parent has no todo_state row
And the parent artifact set contains only its original input artifact
And the retained parent input artifact is frozen against later writes and removal
And the daemon notifies "todo_updated"
```

```
Given child-a and child-b are in the roadmap with group_slug="parent-slug"
When a caller asks the slug-resolution layer for the parent's runnable children
Then `resolve_holder_children_db` returns the roadmap children with matching group_slug, in roadmap order
And `resolve_runnable_holder_children_db` filters to children that are still active, not delivered, and ready for the requested mode (PREPARE or WORK)
```

```
Given a roadmap row is a holder because at least one live child group-references its slug
When any caller attempts to write todo_state for that holder slug
Then the write is refused
And stale holder todo_state rows are purged at holder transition and database bootstrap
```

```
Given a roadmap row is a holder and still has an input artifact
When any caller attempts to write or remove an artifact on that holder slug
Then the write or removal is refused
And stale non-input holder artifacts and versions are purged at holder transition and database bootstrap
```

```
Given a holder roadmap row whose direct children all have unsatisfied dependencies
When `resolve_next_work_queue_db` scans the roadmap and reaches the holder
Then the holder is skipped (no runnable child) with reason DEPS_UNSATISFIED
And the scan continues to the next roadmap entry rather than stalling on the holder
```

```
Given `telec todo split parent-slug --into child-a` is invoked but "child-a" already exists in todos.db
When `POST /todos/split` enters the children loop
Then the request fails with HTTP 409 and detail "Child todo 'child-a' already exists"
And the surrounding transaction rolls back, so no partial children are persisted and no parent holder cleanup is committed
```

```
Given `telec todo split missing-parent --into child-a` is invoked
When `POST /todos/split` checks the roadmap
Then no live roadmap row exists for "missing-parent"
And the request fails with HTTP 404 and detail "Parent todo 'missing-parent' not found"
And no child rows are written
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:279-323` — `_handle_todo_split` argv adapter; enforces a single parent slug and at least one `--into` child, then POSTs to `/todos/split`
- `teleclaude/api/todo_routes.py` — `POST /todos/split` validates the parent roadmap row, validates each child does not already exist, adds child roadmap entries with `group_slug=<parent>`, bootstraps child state via `default_state()`, and clones the parent's frozen `input` artifact to each child
- `teleclaude/core/todos_db/_roadmap.py` — `add_to_roadmap(..., group_slug=<parent>)` purges holder `todo_state` and non-input artifacts/version rows for the parent while preserving the parent input artifact
- `teleclaude/core/todos_db/_state.py` — `read_state` hides holder state and `write_state` / `write_state_sync` refuse holder slugs
- `teleclaude/core/todos_db/_artifacts.py` — holder artifacts are frozen; write/delete paths refuse holder slugs, while read paths can still read the retained input
- `teleclaude/core/next_machine/_types.py:173-175` — `default_state()` returns a fresh `TodoState` (children always start at `lifecycle_phase="draft"`; no inheritance from the parent)
- `teleclaude/core/next_machine/slug_resolution.py` — `resolve_holder_children_db` derives children from the roadmap `group_slug` index; **never** infers parentage from slug prefixes, `roadmap.after`, or holder state
- `teleclaude/core/next_machine/slug_resolution.py:215-282` — `resolve_runnable_holder_children_db` reduces holder children to the runnable subset for the requested `HolderResolutionMode` (PREPARE or WORK), tagging the outcome with a `HolderResolutionReason`
- `teleclaude/core/next_machine/slug_resolution.py:285-331` — `resolve_next_work_queue_db` walks the roadmap and skips holders whose children are blocked, so a stuck container cannot starve later ready Todos

### Cross-context references

- `operations` — `POST /todos/split` is a synchronous write; unlike `remove` it does not go through the receipt-backed operations queue.

## Known caveats

- A roadmap row is recognised as a holder **only** when at least one live child row group-references it through `roadmap.group_slug`. There is no `kind="holder"` enum value, no holder lifecycle phase, no holder `todo_state`, and slug-prefix or `roadmap.after` relationships are never used to infer parentage.
- Children are bootstrapped with `default_state()` (`lifecycle_phase="draft"`). No prepare-lane progress, approvals, verdicts, drift stamps, or skip stamps are inherited from the parent — only the `input` artifact is cloned, and only if present at split time.
- The split transaction is all-or-nothing: a single conflict on any child slug (HTTP 409) aborts the whole batch, leaving the parent as it was before the transaction.
- The retained holder input is immutable after the row becomes a holder. Later edits to the holder's input do not exist as a valid operation; child seeding happens exactly once, at split time.
- Holder status is a projection from child rows. A holder dependency is satisfied when every direct child has delivered; this is computed for dependency gating without mutating the holder row.
- A holder with no runnable direct child (all delivered, all blocked, or all not-yet-ready) is **skipped** by `resolve_next_work_queue_db`, ensuring it cannot starve later ready work in the roadmap.
