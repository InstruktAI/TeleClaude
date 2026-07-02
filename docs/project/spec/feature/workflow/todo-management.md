---
description: 'Per-project ordered todo list managed through todo-scoped commands; sectioned list output, derived active ordering, soft removal, and delivery transitions.'
visibility: 'public'
---

# Todo Management — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Todo management is the operator-facing surface for the per-project ordered todo list. The list is the workflow context's projection of "what is being worked on, what is next, and what is done," managed through the `telec todo` namespace.

Each entry is tied to a Todo by durable identity and active slug. Creation goes through `telec todo create`, which requires substantive content and writes the entry, canonical state, and input artifact atomically. The default read path is `telec todo list`, which renders sectioned dependency trees for active todos and optionally includes delivered or iceboxed sections. Active order is derived from workflow state: Ready entries appear before In-prep entries, and each band sorts by its persisted timestamps and slug. Manual position, move, and add-before/add-after ordering are not part of this surface.

Visual hierarchy within a section resolves each node to its **nearest enclosing structural container**: the innermost in-group `after`-dependency visible in the section, otherwise its group holder, otherwise the section root. Group membership and `after` edges compose rather than compete — an `after`-dependency on a sibling within the same group nests the dependent under that sibling, while an `after` edge crossing into another group orders the roots without re-homing the node out of its own group. Holder status stays group-derived: gaining an `after`-child never makes a node a holder, so a node keeps its own row state while nesting its dependents.

