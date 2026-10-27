---
description: 'Directed acyclic graph of `after` edges between todo entries; cycle detection at the workflow boundary refuses bad mutations before persistence; unmet dependencies block dispatch during prepare/work slug resolution.'
visibility: 'public'
---

# Dependency Graph — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

Todo entries can declare ordering constraints via `after` edges: "A is `after: [B, C]`" means A cannot start work until B and C are delivered. The workflow context models this as a directed acyclic graph (DAG) per project. The graph is per-project; one project's todo list has no influence on another.

The graph has two responsibilities:

1. **Refuse cycles at the boundary.** Mutations that would introduce a cycle are rejected before they reach durable storage. A cycle refusal identifies the cycle path and persists no proposed edge. Cycle detection is pure depth-first traversal over an in-memory snapshot of the current graph plus the proposed edge set — no state is mutated on the failure path.
2. **Gate dispatch by readiness.** The prepare and work orchestrators consult the graph when resolving the next runnable slug. Each candidate's `after` list is evaluated against the lane it is entering: the prepare lane waits for parent `PREPARED`, while the work lane waits for parent delivery.

Dependency mutations land via `telec todo update <slug> --after <dep>...`, which converges on the workflow service's set-deps capability after existence validation and cycle detection. The public `set-deps` verb is retired. To clear all dependencies, pass `--after ""`; omitting `--after` leaves deps untouched.

Group membership and dependencies cannot make a todo depend on its own holder or an ancestor holder. A group update that would create that overlap is refused, including when it also adds the dependency in the same request; a todo outside the group may still depend on its holder.

For kind=`task`, dependency edges and a task `schedule` are mutually exclusive execution gates. A task may use `after` dependencies to wait for delivered parents, or a `schedule` (a one-shot instant or a recurring rule) to wait for a clock instant, but not both. The create/update boundary refuses any live state that would persist both a non-empty `after` set and a `schedule`.

### Phase-specific gates (two gates, both directions)

A dependency is **phase-specific**: a single `after` edge projects into two distinct gates keyed to the dependent's lane, and each clears at a different milestone of the parent.

- **Prepare gate** — a candidate entering the **prepare** lane is blocked until every `after` parent has reached `PREPARED` (its design is frozen). The prepare lane reads the parent's frozen artifacts, so the parent's design freeze — not its delivery — is the unblock condition.
- **Work gate** — a candidate entering the **work/build** lane is blocked until every `after` parent is `delivered` (merged to `main`). The work lane builds on the parent's merged code, so delivery is the unblock condition.

For a `kind=task` parent, **both** gates key on delivery. A task's `PREPARED` phase records only that its `task-plan` is drafted and authorized; a task produces its deliverable when it **runs**, not when its plan freezes. A dependent's prepare lane has nothing to read from a task parent until the task delivers, so a `kind=task` parent clears the prepare gate only when `delivered` — never via `PREPARED`. The `PREPARED`-clears-prepare rule above applies to SDLC kinds (`feature` / `change` / `bug`) only.

`PREPARED` is a durable freeze, not a decaying signal: reaching it clears the prepare gate and does not un-clear. A later parent re-derivation does not reopen the prepare gate; it surfaces on the dependent as dependency-artifact drift (see `@spec/feature/workflow/drift-detection`) and routes the dependent to re-review. Drift propagates the signal; it does not author the change.

An `after` edge is **gate-only**: it is dispatch-blocking ordering metadata consumed by the prepare and work gates, and it is never a drift surface. Mutating the `after` set (adding or removing an edge) or a dependency crossing the freeze/unfreeze boundary changes what is dispatchable, not whether any of the dependent's prepared artifacts are stale — there is nothing to re-derive. Ordering is enforced solely by the dispatch gates above; drift detection tracks no dependency-graph class.

Both gates apply in **both dispatch directions**:

1. **Create-time dispatch** — when a todo is created (the todo-created event), the lifecycle router consults the dependency graph before auto-dispatching. A dep-blocked child is not auto-dispatched (see `@spec/feature/workflow/todo-creation`).
2. **Resolution-time dispatch** — when the prepare/work orchestrators resolve the next runnable slug, the same phase-specific gate skips dep-blocked candidates. An unsatisfied candidate does not stop the search; resolution continues to later candidates.

The prepared-set used by the prepare gate, like the delivered-set used by the work gate, is computed with holder roll-up: a holder dependency is satisfied for the prepare gate when every direct child has reached `PREPARED`, mirroring `effective_delivered_slugs_for_dependencies` for the delivered-set.

## Canonical fields

### Use cases

#### UC-WDG10: An operator sets prerequisites for work

```gherkin
Scenario: Wait for selected prerequisites before work
  Given active todos "feature-a", "feature-b", and "feature-c"
  When the operator sets "feature-b" and "feature-c" as prerequisites for "feature-a" through the todo update surface
  Then "feature-a" waits for both prerequisites to be delivered before it enters work
```

