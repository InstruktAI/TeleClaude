---
description: "Split a Todo into child Todos persisted under the parent's group, each inheriting the parent's canonical kind and entering at that kind's lifecycle entry phase; split stays non-auto-routing and its output instructs the splitting agent to tend each child; the parent becomes a stateless holder with frozen input that re-routes subsequent prepare/work requests to a runnable direct child."
visibility: 'public'
---

# Todo Split — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo split <slug> --into <child> [--into <child2> ...]` decomposes one Todo into N child Todos atomically. Each child is added to the todo list with its `group_slug` pointing at the parent and is bootstrapped with a fresh default state whose `kind` is **inherited from the parent**: the child's kind is the parent's canonical kind (`canonical_kind(parent.kind)`), and the child enters at that kind's lifecycle entry phase. Decomposition starts from the parent's current classification — it is not an automatic re-classification event. A `change` parent yields `change` children that draft a plan directly, a `feature` parent yields `feature` children that author a PRD, and so on.

Split is **non-auto-routing**: creating children through split emits only the mutation/cache/UI signal (`todo_updated`), never `workflow.todo.created`. The lifecycle router auto-dispatch path keys off `workflow.todo.created`, so split does not start `/analyze-todo-input`, `/next-prepare`, or `/next-work` as a side effect. The splitting agent owns child-state correctness: the split command's output **ends with an explicit instruction** to inspect each child, decide whether the inherited parent kind is still right, and correct any child whose kind should differ using `telec todo update <child> --kind <new_kind>` (e.g. a `change` that legitimately decomposes into a `change` plus a `bug`).

From the split forward, the parent entry functions as a **holder** — structural grouping only, not an implementation Todo. The holder MUST NOT carry lifecycle state. Its artifact set is stripped to the original `input` artifact only, and that retained input is frozen: it can be read and cloned into children, but not edited or removed through artifact-write/remove paths. Any prepare or work request against the holder slug is re-routed by the slug-resolution layer to a runnable direct child. If the parent's `input` artifact is present at split time, it is cloned to every child as starter material; beyond the inherited kind (and its entry phase), no approvals, verdicts, drift stamps, skip stamps, or non-input artifacts are inherited.

## Canonical fields

### Use cases

#### UC-WTS1: Change parent children inherit change and cloned input

```
Given a Todo "parent-slug" of kind "change" exists with an "input" artifact
When the operator runs "telec todo split parent-slug --into child-a --into child-b"
Then "child-a" and "child-b" are added to the todo list atomically with group_slug="parent-slug"
And each child inherits the parent's canonical kind "change"
And each child enters the "change" lifecycle entry phase (plan drafting, no PRD) — not the feature PRD lane
And the parent's input artifact is cloned to each child
And the parent has no lifecycle state
And the parent artifact set contains only its original input artifact
And the retained parent input artifact is frozen against later writes and removal
```

#### UC-WTS2: Child kind and entry phase follow parent canonical kind

```
Given a Todo "parent-slug" exists whose kind is one of "feature", "change", "bug", or "task"
When the operator splits it into children
Then each child's kind equals canonical_kind(parent.kind)
And each child enters that kind's lifecycle entry phase: feature → PRD drafting, change → plan drafting, bug → diagnose, task → prepared
And no approvals, review verdicts, drift stamps, or skip stamps cross from parent to child
```

#### UC-WTS3: Unresolvable parent kind fails before child writes

```
Given a holder candidate "parent-slug" has no resolvable kind (missing or unknown)
When the operator attempts to split it
Then the request is refused with a clear error naming the unresolvable parent kind
And no child entries are written
And the parent is left unchanged
```

#### UC-WTS4: Split stays non-auto-routing

```
Given an operator splits "parent-slug" into children
When the split transaction commits
Then the workflow service emits only its mutation/cache signal for the change
And it does NOT emit "workflow.todo.created" for any child
And the lifecycle router does not auto-start "/analyze-todo-input", "/next-prepare", or "/next-work" for the children
And the children wait for the splitting agent (or a later explicit prepare/work request) to advance them
```

#### UC-WTS5: Split output instructs agent to tend child kinds

```
Given an operator runs "telec todo split parent-slug --into child-a --into child-b"
When the command completes successfully
Then it prints the split summary
And its output ends with an explicit instruction to the splitting agent to inspect each child's kind/state
And that instruction names "telec todo update <child> --kind <new_kind>" as the way to correct a child whose kind should differ from the inherited parent kind
```

#### UC-WTS6: Runnable children resolve from direct group rows

```
Given child-a and child-b are in the todo list with group_slug="parent-slug"
When a caller asks for the parent's runnable children
Then the workflow service returns the todo-list children with matching group_slug, in todo-list order
And filters to children that are still active, not delivered, and ready for the requested mode (prepare or work)
```

#### UC-WTS7: Holder lifecycle state is refused and purged

