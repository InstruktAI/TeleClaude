---
id: 'project/spec/feature/workflow/roadmap-management'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Per-project roadmap stored in todos.db as the ordered, dependency-aware list of roadmap entries; CRUD via telec roadmap commands; explicit positioning; delivery transitions that capture commit SHA and free slug reuse.'
---

# Roadmap Management — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The roadmap is the ordered, operator-curated list of work for a project — the public face of "what is being worked on, what is next, and what is done." Each row in the roadmap is a Roadmap entry tied 1:1 to a Todo by slug. Workflow stores the roadmap in `.teleclaude/todos.db` (per project); the order is explicit and operator-controlled via positional commands rather than derived from dependencies or timestamps.

CRUD and lifecycle transitions on the roadmap are exposed through the `telec roadmap` command surface: operators add, remove, move, freeze, unfreeze, and deliver entries. Adding requires a kebab-case slug that is unique among the active and icebox entries; delivered entries keep their slugs reserved in history but allow new entries to reuse the same slug, supporting re-launches of a concept. Removing, freezing, and delivering are mutating operations that emit mutation hooks consumed by the daemon's cache and downstream subscribers so that any open frontend or TUI view reflects the change.

The roadmap is the source of truth that the prepare and work orchestrators consult to choose what to run next; this feature owns the data and the operator-facing commands, not the dispatch decisions themselves.

## Canonical fields

### Use cases

```
Given a project with no roadmap entries
When the operator runs "telec roadmap list"
Then the command prints "Roadmap is empty." and exits successfully
And no JSON is emitted unless --json was supplied
```

```
Given an empty roadmap
When the operator runs "telec roadmap add new-feature --description 'do the thing'"
Then a roadmap row is inserted with status="active" at the next position
And a stable UUID is assigned as the row id
And the slug is rejected if it is not lowercase kebab-case
```

```
Given roadmap entries [a, b, c] in that order
When the operator runs "telec roadmap add d --before b"
Then d is inserted at b's position
And b and c are shifted right (positions incremented)
And the resulting order is [a, d, b, c]
```

```
Given the active roadmap contains slug "feature-x"
When the operator runs "telec roadmap add feature-x --description 'updated'"
Then no second row is inserted
And the existing entry's description is updated in place
And the command reports success idempotently
```

```
Given roadmap entries [a, b, c]
When the operator runs "telec roadmap move c --before a"
Then c is repositioned ahead of a
And the resulting order is [c, a, b]
And no automatic reorder occurs from any other source (deps, groups, timestamps)
```

```
Given an active entry "shipped-thing" with implementation work complete
When the operator runs "telec roadmap deliver shipped-thing --commit abc1234"
Then the entry's status flips to "delivered"
And delivered_at is set to the current UTC timestamp
And delivered_commit is set to "abc1234"
And the todo's lifecycle state phase is rewritten to "delivered"
And cleanup_delivered_slug runs to tear down any leftover worktree/branch
And the entry no longer appears in "telec roadmap list" (use --include-delivered or --delivered-only to see it)
And a new "shipped-thing" slug may be added because the unique-slug index excludes delivered rows
```

```
Given an entry "feature-y" that is no longer wanted
When the operator runs "telec roadmap remove feature-y"
Then the row is deleted from the roadmap table
And its dependency edges in roadmap_deps are deleted
And delivered history (rows with status="delivered") is untouched
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/roadmap.py:35` — `_handle_roadmap` dispatcher routing `list|add|remove|move|deps|freeze|unfreeze|migrate-icebox|deliver`
- `teleclaude/cli/telec/handlers/roadmap.py:67` — `_handle_roadmap_show` list rendering (grouped text + `--json`)
- `teleclaude/cli/telec/handlers/roadmap.py:205` — `_handle_roadmap_add` argument parsing and slug validation
- `teleclaude/cli/telec/handlers/roadmap.py:295` — `_handle_roadmap_move` explicit `--before` / `--after` reorder
- `teleclaude/cli/telec/handlers/roadmap.py:476` — `_handle_roadmap_deliver` deliver + cleanup call
- `teleclaude/core/todos_db/_roadmap.py:130` — `add_to_roadmap` insert/update with `before` / `position` resolution
- `teleclaude/core/todos_db/_roadmap.py:249` — `deliver` flips status, stamps `delivered_at` / `delivered_commit`, rewrites state phase
- `teleclaude/core/todos_db/_roadmap.py:380` — `move_in_roadmap` operator-driven repositioning
- `teleclaude/core/todos_db/schema.sql:4` — `roadmap` table (id, slug, position, group_slug, description, status, delivered_at, delivered_commit, children, timestamps)
- `teleclaude/core/todos_db/schema.sql:18` — partial unique index `idx_roadmap_slug_active` enforces slug uniqueness for `active`/`icebox`, allowing reuse after delivery
- `teleclaude/core/roadmap.py:33` — `assemble_roadmap_from_db` projects rows into `TodoDTO` with derived `status` / `lifecycle_phase` for display

### Cross-context references

- `integration` — `cleanup_delivered_slug` (invoked from `_handle_roadmap_deliver`) reaches into the integrator's worktree/branch bookkeeping to retire the delivered slug's workspace
- `agent_runtime` / daemon cache — the `_on_mutation("todo_updated"|"todo_removed")` hook on every roadmap mutation invalidates the daemon's `DaemonCache` and triggers WebSocket fan-out so the TUI / frontend refresh

## Known caveats

- Roadmap ordering is explicit and operator-controlled — there is no auto-sort by dependency, group, or timestamp. `move` and `add --before` are the only ways to change order.
- Slug uniqueness is enforced by a partial index over `status IN ('active','icebox')`. Delivered rows accumulate without conflict, but they are removed from the default `list` view (use `--include-delivered` or `--delivered-only` to inspect history).
- `add` is idempotent: re-adding an existing active/icebox slug updates `group_slug` / `description` on the existing row instead of inserting a duplicate.
- `remove` deletes the roadmap row and its `roadmap_deps` edges but does not delete the underlying `todo_state` or `todo_artifacts` rows — the state remains in the DB until manually pruned.
- `deliver` rewrites the todo's state JSON in-place to set both `phase` and `integration_phase` to `"delivered"` regardless of prior phase, so a manually delivered slug is forced into the delivered terminal state.
- The roadmap is per-project — one `.teleclaude/todos.db` per project root resolved via `resolve_state_root`. There is no global roadmap.
