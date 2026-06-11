---
description: 'Directed acyclic graph of `after` edges between todo entries; cycle detection at the workflow boundary refuses bad mutations before persistence; unmet dependencies block dispatch during prepare/work slug resolution.'
visibility: 'public'
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
2. **Gate dispatch by readiness.** The prepare and work orchestrators consult the graph when resolving the next runnable slug. Each candidate's `after` list is evaluated against the lane it is entering: the prepare lane waits for parent `PREPARED`, while the work lane waits for parent delivery.

Dependency mutations land via `telec todo update <slug> --after <dep>...`, which converges on the workflow service's set-deps capability after existence validation and cycle detection. The public `set-deps` verb is retired. To clear all dependencies, pass `--after ""`; omitting `--after` leaves deps untouched.

<!-- planned:task-lane -->
For kind=`task`, dependency edges and task datetime are mutually exclusive execution gates. A task may use `after` dependencies to wait for delivered parents, or `datetime` to wait for a clock instant, but not both. The create/update boundary refuses any live state that would persist both a non-empty `after` set and a datetime.
<!-- /planned:task-lane -->


### Phase-specific gates (two gates, both directions)

A dependency is **phase-specific**: a single `after` edge projects into two distinct gates keyed to the dependent's lane, and each clears at a different milestone of the parent.

- **Prepare gate** — a candidate entering the **prepare** lane is blocked until every `after` parent has reached `PREPARED` (its design is frozen). The prepare lane reads the parent's frozen artifacts, so the parent's design freeze — not its delivery — is the unblock condition.
- **Work gate** — a candidate entering the **work/build** lane is blocked until every `after` parent is `delivered` (merged to `main`). The work lane builds on the parent's merged code, so delivery is the unblock condition.

`PREPARED` is a durable freeze, not a decaying signal: reaching it clears the prepare gate and does not un-clear. A later parent re-derivation does not reopen the prepare gate; it surfaces on the dependent as upstream-artifact drift (see `@spec/feature/workflow/drift-detection`) and routes the dependent to re-review. Drift propagates the signal; it does not author the change.

Both gates apply in **both dispatch directions**:

1. **Create-time dispatch** — when a todo is created (`workflow.todo.created`), the lifecycle router consults the dependency graph before auto-dispatching. A dep-blocked child is not auto-dispatched (see `@spec/feature/workflow/todo-creation`).
2. **Resolution-time dispatch** — when the prepare/work orchestrators resolve the next runnable slug, the same phase-specific gate skips dep-blocked candidates.

The prepared-set used by the prepare gate, like the delivered-set used by the work gate, is computed with holder roll-up: a holder dependency is satisfied for the prepare gate when every direct child has reached `PREPARED`, mirroring `effective_delivered_slugs_for_dependencies` for the delivered-set.


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
Given an empty dependency graph
When the operator runs "telec todo update feature-a --after feature-b --after feature-c"
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

```
Given the operator runs "telec todo update alpha --after """
When the workflow service writes the dependency leg
Then all existing edges for that slug are removed
And the workflow service reports that dependencies were cleared for "alpha"
```


### Use cases

#### UC-WDG1: Prepare gate waits for parent PREPARED

```gherkin
Given entries [parent, child] with edge {child: [parent]} and parent at lifecycle_phase=plan_drafting (not yet PREPARED)
When the prepare orchestrator resolves the next prepare-runnable slug
Then "child" is skipped because the prepare gate requires "parent" to be PREPARED
And the resolver reports the candidate as dependency-blocked for the prepare lane
```

#### UC-WDG2: PREPARED clears only the prepare gate

```gherkin
Given entries [parent, child] with edge {child: [parent]} and parent at lifecycle_phase=PREPARED but not delivered
When the prepare orchestrator resolves the next prepare-runnable slug
Then "child" is prepare-runnable because the prepare gate is cleared by PREPARED
And the same "child" is still WORK-blocked until "parent" is delivered
```

#### UC-WDG3: Create-time dispatch honors the prepare gate

```gherkin
Given a child created with "telec todo create child --kind change --after parent" while parent is not PREPARED
When the lifecycle router consumes workflow.todo.created for "child"
Then the router consults the dependency graph and finds the prepare gate unsatisfied
And the router does not auto-dispatch /next-prepare for "child"
And "child" waits until "parent" reaches PREPARED, which triggers auto-continue (see @spec/feature/workflow/prepare-state-machine)
```

<!-- planned:task-lane -->
#### UC-WDG4: Task datetime excludes dependency edges

```gherkin
Given a task has a non-empty `after` dependency set
When a caller updates the same task with `--datetime <iso-instant>` without clearing dependencies
Then workflow refuses the mutation before persistence
And the task keeps its previous dependency set and datetime state
```

```gherkin
Given a task has a datetime
When a caller updates the same task with a non-empty `--after` set without clearing datetime
Then workflow refuses the mutation before persistence
And the task keeps its previous dependency set and datetime state
```

```gherkin
Given a task has a datetime
When the caller clears datetime and sets `--after parent` in the same accepted mutation
Then workflow persists the dependency edge and leaves datetime empty
```
<!-- /planned:task-lane -->


### Cross-context references

- `workflow` orchestration internals — prepare and work pickup consult the dependency graph against the delivered set to decide what is runnable.

## Known caveats

- Cycle detection runs BEFORE persistence at the workflow boundary, so durable state is never observed in a cyclic state.
- The graph is per-project: one todo list, one dependency graph, one project root. There is no cross-project dependency.
- Dependency satisfaction is lane-specific. `delivered` clears the work gate; `PREPARED` clears the prepare gate. `icebox`, `pending`, and lifecycle phases before `PREPARED` leave the prepare gate closed. Removing a dep edge is the only way to unblock a candidate whose dep is iceboxed.
- `set-deps` is a full replacement: passing no `--after` clears all edges for the slug; there is no incremental add/remove surface. To merge edges, the caller must read the current edges first and submit the union.
- `telec todo update --after` carries the same full-replacement semantics. To clear all edges, pass `--after ""`; omitting `--after` leaves deps untouched. There is no incremental add/remove dependency surface; callers that want to merge edges must read the current set and submit the union.
- At slug retirement, the workflow context scrubs the deleted slug out of other entries' `depends_on` lists — without that, removing a slug could leave dangling deps that block its dependents forever.


- The gate is **phase-specific**. The **work** gate is cleared only by `delivered`. The **prepare** gate is cleared by the parent reaching `PREPARED` — a non-`delivered` lifecycle phase. `icebox`, and any lifecycle phase before `PREPARED`, leave the prepare gate closed.
- Both gates are enforced at **create-time** (lifecycle router, before auto-dispatch) and at **resolution-time** (orchestrator next-runnable resolution). Before this change the router applied no dependency gate at create-time, which let a dep-blocked child auto-dispatch in parallel with its parent.
