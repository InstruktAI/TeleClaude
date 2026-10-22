---
description: 'Frozen-but-recoverable state for todos that are not being actively pursued; iceboxed rows are hidden from default list output and ignored by active dispatch until unfrozen.'
visibility: 'public'
---

# Todo Icebox — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

The icebox is the parking lot for todos the project does not want to lose but does not want to act on. Freezing a todo flips its status from `active` to `icebox`; its associated state, artifacts, dependency edges, and timestamps are preserved untouched.

A todo may also be created directly in the icebox with `telec todo create … --icebox`, which writes the roadmap entry with `status="icebox"` from the outset — the same parked band, reached without a transient active state and without spawning a session.

Iceboxed entries are excluded from the default `telec todo list` view and from prepare/work candidate search. They neither get dispatched nor satisfy another todo's dependencies. Unfreezing flips the entry back to `active`, returning it to the default list and to the orchestrators' attention without losing history.

The icebox is distinct from soft removal. Freeze preserves the live entry in a recoverable inactive band; remove marks the entry `removed`, hides it from every default resolver, scrubs live dependency edges, and starts the retention window.

## Canonical fields

### Use cases

#### UC-ICE-FRZ: Park active work for later

```
Given an active todo "deferred-feature" has state, artifacts, and dependency edges
When the operator runs "telec todo freeze deferred-feature"
Then the todo is parked in the icebox and no longer appears in the default list or active dispatch
And its state, artifacts, and dependency edges remain intact for later resumption
```

```gherkin
Given no todo in the project has slug "missing-slug"
When the operator runs "telec todo freeze missing-slug"
Then no todo is changed
And the command reports "Slug not found in todo list: missing-slug" and exits non-zero
```

#### UC-ICE-LIST: Find parked work in the todo list

```gherkin
Scenario: Include parked work with the project list
  Given the project has active, delivered, and iceboxed todos
  When the operator lists todos with `--include-icebox`
  Then iceboxed todos appear in the icebox section with status `icebox`

Scenario: Limit the project list to parked work
  Given the project has active, delivered, and iceboxed todos
  When the operator lists todos with `--icebox-only`
  Then only iceboxed todos appear and each is shown with status `icebox`
```

#### UC-ICE-THAW: Resume parked work

```gherkin
Given an iceboxed todo "deferred-feature" has state, artifacts, and dependency edges
When the operator unfreezes it
Then it returns to the default list and its normal lane can consider it again
And its dependency edges, artifacts, and history remain intact
```

#### UC-ICE-FRZ-WARN: An operator can see which open work a freeze will block

Freezing never cascades and is never refused for graph reasons — freezing a subtree is an explicit per-todo act. The freeze surface warns, naming each open (active) dependent that points at the newly frozen todo, so the operator knows which open work is now blocked behind the freezer. It gives no warning when there are no open dependents.

```gherkin
Scenario: See work that a freeze will strand
  Given open todos depend on a todo the operator intends to freeze
  When the operator freezes that todo
  Then the operator can see each open active dependent that freezing will block from dispatch
  And no warning appears when there are no open dependents
```

#### UC-ICE-THAW-WARN: An operator can see why resumed work remains blocked

Thaw order is the operator's to sequence; unfreezing succeeds regardless of thaw order, and the tool does not refuse an out-of-order thaw. The unfreeze surface warns, naming each dependency still in the icebox, so root-first thawing is visible rather than enforced. It gives no warning when every prerequisite is active or delivered.

```gherkin
Scenario: Resume work with a frozen prerequisite
  Given a todo has one or more prerequisites that are still frozen
  When the operator unfreezes it
  Then the operator can see each prerequisite that is still iceboxed and blocks dispatch
  And no warning appears when every prerequisite is active or delivered
```

### Cross-context references

- `workflow` orchestration internals — prepare/work resolvers consume the active todo-list projection; iceboxed entries are out of band because they are filtered upstream.

## Known caveats

- Freezing keeps the todo recoverable and live-entry-addressable; it is fundamentally different from soft removal.
- Iceboxed entries retain artifacts, lifecycle state, and dependency edges. The edges remain in the dependency graph but never gate dispatch while the source slug is iceboxed.
- An active entry that depends on an iceboxed entry is blocked because iceboxed is not delivered. To unblock, the operator unfreezes the dependency, delivers it, or rewrites the dependency edge with `telec todo set-deps`.
- Slug uniqueness still applies across `active` and `icebox`: an iceboxed slug cannot be re-created until it is unfrozen, removed, or delivered.
