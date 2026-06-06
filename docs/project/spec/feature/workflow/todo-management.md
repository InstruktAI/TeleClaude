---
id: 'project/spec/feature/workflow/todo-management'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Per-project ordered todo list managed through todo-scoped commands; sectioned list output, derived active ordering, soft removal, and delivery transitions.'
---

# Todo Management — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Todo management is the operator-facing surface for the per-project ordered todo list. The list is the workflow context's projection of "what is being worked on, what is next, and what is done," managed through the `telec todo` namespace.

Each entry is tied to a Todo by durable identity and active slug. Creation goes through `telec todo create`, which requires substantive content and writes the entry, canonical state, and input artifact atomically. The default read path is `telec todo list`, which renders sectioned dependency trees for active todos and optionally includes delivered or iceboxed sections. Active order is derived from workflow state: Ready entries appear before In-prep entries, and each band sorts by its persisted timestamps and slug. Manual position, move, and add-before/add-after ordering are not part of this surface.

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

### Cross-context references

- `integration` — delivered-slug cleanup retires the delivered slug's worktree/branch/workspace after delivery bookkeeping.

## Known caveats

- Active ordering is derived, not manually curated. There is no persisted `position` field and no command for manual reorder.
- `telec todo create` is not a thin todo-entry insert; substantive content is required and the input artifact and its first version are part of the create transaction.
- Slug uniqueness is enforced only across live entries (`active` and `icebox`). Delivered and removed retained entries may share a slug with a fresh live entry because they are addressed by durable identity.
- `telec todo remove` is soft and retained during the recovery window; hard purge is routine maintenance and identity-only.
- The ordered todo list is per-project: one project root, one todo list. There is no global todo list.
