---
description: A slug worktree owns a temporary clone of the TeleClaude home repository, provisioned and retired with the worktree; code loaded from the worktree resolves that clone as its home and never the live home, while installed code keeps operating the live platform.
visibility: internal
delivered_by: [agent-home-clone-provisioning]
---

# Isolated Worktree Home — Spec

## What it is

Every slug worktree owns an isolated, temporary Git clone of the TeleClaude
home repository. The platform creates the clone in the step that creates or
attaches the worktree and deletes it in the step that releases the worktree at
delivery or removal; platform maintenance gives an existing worktree that has
no clone its clone and deletes a clone whose worktree is gone. A renamed todo's
worktree keeps its clone. No agent session creates, selects, sets, or removes
it.

The clone is a Git clone of the home repository — its history and its tracked
material, the project registry and the global, person, and company tier
documents — carrying the tracked working-tree edits present when it is
provisioned. It keeps no remote. When the live home's tracked content has
changed, the next dispatch into the worktree refreshes the clone; writes made
inside the clone are disposable. Databases, credentials, secrets, sockets,
logs, and other runtime state are not part of the clone and are never linked
into it, so the worktree's code reaches no live runtime state through its home.
The cloned registry remains readable with its real project entries; it alone
grants no permission for undelivered code to modify those live repositories.

The clone's location follows from the worktree's own location, so it is known
before the clone exists. Code loaded from a slug worktree, however it is
started, resolves its home to that worktree's clone when `TELECLAUDE_HOME` is
unset, empty, or names a live home by any spelling — the home the installation
of the worktree's owning checkout recorded, or the default home — and refuses
at startup, naming the clone, when the clone is missing. It never falls back to a live home. Any other home its caller
names explicitly is used as named, a relative name meaning the same location it
meant where the caller invoked the command. Code loaded from any other checkout —
the installed canonical checkout, the integration worktree — resolves its home
as before, so agent sessions, hooks, installed commands, and the daemon keep
operating the live platform and their environment is unchanged.

## Canonical fields

### Use cases

#### UC-IAH1: A worktree receives its home when it is provisioned

```gherkin
Given a todo's slug worktree is created or attached for dispatch
When provisioning completes
Then the worktree owns a temporary clone of the TeleClaude home repository
And the clone contains the tracked project registry and tier documents
And no agent created or selected that home
```

#### UC-IAH2: The clone follows current tracked configuration

```gherkin
Given a tracked home configuration document differs from what a worktree's clone holds
When the worktree is next dispatched
Then its clone holds the current tracked working-tree content
And the source document is unchanged
```

#### UC-IAH3: Sessions on one worktree share its home

```gherkin
Given a build session and a later review session work in the same slug worktree
When each runs the worktree's code
Then both run it against the same worktree home
```

#### UC-IAH5: Installed code keeps operating the live platform

```gherkin
Given an agent session in a slug worktree
When the global telec, an agent hook, the agent shell, or git runs in that session
Then it resolves the live home exactly as it does outside a worktree
And the session's environment names no worktree home
```

#### UC-IAH6: Checkout grading uses the worktree's home

```gherkin
Given an agent works in a slug worktree whose code differs from the installed checkout
When the agent runs the quality gate for that worktree
Then the worktree's code is graded with the tracked configuration in its worktree home
And no quality step assembles a separate partial home
And the live home is unchanged
```

#### UC-IAH7: A missing worktree home is refused

```gherkin
Given a slug worktree whose home does not exist
When code loaded from that worktree starts
Then it refuses at startup with the missing home named
And no home is created
And the live home is unchanged
```

#### UC-IAH8: Releasing the worktree deletes its home

```gherkin
Given a slug worktree with its home
When the worktree is released at delivery or removal
Then its home is deleted
And the source home repository is unchanged
```

#### UC-IAH9: Maintenance deletes an orphaned home

```gherkin
Given a worktree home whose worktree no longer exists
When platform maintenance runs
Then that home is deleted
```

#### UC-IAH10: Registry reads do not authorize live project writes

```gherkin
Given a worktree's clone contains the real project registry
When undelivered checkout code invokes an operation that would update registered projects
Then the operation cannot change any live repository named by that cloned registry
And the registry remains available for configuration reads
```

#### UC-IAH13: Maintenance gives an existing worktree its home

```gherkin
Given a slug worktree that has no home
When platform maintenance runs
Then the worktree owns a home holding the current tracked configuration
And no agent created or selected that home
```

#### UC-IAH14: A renamed todo's worktree keeps its home

```gherkin
Given a todo whose slug worktree owns a home
When the todo is renamed
Then the renamed worktree owns that home
And no home remains under the former slug
```

#### UC-IAH15: Worktree code never resolves the live home

```gherkin
Given code loaded from a slug worktree
When it starts with TELECLAUDE_HOME unset, empty, or naming the installation's recorded home or the default home however it is spelled
Then it runs against that worktree's home
And the live home is unchanged
```

## Known caveats

- The clone carries no session record, so a caller-gated command run through a
  worktree's own wrapper is refused. Help is served before the gate, and
  behavior that acts through the daemon is verified after delivery
  (`project/policy/test-moratorium`).
- Between dispatches the clone is a snapshot: a tracked live edit made while a
  session works reaches the worktree's code at the worktree's next dispatch.

## See Also

- docs/project/spec/feature/agent_runtime/checkout-code-selection.md — which
  checkout's code executes and how its quality rules are selected.
- docs/project/design/architecture/home-repository.md — the retained set that
  determines what the home repository records.
