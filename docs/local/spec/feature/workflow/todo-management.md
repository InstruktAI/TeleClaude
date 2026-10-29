---
description: 'Per-project ordered todo list managed through todo-scoped commands; sectioned list output, derived active ordering, soft removal, and delivery transitions.'
visibility: 'public'
---

# Todo Management — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

Todo management is the operator-facing surface for the per-project ordered todo list. The list is the workflow context's projection of "what is being worked on, what is next, and what is done," managed through the `telec todo` namespace.

Each entry is tied to a Todo by durable identity and active slug. Creation goes through `telec todo create`, which requires substantive content and writes the entry, canonical state, and input artifact atomically. The default read path is `telec todo list`, which renders sectioned dependency trees for active todos and optionally includes delivered or iceboxed sections. Active order is derived from workflow state: Ready entries appear before In-prep entries, and each band sorts by its persisted timestamps and slug. Manual position, move, and add-before/add-after ordering are not part of this surface.

Visual hierarchy within an active, icebox, or removed section resolves each node to its **nearest enclosing structural container**: the innermost in-group `after`-dependency visible in the section, otherwise its group holder, otherwise the section root. Group membership and `after` edges compose rather than compete in these sections — an `after`-dependency on a sibling within the same group nests the dependent under that sibling, while an `after` edge crossing into another group orders the roots without re-homing the node out of its own group. A holder is an explicit row status, entered once when the first child is grouped under a parent and never left; a holder is exempt from the todo lifecycle and exists to bind its artifacts as evidence of the split and to label its children wherever they render. Children reference their holder by durable row id, and every surface renders the holder label as context joined from that row — the holder has no row-presence of its own in any band. Gaining an `after`-child never makes a node a holder; a node keeps its own row state while nesting its dependents.

Delivered history is ordered by delivery recency. Group membership supplies the header beneath which a delivered todo appears; dependencies determine neither its nesting nor its order. Children sort newest first, and each group is placed among standalone todos by its newest visible descendant. The holder's own timestamps never determine that placement. Delivery-cutoff filtering applies to each todo independently of group membership, and a group with no visible delivered children contributes no delivered header. Delivered children retain their group context even when other children of that group remain active.

Group membership is set when a todo is created under a parent and can be changed later through the update facade: a live todo moves into a group, into a different group, or out of any group. The move changes only which holder labels the todo and which holder's roll-up counts it; the todo keeps its own lifecycle state, artifacts, and dependencies. Moving into a parent that is not yet a holder makes it one through the same transition group creation uses, and a holder that loses its last live child stays a holder that renders nowhere.

<!-- planned:github-item-acts -->

A todo's title is set or cleared through the same update facade (`telec todo update <slug> --title <text>`, an empty value clearing it). The title is the todo's readable name beside its slug; setting it renames nothing, and the slug stays the todo's identity and handle.

<!-- /planned:github-item-acts -->

Removal and delivery are lifecycle transitions on the same aggregate. `telec todo remove` soft-removes a todo while retaining its state, artifacts, version history, and identity-addressed recovery metadata for the retention window. `telec todo deliver` stamps delivery metadata, moves the todo to delivered history, and runs delivered-slug cleanup.

Lifecycle and artifact-changing actions are addressable by slug or by a todo's durable identity. A slug-addressed action resolves to the live todo that holds the slug. An identity-addressed action acts on exactly the identified todo and never resolves to another todo that shares its slug: on a live todo it performs the same action a slug-addressed request performs, and on a removed or delivered todo it is refused without effect, with a refusal that names the todo's state and the way forward — reactivation for a removed todo; a delivered todo's record is read-only. Reactivating a removed todo is the one change a retained todo accepts, and its retained content stays readable.

