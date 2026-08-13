---
description: 'Frozen-but-recoverable state for todos that are not being actively pursued; iceboxed rows are hidden from default list output and ignored by active dispatch until unfrozen.'
visibility: 'public'
---

# Todo Icebox — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The icebox is the parking lot for todos the project does not want to lose but does not want to act on. Freezing a todo flips its status from `active` to `icebox`; its associated state, artifacts, dependency edges, and timestamps are preserved untouched.

A todo may also be created directly in the icebox with `telec todo create … --icebox`, which writes the roadmap entry with `status="icebox"` from the outset — the same parked band, reached without a transient active state and without spawning a session.

Iceboxed entries are excluded from the default `telec todo list` view and from prepare/work candidate search. They neither get dispatched nor satisfy another todo's dependencies. Unfreezing flips the entry back to `active`, returning it to the default list and to the orchestrators' attention without losing history.

The icebox is distinct from soft removal. Freeze preserves the live entry in a recoverable inactive band; remove marks the entry `removed`, hides it from every default resolver, scrubs live dependency edges, and starts the retention window.

## Canonical fields

### Use cases

```
Given an active todo "deferred-feature"
When the operator runs "telec todo freeze deferred-feature"
Then the entry's status changes to "icebox"
And the entry is no longer returned by the default "telec todo list"
And the entry's state, artifacts, and dependency edges are preserved unchanged
```

```
Given an operator knows an idea is parked and runs "telec todo create parked-idea '<content>' --kind change --icebox"
When the workflow service creates the entry
Then the roadmap entry's status is "icebox"
And the entry is absent from the default "telec todo list"
And no session is dispatched for the slug
And unfreezing it later returns it to active and resumes its lane
```

```
Given an iceboxed todo "deferred-feature"
When the operator runs "telec todo list --include-icebox"
Then "deferred-feature" appears in the icebox section
And its rendered status is "icebox"
```

```
Given an iceboxed todo "deferred-feature"
When the operator runs "telec todo list --icebox-only"
Then only entries with status="icebox" are shown
And active and delivered entries are hidden regardless of other flags
```

```
Given an iceboxed todo "deferred-feature"
When the operator runs "telec todo unfreeze deferred-feature"
Then the entry's status flips back to "active"
And it reappears in the default "telec todo list" view
And its dependency edges and artifacts remain intact
And the next prepare/work pickup may consider it again
```

```
Given an active todo "alpha" depending on iceboxed todo "beta"
When the work orchestrator searches for the next runnable slug
Then "alpha" is skipped because "beta" is not delivered
And the resolver reports the candidate as dependency-blocked
And the iceboxed "beta" is not itself dispatched, regardless of its own readiness
```

```
Given the operator runs "telec todo freeze missing-slug" for a slug that is not in the todo list
When the workflow service resolves the active entry
Then no entry is mutated
And the command reports "Slug not found in todo list: missing-slug" and exits non-zero
```

<!-- planned:fix-after-dep-on-icebox-todo-undetected -->

#### UC-ICE-FRZ-WARN: Freezing a todo with open dependents warns naming the dependents it strands

Freezing never cascades and is never refused for graph reasons — freezing a subtree is an explicit per-todo act. The freeze surface warns, naming each open (active) dependent that points at the newly frozen todo, so the operator knows which open work is now blocked behind the freezer.

```gherkin
Given an active todo "dependent" with an "after" edge on active todo "parent"
When the operator runs "telec todo freeze parent"
Then "parent" moves to icebox
And the response carries a warning naming "dependent" as an open dependent that will not dispatch while "parent" is frozen
And freezing a todo with no open dependents produces no warning
```

#### UC-ICE-THAW-WARN: Unfreezing a todo with still-frozen dependencies warns naming them

Thaw order is the operator's to sequence; the tool does not refuse an out-of-order thaw. The unfreeze surface warns, naming each dependency still in the icebox, so root-first thawing is visible rather than enforced.

```gherkin
Given iceboxed todos "parent" and "child" where "child" has an "after" edge on "parent"
When the operator runs "telec todo unfreeze child" while "parent" remains iceboxed
Then "child" returns to active
And the response carries a warning naming "parent" as a still-frozen dependency that blocks dispatch of "child"
And unfreezing a todo whose dependencies are all live or delivered produces no warning
```

<!-- /planned:fix-after-dep-on-icebox-todo-undetected -->

### Cross-context references

- `workflow` orchestration internals — prepare/work resolvers consume the active todo-list projection; iceboxed entries are out of band because they are filtered upstream.

## Known caveats

- Freezing keeps the todo recoverable and live-entry-addressable; it is fundamentally different from soft removal.
- Iceboxed entries retain artifacts, lifecycle state, and dependency edges. The edges remain in the dependency graph but never gate dispatch while the source slug is iceboxed.
- An active entry that depends on an iceboxed entry is blocked because iceboxed is not delivered. To unblock, the operator unfreezes the dependency, delivers it, or rewrites the dependency edge with `telec todo set-deps`.
- Slug uniqueness still applies across `active` and `icebox`: an iceboxed slug cannot be re-created until it is unfrozen, removed, or delivered.
