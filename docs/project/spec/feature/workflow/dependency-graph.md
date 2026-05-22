---
id: 'project/spec/feature/workflow/dependency-graph'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Directed acyclic graph of `after` edges between todo roadmap entries; cycle detection at the API boundary refuses bad mutations before persistence; unmet dependencies block dispatch during prepare/work slug resolution.'
---

# Dependency Graph — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Roadmap entries can declare ordering constraints via `after` edges: "A is `after: [B, C]`" means A cannot start work until B and C are delivered. Workflow models this as a directed acyclic graph (DAG) per project, persisted as `(slug, depends_on)` rows in `roadmap_deps`. The graph is per-project; one project's roadmap has no influence on another.

The graph has two responsibilities:

1. **Refuse cycles at the boundary.** Mutations that would introduce a cycle are rejected before they reach the database. The `/todos/set-deps` HTTP endpoint runs cycle detection as part of request validation; the CLI handlers route through the same persistence path. Cycle detection is pure DFS over an in-memory snapshot of the current graph plus the proposed edge set — no DB writes happen on the failure path.
2. **Gate dispatch by readiness.** The prepare and work orchestrators consult the graph when resolving the next runnable slug. A candidate whose `after` list contains any slug that is not in `delivered_slugs` is skipped. Pending, in-progress, and iceboxed dependencies all leave the candidate blocked; only delivery clears the gate.

Mutations land via `telec todo set-deps` and the `POST /todos/set-deps` API endpoint, both of which converge on `TodosDb.set_deps` after passing validation.

## Canonical fields

### Use cases

```
Given an empty dependency graph
When the operator runs "telec todo set-deps feature-a --after feature-b --after feature-c"
Then both "feature-b" and "feature-c" are validated as existing roadmap slugs
And cycle detection runs over the current graph plus the proposed edges
And the deps are persisted via TodosDb.set_deps, replacing any prior edges for "feature-a"
```

```
Given a graph where "alpha" depends on "beta" and "beta" depends on "gamma"
When a client posts {"slug": "gamma", "after": ["alpha"]} to /todos/set-deps
Then detect_circular_dependency returns the cycle path [gamma -> alpha -> beta -> gamma]
And the API responds with HTTP 409 and a body citing the cycle path joined by " -> "
And no row is written to roadmap_deps
```

```
Given a request to /todos/set-deps with {"slug": "alpha", "after": ["alpha"]}
When the route validates the payload
Then the self-edge is rejected with HTTP 400 "slug 'alpha' cannot depend on itself"
And no further validation or write happens
```

```
Given a request to /todos/set-deps where "alpha" exists but "ghost" is not in the roadmap
When the route validates the deps
Then the missing slug check fires before cycle detection
And the API responds with HTTP 404 "dependency 'ghost' not found in roadmap"
And no row is written
```

```
Given roadmap entries [a, b, c] with edges {b: [a], c: [b]} and only "a" delivered
When the work orchestrator searches for the next runnable slug
Then "b" is selected because its only dependency "a" is delivered
And "c" is skipped because "b" is not yet delivered
And the resolver returns the WorkQueueResolution with reason=READY for "b"
```

```
Given an entry "c" depending on iceboxed entry "b"
When the work orchestrator evaluates "c"
Then "b" is not in delivered_slugs (icebox is not delivery)
And "c" is reported as dependency-blocked
And the resolver continues searching the rest of the roadmap
```

```
Given a request to /todos/set-deps with after=[] for an existing slug
When the route writes the deps
Then all existing edges for that slug are deleted from roadmap_deps
And the API responds with "dependencies cleared for '<slug>'"
```

### Implementation pointers (v1)

- `teleclaude/core/next_machine/dep_graph.py:9` — `detect_circular_dependency(deps, slug, new_deps)` pure DFS implementation; no DB or filesystem access
- `teleclaude/api/todo_routes.py:211` — `POST /todos/set-deps` validates slug format, target existence, self-edge, runs cycle detection, then calls `set_deps`
- `teleclaude/api/todo_routes.py:249` — `load_deps()` + `detect_circular_dependency` boundary check before write
- `teleclaude/cli/tool_commands/todo.py` — `handle_todo_set_deps` CLI entrypoint used by `telec todo set-deps`
- `teleclaude/core/todos_db/_roadmap.py:329` — `set_deps` replaces edges in a single transaction (delete all, insert new)
- `teleclaude/core/todos_db/_roadmap.py:358` — `load_deps` returns `{slug: [depends_on, ...]}` for graph snapshots
- `teleclaude/core/todos_db/_roadmap.py:367` — `clean_dep_references` removes a slug from all `depends_on` lists, used during slug retirement
- `teleclaude/core/todos_db/schema.sql:52` — `roadmap_deps(slug, depends_on)` table with composite primary key
- `teleclaude/core/next_machine/slug_resolution.py:164` — `_deps_satisfied(dependencies, delivered, slug)` is the canonical gating predicate
- `teleclaude/core/next_machine/slug_resolution.py:285` — `resolve_next_work_queue_db` skips candidates whose deps are unsatisfied and reports `DEPS_UNSATISFIED` when nothing is runnable

### Cross-context references

- `workflow` orchestration internals — prepare and work pickup (`next_machine.slug_resolution`) consult `load_deps()` against `delivered_slugs()` to decide what is runnable
- `agent_runtime` / daemon cache — `set_deps` triggers `_on_mutation("todo_updated")`, propagating the change to cached roadmap views

## Known caveats

- `dep_graph.py` is pure logic — no DB access. Persistence lives in `TodosDb.set_deps`; the API route is the only place that pairs cycle detection with persistence.
- Cycle detection runs BEFORE persistence at the API boundary, so the database is never observed in a cyclic state. CLI invocation uses the same todo dependency surface rather than a separate roadmap-specific command.
- The graph is per-project: one roadmap, one `roadmap_deps` table, one `.teleclaude/todos.db`. There is no cross-project dependency.
- Only `delivered` clears a dependency. `icebox`, `pending`, and `in_progress` all leave the gate closed. Removing a dep edge (or marking the parent delivered) is the only way to unblock a candidate whose dep is iceboxed.
- `set_deps` is a full replacement: passing `after=[]` clears all edges for the slug; there is no incremental add/remove API. To merge edges, the caller must `load_deps` first and submit the union.
- `clean_dep_references` is invoked at slug retirement to scrub a deleted slug out of other entries' `depends_on` lists — without it, removing a slug could leave dangling deps that block its dependents forever.