`telec todo show` reports who holds an active todo's lifecycle claim in a `claim` block. The block names the holding session, the computer running it and that session's role, or states that no session holds the todo. The holder it names is the one the holder rule of `local/projects/teleclaude/spec/feature/workflow/driver-admission` finds at that moment, judged where that rule judges it, on whichever computer `todo show` runs, and the block carries what that rule names with the holder. When the holder cannot be decided — the daemon or the project's active computer cannot be reached, the project names no active computer, or no decision arrives within the read's wait — the block says the holder is undetermined and why, and never reports the todo as free. The state block's `active_runner` keeps its own meaning as the recorded driver link, and can differ from the holder: it can name a session that no longer holds the todo, or be empty while a session holds it. Iceboxed, delivered and removed todos and the structural projection of a holder carry no `claim` block.

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
And the row's status is not holder
When the workflow projects the todo list
Then the stateless row is omitted from the projection with an integrity warning
And dependent todos that still have valid state remain visible
```

#### UC-WM7: Roadmap projection renders a holder as context over its live children

```gherkin
Given a row has status holder
And at least one live child references that row by group id
When the workflow projects the todo list
Then the children nest under the holder's label
And the holder contributes no own kind, lifecycle, build, or review state
And its visible status derives from its leaf children
And a holder with no live children appears nowhere in the projection
```

#### UC-WM8: Show resolves a holder with live children as structure only

```gherkin
Given a row has status holder
And at least one live child references that row by group id
And the holder has an input artifact
When the workflow assembles the show payload for that entry
Then the service returns a structural holder projection instead of not-found
And the projection includes only holder structure: slug, holder stage, roadmap facts with direct group children, retained holder artifacts, and optional artifact content
And the projection omits Todo lifecycle fields: current, state, approvals, reviews, drift, work, audit, events, next_commands, previous, and next
And the same request for a holder with no live children resolves as not found
```

#### UC-WM25: A child's show payload carries its holder as context

```gherkin
Given a child references a holder by group id
When the workflow assembles the child's show payload
Then the payload names the holder as the child's group context
And the context is joined from the holder's row rather than copied into the child
```

#### UC-WM26: Terminal listings keep rendering the holder label over its children

```gherkin
Given delivered or removed children reference a holder by group id
When the operator lists todos including the delivered or removed sections
Then those children render grouped under their holder's label
And the holder itself contributes no entry of its own to any section
```

#### UC-WM9: Intra-group dependency nests under its dependency

```gherkin
Given a group holder "epic" with active grouped children "base" and "follow-on"
And "follow-on" declares an after-dependency on "base"
When the workflow projects the todo list
Then "follow-on" nests under "base" instead of beside it under "epic"
And "base" retains its own row state and is not made a holder by the after-child
```

#### UC-WM10: Cross-group dependency does not re-home the dependent

```gherkin
Given an active grouped child "left-child" under holder "left-epic"
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

#### UC-WM32: Listing reads the caller's project through the workflow service

```
Given an operator or agent is inside a project worktree
When they run "telec todo list" or "telec bugs list"
Then the CLI hands the invocation working directory to the workflow service
And the service answers from that project's todo list
And the answer honors the caller's section and delivery-cutoff filters
And each listed bug fix's progress is the one its lifecycle state determines
And the CLI renders the service's answer without reading the todo store itself
```

#### UC-WM33: Todo and bug reads refuse a caller the platform cannot identify

```
Given a process with no resolved person or principal — no terminal login, no usable session identity, or a session whose record holds only an operational role
When it runs "telec todo list", "telec todo show", "telec todo artifacts list", "telec todo artifacts read", "telec todo artifacts diff", or "telec bugs list"
Then the request is refused before any todo is read
And no todo, artifact, or bug content is printed
And the refusal says why: at a terminal, how to establish an identity; inside a session, that the session carries no usable identity
```

```
Given active todos [ready-a, prep-b]
And ready-a has all after dependencies delivered and a ready lifecycle phase
And prep-b is still before the ready lifecycle phase
When the operator runs "telec todo list"
Then ready-a appears in the Ready band before prep-b
And no manual position value is read or written to produce that order
```

#### UC-WM27: Direct delivery reconciles pending material and derives terminal phase

```
Given an active todo "shipped-thing" with implementation work complete
And pending documentation material is owned by "shipped-thing"
When the operator runs "telec todo deliver shipped-thing --commit abc1234"
Then the pending documentation is reconciled with delivery semantics before the transition reports success
And the entry's status flips to "delivered"
And delivered_at is set to the current UTC timestamp
And delivered_commit is set to "abc1234"
And the workflow engine derives lifecycle_phase as "delivered" from the persisted delivery evidence
And delivered-slug cleanup runs to tear down any leftover worktree/branch
And the entry no longer appears in the default "telec todo list" view
And "telec todo list --include-delivered" can show the delivered history
And a new "shipped-thing" slug may be created because the unique-slug index excludes delivered entries
```

