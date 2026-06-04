---
id: 'project/spec/feature/workflow/dependency-graph'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Directed acyclic graph of `after` edges between todo entries; cycle detection at the workflow boundary refuses bad mutations before persistence; unmet dependencies block dispatch during prepare/work slug resolution.'
---

# Dependency Graph — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Todo entries can declare ordering constraints via `after` edges: "A is `after: [B, C]`" means A cannot start work until B and C are delivered. The workflow context models this as a directed acyclic graph (DAG) per project. The graph is per-project; one project's todo list has no influence on another.

The graph has two responsibilities:

1. **Refuse cycles at the boundary.** Mutations that would introduce a cycle are rejected before they reach durable storage. Cycle detection is pure depth-first traversal over an in-memory snapshot of the current graph plus the proposed edge set — no state is mutated on the failure path.
2. **Gate dispatch by readiness.** The prepare and work orchestrators consult the graph when resolving the next runnable slug. A candidate whose `after` list contains any slug that is not delivered is skipped. Pending, in-progress, and iceboxed dependencies all leave the candidate blocked; only delivery clears the gate.

Mutations land via `telec todo set-deps`, which converges on the workflow service's set-deps capability after passing validation.

## Canonical fields

### Use cases

```
Given an empty dependency graph
When the operator runs "telec todo set-deps feature-a --after feature-b --after feature-c"
Then both "feature-b" and "feature-c" are validated as existing todo slugs
And cycle detection runs over the current graph plus the proposed edges
And the deps are persisted, replacing any prior edges for "feature-a"
```

```
Given a graph where "alpha" depends on "beta" and "beta" depends on "gamma"
When the operator runs "telec todo set-deps gamma --after alpha"
Then cycle detection identifies the cycle path [gamma -> alpha -> beta -> gamma]
And the workflow service refuses the mutation with a cycle-conflict error citing the cycle path
And no edge is persisted
```

```
Given the operator runs "telec todo set-deps alpha --after alpha"
When the workflow service validates the request
Then the self-edge is rejected as invalid
And no further validation or write happens
```

```
Given the operator runs "telec todo set-deps alpha --after ghost" where "ghost" is not in the todo list
When the workflow service validates the deps
Then the missing-slug check fires before cycle detection
And the workflow service refuses the mutation with a not-found error
And no edge is persisted
```

```
Given todo entries [a, b, c] with edges {b: [a], c: [b]} and only "a" delivered
When the work orchestrator searches for the next runnable slug
Then "b" is selected because its only dependency "a" is delivered
And "c" is skipped because "b" is not yet delivered
And the resolver returns the next runnable candidate as "b"
```

```
Given an entry "c" depending on iceboxed entry "b"
When the work orchestrator evaluates "c"
Then "b" is not in the delivered set (icebox is not delivery)
And "c" is reported as dependency-blocked
And the resolver continues searching the rest of the todo list
```

```
Given the operator runs "telec todo set-deps alpha" with no --after flag
When the workflow service writes the deps
Then all existing edges for that slug are removed
And the workflow service reports "dependencies cleared for 'alpha'"
```

### Cross-context references

- `workflow` orchestration internals — prepare and work pickup consult the dependency graph against the delivered set to decide what is runnable.

## Known caveats

- Cycle detection runs BEFORE persistence at the workflow boundary, so durable state is never observed in a cyclic state.
- The graph is per-project: one todo list, one dependency graph, one project root. There is no cross-project dependency.
- Only `delivered` clears a dependency. `icebox`, `pending`, and `in_progress` all leave the gate closed. Removing a dep edge (or marking the parent delivered) is the only way to unblock a candidate whose dep is iceboxed.
- `set-deps` is a full replacement: passing no `--after` clears all edges for the slug; there is no incremental add/remove surface. To merge edges, the caller must read the current edges first and submit the union.
- At slug retirement, the workflow context scrubs the deleted slug out of other entries' `depends_on` lists — without that, removing a slug could leave dangling deps that block its dependents forever.