```
Given an entry is a holder because at least one live child group-references its slug
When any caller attempts to write lifecycle state for that holder slug
Then the write is refused
And stale holder lifecycle state is purged at holder transition and bootstrap
```

#### UC-WTS8: Holder artifacts are frozen to retained input

```
Given an entry is a holder and still has an input artifact
When any caller attempts to write or remove an artifact on that holder slug
Then the write or removal is refused
And stale non-input holder artifacts and versions are purged at holder transition and bootstrap
```

#### UC-WTS9: Dependency-blocked holder does not stall work selection

```
Given a holder entry whose direct children all have unsatisfied dependencies
When the work resolver scans the todo list and reaches the holder
Then the holder is skipped (no runnable child) as dependency-blocked
And the scan continues to the next todo entry rather than stalling on the holder
```

#### UC-WTS10: Existing child conflict rolls back split

```
Given the operator runs "telec todo split parent-slug --into child-a" but "child-a" already exists
When the workflow service enters the children loop
Then the request fails with a conflict error citing the existing child slug
And the surrounding transaction rolls back, so no partial children are persisted and no parent holder cleanup is committed
```

#### UC-WTS11: Missing parent is refused

```
Given the operator runs "telec todo split missing-parent --into child-a"
When the workflow service checks the todo list
Then no live entry exists for "missing-parent"
And the request fails with a not-found error
And no child entries are written
```

#### UC-WTS12: A group member cannot depend on its own holder

```
Given child-a is in the todo list with group_slug="parent-slug" (so "parent-slug" is a holder)
When a caller runs "telec todo update child-a --after parent-slug"
Then the request is refused with a conflict error stating that group membership and an "after" dependency on the same holder are mutually exclusive
And child-a's existing dependencies are left unchanged
And the same refusal applies when the requested dependency is any ancestor holder of child-a reached by walking group_slug transitively
And a dependency from a non-member todo onto the holder is still allowed (UC-WTS9 group-as-unit gating is unaffected)
```

## Known caveats

- An entry is recognised as a holder **only** when at least one live child entry group-references it. There is no `kind="holder"` enum value, no holder lifecycle phase, no holder lifecycle state, and slug-prefix or `after` relationships are never used to infer parentage.
- Children inherit the parent's canonical kind and enter at that kind's lifecycle entry phase (`feature` → `prd_drafting`, `change` → `plan_drafting`, `bug` → `diagnose`, `task` → `prepared`); `feature`/`change` children keep the default stored `lifecycle_phase="draft"` and derive their entry phase from the inherited kind, while `bug`/`task` children carry the explicit entry phase. Beyond the inherited kind, no prepare-lane progress, approvals, verdicts, drift stamps, or skip stamps are inherited from the parent — only the `input` artifact is cloned, and only if present at split time.
- The inherited parent kind is a **starting default, not a final classification.** Decomposition can legitimately change a child's kind (a `change` may split into a `change` plus a `bug`). The splitting agent owns final correctness and re-kinds a child with `telec todo update <child> --kind <new_kind>` after inspecting it; the split command output exists to prompt exactly that tending step.
- Split is intentionally **non-auto-routing**: it never emits `workflow.todo.created`, so no orchestrator (`/analyze-todo-input`, `/next-prepare`, `/next-work`) auto-starts for split children. This keeps decomposition under the splitting agent's control and is the reason the command output instructs the agent to tend children rather than relying on automatic classification.
- A parent whose kind cannot be resolved to a canonical kind cannot be split: the split is refused rather than defaulting the children to `feature`. This fail-closed guard exists because kind inheritance is the contract; silently substituting a default would re-introduce the mis-classification it prevents.
- The split transaction is all-or-nothing: a single conflict on any child slug aborts the whole batch, leaving the parent as it was before the transaction.
- The retained holder input is immutable after the entry becomes a holder. Later edits to the holder's input do not exist as a valid operation; child seeding happens exactly once, at split time.
- Holder status is a projection from child entries. A holder dependency is satisfied when every direct child has delivered; this is computed for dependency gating without mutating the holder entry.
- A holder with no runnable direct child (all delivered, all blocked, or all not-yet-ready) is **skipped** by the work resolver, ensuring it cannot starve later ready work in the todo list.
- Group membership (`group_slug`) and an `after` dependency on the same holder are **mutually exclusive** for a holder and its own members. A member already belongs to its holder through grouping; letting it also declare an `after` dependency on that holder produces an unsatisfiable item, because the holder is treated as delivered/prepared only once every member reaches that state — the member would gate on a target gated on itself. The dependency-write path rejects any requested dependency that is the slug's own `group_slug` or any ancestor holder reached by walking `group_slug` transitively. This is enforced in addition to ordinary `roadmap_deps` cycle detection, which alone cannot see the holder→member edge because that relationship lives in `group_slug`, not in `roadmap_deps`. A dependency from a non-member todo onto the holder (depending on the group as a unit) stays valid.