#### UC-WM31: Delivery without a commit is refused for SDLC work

```
Given an active todo whose kind is "feature", "change", or "bug"
When the operator runs "telec todo deliver <slug>" without --commit
Then the delivery is refused and the command exits non-zero naming the missing provenance
And the entry keeps its current status with no delivered_at and no delivered_commit
And the pending documentation material reconciled for the attempted delivery is left as it was
```

#### UC-WM43: Remove a todo that is no longer wanted

```gherkin
Given an active todo "feature-y" is no longer wanted
When the operator runs "telec todo remove feature-y"
Then the todo no longer appears in default reads during the recovery window
And it remains recoverable by its durable identity until that window ends
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
And emits the todo-updated event so the lifecycle runner re-evaluates the task
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

#### UC-WM15: Rename reflects the new slug in the bound session's title

```gherkin
Given a session bound to a todo, whose title embeds the old slug as a token
When the operator runs "telec todo update my-todo --slug new-slug"
Then the rename engine reconciles the bound session's title, replacing the old-slug token with the new slug
And the session's title never renders the old slug alongside the new slug
```

#### UC-WM16: Todo update from a working directory resolving to no project checkout fails loud

```gherkin
Given an active todo "feature-x" exists in its project
When the operator runs "telec todo update feature-x --release" from a working directory that resolves to no project checkout
Then the workflow service refuses with a clear error naming the unresolved working directory
And it does not report "feature-x" as absent from the todo list
And it does not create or read a stray todos.db under the unresolved working directory
```

#### UC-WM28: A manual hold through update carries the reason it exists

```gherkin
Given an active todo "feature-x" exists in its project
When the operator runs "telec todo update feature-x --hold --reason '<why this waits, or the gate or owner it waits on>'"
Then the workflow service records hold=true and hold_audit with source manual, the stated reason, the time, and the caller session id
And `telec todo show feature-x` exposes that source and reason together
And a `--hold` request whose reason is missing or blank is refused before any write, naming the reason as required
And a `--reason` supplied without `--hold` is refused before any write rather than ignored
```

#### UC-WM29: Every hold has truthful provenance and a meaningful reason

<!-- planned-change:github-item-acts -->

```gherkin
Given a hold set through any path — a manual writer (`telec todo update --hold`, `telec todo create --hold`) or an automatic writer (a task-error stamp, a diagnosis-unresolved stamp, a session-close hold, or another grounded mechanism)
When an observer reads the hold through `telec todo show`
Then hold_audit.reason says why the hold exists or names the gate or owner it waits on
And a manual writer received that reason from its caller, and an automatic writer produced its own causal reason
And the command that set the hold is never presented as its reason
And a hold recorded before this contract, whose stored reason is the command that set it, is projected as reason-unknown and is never interpreted as a gate, an owner, or a reason
```

<!-- change:github-item-acts -->

```gherkin
Given a hold set through any path — a manual writer (`telec todo update --hold`, `telec todo create --hold`), a person's hold from the item's GitHub issue, or an automatic writer (a task-error stamp, a diagnosis-unresolved stamp, a session-close hold, or another grounded mechanism)
When an observer reads the hold through `telec todo show`
Then the hold's reason says why the hold exists or names the gate or owner it waits on, or, for a person's hold from GitHub, who held it there
And a manual writer received that reason from its caller, a person's hold from GitHub carries the reason the platform infers from that act, naming the person and that they held it on GitHub, and an automatic writer produced its own causal reason
And a command name is never presented as a hold's reason
And a hold recorded before this contract, whose stored reason is the command that set it, is projected as reason-unknown and is never interpreted as a gate, an owner, or a reason
```

<!-- /planned-change:github-item-acts -->

#### UC-WM30: A human operator can hold an active todo from the preparation view

#### UC-WM34: An identity-addressed action acts on exactly the identified todo or is refused

```gherkin
Given a project holds a removed todo, a delivered todo, and a live todo that share one slug
When an agent calling the workflow API addresses a lifecycle or artifact-changing action to the removed todo's durable identity
Then the agent receives a refusal naming the removed state and reactivation as the way forward
And none of the three todos changes
When the agent addresses such an action to the delivered todo's durable identity
Then the agent receives a refusal naming the delivered state as read-only
And none of the three todos changes
When the agent addresses the same action to the live todo's durable identity
Then the live todo changes exactly as it does when the action is addressed to its slug
And the removed and delivered todos do not change
```

#### UC-WM35: The TUI's todo data carries recent deliveries and every iced todo

```
Given a project with grouped and standalone todos delivered inside and outside the recent-delivery window, and iced todos of any age
When a human operator views that project's todos in the TUI
Then it carries only the deliveries inside the recent-delivery window, regardless of group membership
And group headers appear only for groups with visible delivered children in that section
And it carries every iced todo, whatever its age
```

#### UC-WM36: An agent moves a live todo into a group

```gherkin
Given an agent is working with an active todo "moved" that belongs to no group
And "epic" is a holder, or a live todo that has not yet reached prepared
When the agent updates "moved" to belong to "epic"
Then "moved" becomes a child of "epic"
And every todo listing renders "moved" under the "epic" label
And "epic" counts "moved" when it decides whether all of its children are prepared or delivered
And "moved" keeps its own lifecycle state, artifacts, and dependencies
And an "epic" that was not yet a holder becomes one exactly as it would when a child is created under it
```

#### UC-WM37: An agent moves a grouped todo to another group

```gherkin
Given an agent is working with an active todo "moved" that is a child of holder "old-epic"
When the agent updates "moved" to belong to "new-epic"
Then "moved" becomes a child of "new-epic" and is no longer a child of "old-epic"
And "old-epic" stays a holder, and renders nowhere once it has no live child
```

#### UC-WM38: An agent moves a grouped todo out of every group

```gherkin
Given an agent is working with an active todo "moved" that is a child of holder "old-epic"
When the agent updates "moved" to belong to no group
Then "moved" belongs to no group and renders at its section root
And "old-epic" stays a holder, and renders nowhere once it has no live child
```

#### UC-WM39: A move into an ineligible or cyclic group is refused

```gherkin
Scenario Outline: the agent names a target that cannot hold the todo
Given an agent is working with an active todo "moved"
When the agent updates "moved" to belong to <target>
Then the update is refused with an error naming why the target cannot hold "moved"
And "moved"'s group membership and every other todo are left unchanged

