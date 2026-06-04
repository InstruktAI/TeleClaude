---
id: 'project/spec/feature/workflow/todo-management'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
description: 'Per-project ordered todo list stored in todos.db and managed through todo-scoped commands; sectioned list output, derived active ordering, soft removal, and delivery transitions.'
---

# Todo Management — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Todo management is the operator-facing surface for the per-project ordered todo list. Internal roadmap rows remain the storage source of truth for "what is being worked on, what is next, and what is done," but the surface is managed through the `telec todo` namespace rather than a separate roadmap command family.

Each row is a todo entry tied to a Todo by durable row id and active slug. Creation goes through `telec todo create`, which requires substantive content and writes the storage row, canonical state, input artifact, and artifact-version row together. The default read path is `telec todo list`, which renders sectioned dependency trees for active todos and optionally includes delivered or iceboxed sections. Active order is derived from workflow state: Ready entries appear before In-prep entries, and each band sorts by its persisted timestamps and slug. Manual position, move, and add-before/add-after ordering are not part of this surface.

Removal and delivery are lifecycle transitions on the same aggregate. `telec todo remove` soft-removes a todo while retaining its state, artifacts, version history, and row-id-addressed recovery metadata for the retention window. `telec todo deliver` stamps delivery metadata, moves the todo to delivered history, and runs delivered-slug cleanup.

## Canonical fields

### Use cases

```
Given a project with no todo entries
When the operator runs "telec todo list"
Then the command prints "Todo list is empty." and exits successfully
And "telec todo list --json" emits "{}"
```

```
Given an empty todo list
When the operator runs "telec todo create new-feature 'do the thing' --kind feature --description 'do the thing'"
Then a live roadmap row is inserted with status="active"
And a stable UUID is assigned as the row id
And the slug is rejected if it is not lowercase kebab-case
And the input artifact and its first version are written with the supplied content
```

```
Given active todos that contain parent/child groupings and dependency edges
When the operator runs "telec todo list --json"
Then the command emits a JSON object keyed by visible section
And each section contains dependency-tree rows with nested children
And an empty visible section is omitted from the JSON object
```

```
Given active todos [ready-a, prep-b]
And ready-a has all after dependencies delivered and a ready lifecycle phase
And prep-b is still before the ready lifecycle phase
When the operator runs "telec todo list"
Then ready-a appears in the Ready band before prep-b
And no manual position value is read or written to produce that order
```

```
Given an active todo "shipped-thing" with implementation work complete
When the operator runs "telec todo deliver shipped-thing --commit abc1234"
Then the entry's status flips to "delivered"
And delivered_at is set to the current UTC timestamp
And delivered_commit is set to "abc1234"
And the todo's lifecycle state phase is rewritten to "delivered"
And cleanup_delivered_slug runs to tear down any leftover worktree/branch
And the entry no longer appears in the default "telec todo list" view
And "telec todo list --include-delivered" can show the delivered history
And a new "shipped-thing" slug may be created because the unique-slug index excludes delivered rows
```

```
Given an active todo "feature-y" that is no longer wanted
When the operator runs "telec todo remove feature-y"
Then the roadmap row is marked status="removed" with removed_at set
And its outgoing dependencies are snapshotted into removed_deps before live dependency edges are scrubbed
And its state, artifacts, and artifact versions remain available to the row-id-addressed recovery primitive during the retention window
And the todo disappears from every default read path
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py` — `list`, `create`, `remove`, `freeze`, `unfreeze`, and `deliver` command handlers.
- `teleclaude/cli/telec/surface.py` — `telec todo` command definitions and help surface.
- `teleclaude/core/todos_db/_roadmap.py` — roadmap row persistence, status transitions, soft removal, delivery stamping, and ready timestamp helpers.
- `teleclaude/core/roadmap.py` — sectioned roadmap assembly, Ready/In-prep band classification, and delivered/icebox sorting.
- `teleclaude/core/roadmap_tree.py` — dependency-tree construction for sectioned list output.
- `teleclaude/core/todos_db/schema.sql` — `roadmap` table, row identity, status fields, `ready_since`, and active-slug uniqueness.

### Cross-context references

- `integration` — `cleanup_delivered_slug` retires the delivered slug's worktree/branch/workspace after delivery bookkeeping.
- `agent_runtime` / daemon cache — roadmap mutations fire `_on_mutation("todo_updated"|"todo_removed")`, invalidating daemon cache and faning out to TUI/frontend subscribers.

## Known caveats

- Active ordering is derived, not manually curated. There is no persisted `position` field and no command for manual reorder.
- `telec todo create` is not a thin roadmap-row insert; substantive content is required and the input artifact/version are part of the create transaction.
- Slug uniqueness is enforced only across live rows (`active` and `icebox`). Delivered and removed retained rows may share a slug with a fresh live row because they are addressed by durable row identity.
- `telec todo remove` is soft and retained during the recovery window; hard purge is routine maintenance and row-id-only.
- The ordered todo list is per-project: one `.teleclaude/todos.db` per project root resolved via `resolve_state_root`. There is no global todo list.