#### UC-WDG11: An operator clears a todo's prerequisites

```gherkin
Scenario: Stop waiting for cleared prerequisites
  Given active todo "alpha" is waiting for prerequisite todos
  When the operator clears its prerequisites through the todo update surface
  Then "alpha" no longer waits for those prerequisites
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

#### UC-WDG3: Create-time dispatch honors the prepare gate

```gherkin
Given a child created with "telec todo create child --kind change --after parent" while parent is not PREPARED
When the lifecycle router consumes the todo-created event for "child"
Then the router consults the dependency graph and finds the prepare gate unsatisfied
And the router does not auto-dispatch sdlc/procedure/lifecycle/prepare/overview for "child"
And "child" waits until "parent" reaches PREPARED, which triggers auto-continue (see @spec/feature/workflow/prepare-state-machine)
```

#### UC-WDG4: Task schedule excludes dependency edges

#### UC-WDG5: A group member cannot depend on its own holder

#### UC-WDG9: A todo cannot join a group it depends on

#### UC-WDG6: A task parent clears the prepare gate only on delivery

#### UC-WDG7: A cross-band dependency mutation succeeds with a warning naming the frozen dependency

An `after` edge from an open (active) todo onto an iceboxed todo is legitimate — whether the edge is correct filing is the filer's judgment, never tool validation. The mutation boundary's duty is visibility: it admits the edge and warns, naming each iceboxed dependency, so the caller knows the open todo will not dispatch until the dependency thaws. A todo created into or already in the icebox produces no warning; its dependencies have meaning only at thaw.

```gherkin
Scenario: Adding an active todo's iceboxed prerequisite warns without refusing
  Given an active todo "open-child" and an iceboxed todo "frozen-parent"
  When a caller runs "telec todo update open-child --after frozen-parent"
  Then the mutation succeeds and the edge is persisted
  And the response carries a warning naming "frozen-parent" as an iceboxed dependency that blocks dispatch of "open-child"

Scenario: An iceboxed todo receives no warning about its prerequisites
  Given an iceboxed todo "frozen-parent"
  When a caller creates an active todo with "telec todo create open-child '<content>' --kind change --after frozen-parent"
  Then the todo is created and the edge is persisted
  And the outcome delivered to the filing session carries a warning naming "frozen-parent" as an iceboxed dependency
  But the same creation with "--icebox" produces no warning
```

#### UC-WDG8: Kickback re-closes the prepare gate until the parent is prepared again

```gherkin
Given entries [parent, child] with edge {child: [parent]}
And parent previously reached PREPARED or a work phase
When parent is kicked back so its implementation-plan review is cleared-by-substantive-drift
And that review no longer approves the current implementation-plan digest
Then parent no longer counts as dependency-prepared
And "child" remains prepare-blocked until parent reaches PREPARED again
And the gate does not self-resolve merely because parent still has a PRD approval or a stored work-phase pointer
```

### Cross-context references

- `workflow` orchestration internals — prepare and work pickup consult the dependency graph against the delivered set to decide what is runnable.

## Known caveats

- Cycle detection runs BEFORE persistence at the workflow boundary, so durable state is never observed in a cyclic state.
- The graph is per-project: one todo list, one dependency graph, one project root. There is no cross-project dependency.
- Dependency satisfaction is lane-specific. `delivered` clears the work gate; `PREPARED` clears the prepare gate. `icebox`, `pending`, and lifecycle phases before `PREPARED` leave the prepare gate closed. Removing a dep edge is the only way to unblock a candidate whose dep is iceboxed.

- A `kind=task` parent is the exception to the prepare-gate rule: it clears the prepare gate only on `delivered`, never on `PREPARED`, because a task's deliverable is a run product (see the phase-specific gates section).

- `telec todo update --after` carries the same full-replacement semantics. To clear all edges, pass `--after ""`; omitting `--after` leaves deps untouched. There is no incremental add/remove dependency surface; callers that want to merge edges must read the current set and submit the union.
- At slug retirement, the workflow context scrubs the deleted slug out of other entries' `depends_on` lists — without that, removing a slug could leave dangling deps that block its dependents forever.

- The gate is **phase-specific**. The **work** gate is cleared only by `delivered`. The **prepare** gate is cleared by the parent reaching `PREPARED` — a non-`delivered` lifecycle phase. `icebox`, and any lifecycle phase before `PREPARED`, leave the prepare gate closed.
- Both gates are enforced at **create-time** (lifecycle router, before auto-dispatch) and at **resolution-time** (orchestrator next-runnable resolution). Before this change the router applied no dependency gate at create-time, which let a dep-blocked child auto-dispatch in parallel with its parent.