Removal and delivery are lifecycle transitions on the same aggregate. `telec todo remove` soft-removes a todo while retaining its state, artifacts, version history, and identity-addressed recovery metadata for the retention window. `telec todo deliver` stamps delivery metadata, moves the todo to delivered history, and runs delivered-slug cleanup.

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
When the operator runs "telec todo create new-feature 'do the thing' --kind feature"
Then a live todo entry is inserted with status="active"
And a stable durable identity is assigned
And the slug is rejected if it is not lowercase kebab-case
And the input artifact and its first version are written with the supplied content
```

```
Given active todos that contain parent/child groupings and dependency edges
When the operator runs "telec todo list --json"
Then the command emits a JSON object keyed by visible section
And each section contains dependency-tree entries with nested children
And an empty visible section is omitted from the JSON object
```

#### UC-WM6: Roadmap projection skips stateless non-holder rows

```gherkin
Given an active roadmap row has no todo_state row
And that row is not referenced by any live child's group_slug
When the workflow projects the todo list
Then the stateless non-holder row is omitted from the projection
And dependent todos that still have valid state remain visible
```

#### UC-WM7: Roadmap projection keeps stateless group holders

```gherkin
Given an active roadmap row has no todo_state row
And at least one live child references that row through group_slug
When the workflow projects the todo list
Then the row remains visible as a structural holder
And the holder has no own kind, lifecycle, build, or review state
And its visible status derives from its leaf children
```

#### UC-WM8: Show resolves stateless group holders

```gherkin
Given an active roadmap row has no todo_state row
And at least one live child references that row through group_slug
And the holder has an input artifact
When the workflow assembles the show payload for that entry
Then the service returns a structural holder projection instead of not-found
And the projection includes only holder structure: slug, holder stage, roadmap facts with direct group children, retained holder artifacts, and optional artifact content
And the projection omits Todo lifecycle fields: current, state, approvals, reviews, drift, work, audit, events, next_commands, previous, and next
```

#### UC-WM9: Intra-group dependency nests under its dependency

```gherkin
Given a group holder "epic" with grouped children "base" and "follow-on"
And "follow-on" declares an after-dependency on "base"
When the workflow projects the todo list
Then "follow-on" nests under "base" instead of beside it under "epic"
And "base" retains its own row state and is not made a holder by the after-child
```

#### UC-WM10: Cross-group dependency does not re-home the dependent

```gherkin
Given a grouped child "left-child" under holder "left-epic"
And "left-child" declares an after-dependency on "right-anchor" under a different holder "right-epic"
When the workflow projects the todo list
Then "left-child" stays nested under "left-epic"
And the cross-group dependency orders the section roots without moving "left-child" out of its group
```

#### UC-WM1: Show reads the caller's project

```
Given the operator is inside a project worktree
When the operator runs "telec todo show feature-x"
Then the CLI sends the invocation working directory to the workflow service
And the service resolves the show payload from that project rather than the daemon default directory
```

#### UC-WM2: Artifact listing reads the caller's project

```
Given the operator is inside a project worktree
When the operator runs "telec todo artifacts list feature-x"
Then the CLI sends the invocation working directory to the workflow service
And the service lists artifacts from that project rather than the daemon default directory
```

#### UC-WM3: Artifact body reads the caller's project

```
Given the operator is inside a project worktree
When the operator runs "telec todo artifacts read feature-x prd"
Then the CLI sends the invocation working directory to the workflow service
And the service reads the artifact from that project rather than the daemon default directory
```

#### UC-WM4: Slug reactivation targets the caller's project

```
Given the operator is inside a project worktree
When the operator runs "telec todo reactivate feature-x"
Then the CLI sends the invocation working directory to the workflow service
And the service resolves the removed slug from that project rather than the daemon default directory
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
And the todo's lifecycle phase is rewritten to "delivered"
And delivered-slug cleanup runs to tear down any leftover worktree/branch
And the entry no longer appears in the default "telec todo list" view
And "telec todo list --include-delivered" can show the delivered history
And a new "shipped-thing" slug may be created because the unique-slug index excludes delivered entries
```

```
Given an active todo "feature-y" that is no longer wanted
When the operator runs "telec todo remove feature-y"
Then the entry is marked status="removed" with removed_at set
And its outgoing dependencies are snapshotted before live dependency edges are scrubbed
And its state, artifacts, and artifact versions remain available to the identity-addressed recovery primitive during the retention window
And the todo disappears from every default read path
```

#### UC-WM5: Unified todo update facade

```
Given an active todo whose build has not started
When the operator runs "telec todo update my-todo --slug new-slug"
Then the slug leg delegates to the workflow rename engine and applies the
same atomic slug cascade as the rename contract
```

```
Given an active todo
When the operator runs "telec todo update my-todo --after parent-a --after parent-b"
Then the dependency leg validates every parent slug, rejects cycles, and
replaces the todo's dependency set with the supplied parents
```

```gherkin
Given an active task todo
When the operator runs "telec todo update my-task --schedule 2026-06-12T09:00:00Z"
Then the update leg validates the schedule (a one-shot ISO-8601 instant or a recurring rule)
And persists it as the task execution eligibility
And emits `workflow.todo.updated` so the lifecycle runner re-evaluates the task
```

```gherkin
Given an active task todo has a schedule
When the operator runs 'telec todo update my-task --schedule ""'
Then the update leg clears the schedule
And keeps the rest of the todo state unchanged
```

```
Given an active todo
When the operator runs "telec todo update my-todo --after parent-a,parent-b"
Then the CSV value is expanded and both parents are validated and stored
equivalent to supplying them as two separate --after flags
```

```
Given an active todo with existing dependencies
When the operator runs 'telec todo update my-todo --after ""'
Then the dependency leg sends an empty replacement set
And all existing dependencies for my-todo are removed
```

```
Given an active todo whose build has not started
When the operator runs "telec todo update my-todo --kind bug"
Then the kind leg handles any orphaned kind-specific artifacts explicitly
And lifecycle_phase is re-routed to the target kind's entry phase
```

```
Given an active todo whose build has started
When the operator runs "telec todo update my-todo --slug new-slug"
Or the operator runs "telec todo update my-todo --kind task"
Then the workflow service refuses the mutation before changing state
But dependency-only updates through --after remain allowed
```

#### UC-WM11: Rename self-excludes the caller's own claiming session

```gherkin
Given an active todo whose runner claim is held by the caller's own session
When the caller runs "telec todo update my-todo --slug new-slug"
Then the rename engine excludes the caller's own session from the block-check
And the rename proceeds, applying the same atomic slug cascade as the rename contract
```

#### UC-WM12: Rename proceeds when no other session or operation is bound

```gherkin
Given an active todo bound to no open session and no non-terminal operation
When the operator runs "telec todo update my-todo --slug new-slug"
Then the block-check finds no other binding
And the rename proceeds, applying the same atomic slug cascade as the rename contract
```

#### UC-WM13: Rename is refused when a different open session is bound

```gherkin
Given an active todo whose runner claim is held by a different open session
When the operator runs "telec todo update my-todo --slug new-slug"
Then the rename is refused before any surface changes, naming the bound session
```

#### UC-WM14: Rename is refused when a foreign non-terminal operation is bound

```gherkin
Given an active todo bound by a non-terminal operation other than the caller's own
When the operator runs "telec todo update my-todo --slug new-slug"
Then the rename is refused before any surface changes, naming the bound operation
```

### Cross-context references

- `integration` — delivered-slug cleanup retires the delivered slug's worktree/branch/workspace after delivery bookkeeping.

## Known caveats

- Active ordering is derived, not manually curated. There is no persisted `position` field and no command for manual reorder.
- `telec todo create` is not a thin todo-entry insert; substantive content is required and the input artifact and its first version are part of the create transaction.
- Slug uniqueness is enforced only across live entries (`active` and `icebox`). Delivered and removed retained entries may share a slug with a fresh live entry because they are addressed by durable identity.
- `telec todo remove` is soft and retained during the recovery window; hard purge is routine maintenance and identity-only.
- The ordered todo list is per-project: one project root, one todo list. There is no global todo list.
