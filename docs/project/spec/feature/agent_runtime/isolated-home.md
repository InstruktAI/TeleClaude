---
description: A slug worktree owns a temporary clone of the TeleClaude home repository, provisioned and retired with the worktree, which the worktree's code runs against while installed commands keep operating the live platform.
visibility: internal
delivered_by: [agent-home-clone-provisioning]
---

# Isolated Worktree Home — Spec

## What it is

Every slug worktree owns an isolated, temporary Git clone of the TeleClaude
home repository. The platform creates the clone in the step that creates or
attaches the worktree and removes it in the step that releases the worktree at
delivery or removal; platform maintenance gives an existing worktree that has
no clone its clone and removes a clone whose worktree is gone. A renamed todo's
worktree keeps its clone. No agent session creates, selects, sets, or removes
it.
A session that is not rooted in a slug worktree has no worktree home, and its
environment carries none.

The clone is a Git clone of the home repository — its history and its tracked
material, the project registry and the global, person, and company tier
documents — carrying the tracked working-tree edits present when it is
provisioned. It keeps no remote. When the live home's tracked content has changed, the next dispatch into
the worktree refreshes the clone; writes made inside the clone are disposable.
Databases, credentials, secrets, sockets, logs, and other runtime state are not
part of the clone and are never linked into it, so the worktree's code reaches
no live runtime state through its home. The cloned registry remains readable with its real project
entries; it alone grants no permission for undelivered code to modify those
live repositories.

The worktree's code finds its home from the worktree. The worktree's own
`telec` wrapper and checkout grading both run that code against the clone, and
a worktree whose home is missing is refused rather than given a partial one.
An agent session started in a slug worktree carries `TELECLAUDE_HOME` naming
the clone, so anything the agent builds from that variable resolves to
disposable material. Every entry point TeleClaude installs for agent sessions —
the global `telec`, the agent hook receiver, the TeleClaude shell and its
startup files, the git wrapper and the declaration reader it shares, and the
other command wrappers in the home's `bin` — resolves the live home the installation recorded and never adopts
the session's value, so hooks, session-scoped checkpoint state, caller
resolution, todos, and the daemon stay on the live platform. None of them
exports the live home as the session's `TELECLAUDE_HOME`.

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

#### UC-IAH4: A worktree session's environment names its home

```gherkin
Given an agent session starts in a slug worktree
When the agent builds a command from TELECLAUDE_HOME
Then that command resolves inside the worktree's clone
And the live home is unchanged
```

#### UC-IAH5: Installed commands keep operating the live platform

```gherkin
Given an agent session in a slug worktree whose environment names the worktree's clone
When the global telec or an agent hook runs in that session
Then it resolves the caller from the live platform and acts on the live records it addresses
And its session-scoped checkpoint state is recorded where the live platform reads it
And the agent does not change its environment to make it work
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
Given a slug worktree whose home no longer exists
When the worktree's own telec wrapper or checkout grading would run the worktree's code
Then the invocation is refused with the missing home named
And no partial home is created
```

#### UC-IAH8: Releasing the worktree retires its home

```gherkin
Given a slug worktree with its home
When the worktree is released at delivery or removal
Then its home is removed
And the source home repository is unchanged
```

#### UC-IAH9: Maintenance removes an orphaned home

```gherkin
Given a worktree home whose worktree no longer exists
When platform maintenance runs
Then that home is removed
```

#### UC-IAH10: Registry reads do not authorize live project writes

```gherkin
Given a worktree's clone contains the real project registry
When undelivered checkout code invokes an operation that would update registered projects
Then the operation cannot change any live repository named by that cloned registry
And the registry remains available for configuration reads
```

#### UC-IAH11: Sessions outside worktrees carry no worktree home

```gherkin
Given an agent session that is not rooted in a slug worktree
When the session starts
Then its environment names no worktree home
And its commands operate the live platform
```

#### UC-IAH12: The agent shell and git keep their installed guards in a worktree session

```gherkin
Given an agent session in a slug worktree whose environment names the worktree's clone
When the agent starts a nested shell or runs git in the worktree
Then the TeleClaude git wrapper governs that git command
And the wrapper reads the project's declaration through the live platform
And a push of the worktree's branch runs the project's installed hooks without resolving any home
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