Examples:
| target                                                 |
| a slug that names no live todo or holder               |
| "moved" itself                                         |
| a todo that is not yet a holder and has reached prepared |
```

#### UC-WM40: A move respects the live claims on the todos it changes

```gherkin
Given an agent is working with an active todo "moved"
When the agent updates "moved" to belong to "epic"
And "moved" is claimed by a live session outside the agent's claiming group
Or "epic" is not yet a holder and is claimed by a live session outside the agent's claiming group
Then the update is refused with an error naming the claiming session
And neither "moved" nor "epic" is changed
But a move by a session inside the claiming group proceeds
```

#### UC-WM41: Delivered history orders group context by delivery recency

```gherkin
Given a project with grouped and standalone delivered todos whose delivery times differ
And some delivered todos depend on other delivered todos
When a human operator views the delivered section
Then standalone todos and groups are ordered newest first using each todo's delivery time and each group's newest visible delivery
And children within each group are ordered newest first
And dependencies change neither the order nor the group nesting
And the holder's own timestamps do not affect the order
```

#### UC-WM42: Delivered children retain their group context beside active siblings

```gherkin
Given a group contains both active and delivered children
When a human operator views the delivered section
Then its delivered children appear beneath the group's header
And its active children remain in the active section
```

### Cross-context references

- `integration` — delivered-slug cleanup retires the delivered slug's worktree/branch/workspace after delivery bookkeeping.

## Known caveats

- Active ordering is derived, not manually curated. There is no persisted `position` field and no command for manual reorder.
- `telec todo create` is not a thin todo-entry insert; substantive content is required and the input artifact and its first version are part of the create transaction.

- Slug uniqueness is enforced across addressable entries: `active`, `icebox`, and `holder`. A holder keeps its name reserved while it exists, so a slug-addressed command never faces two candidates; creating a todo with a holder's slug is refused with a 409 naming the holder. Delivered and removed retained entries may share a slug with a fresh live entry because they are addressed by durable identity.

- `telec todo remove` is soft and retained during the recovery window; hard purge is routine maintenance and identity-only.
- The ordered todo list is per-project: one project root, one todo list. There is no global todo list.

- A `claim` block names the holding session's role only when the computer running the session lets the caller read that session's record; otherwise it names the session and its computer without a role.
