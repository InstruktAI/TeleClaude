---
description: A slug worktree owns a temporary clone of the TeleClaude home repository,
  provisioned, refreshed, and retired with the worktree, and kept outside it so nothing
  reaches live runtime state through it.
visibility: internal
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
started, runs against that worktree's clone and never reads `TELECLAUDE_HOME`;
when the clone is missing it refuses at startup, naming the clone. Code loaded
from any other checkout — the installed canonical checkout, the integration
worktree — resolves its home as before, so agent sessions, hooks, installed
commands, and the daemon keep operating the live platform and their
environment is unchanged.

## Canonical fields

### Use cases

#### UC-IAH1: A worktree receives its home when it is provisioned

#### UC-IAH2: The clone follows current tracked configuration

#### UC-IAH3: Sessions on one worktree share its home

#### UC-IAH5: An operator can use the live platform from a worktree

```gherkin
Given an operator is working in a slug worktree and needs an installed platform command
When they use that command from the worktree
Then it operates on the live home as it does outside the worktree
And the worktree home does not replace the live platform environment
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

#### UC-IAH8: Releasing the worktree deletes its home

#### UC-IAH9: Maintenance deletes an orphaned home

#### UC-IAH10: Registry reads do not authorize live project writes

```gherkin
Given an operator wants to inspect or process registered projects from an undelivered worktree
When worktree code uses the cloned project registry
Then it cannot change any live repository named by that registry
And the registry remains available for configuration reads
```

#### UC-IAH13: Maintenance gives an existing worktree its home

#### UC-IAH14: A renamed todo's worktree keeps its home

#### UC-IAH15: A developer can run worktree code without accessing the live home

```gherkin
Given a developer runs code from a slug worktree
When the code starts with any `TELECLAUDE_HOME` value
Then it uses that worktree's isolated home
And the live home remains unchanged
```

## Known caveats

- The clone carries no session record, so a caller-gated command run through a
  worktree's own wrapper is refused. Help is served before the gate, and
  behavior that acts through the daemon is verified after delivery
  (`local/projects/teleclaude/policy/test-moratorium`).
- Between dispatches the clone is a snapshot: a tracked live edit made while a
  session works reaches the worktree's code at the worktree's next dispatch.

## See Also

- docs/local/spec/feature/agent_runtime/checkout-code-selection.md — which
  checkout's code executes and how its quality rules are selected.
- docs/local/design/architecture/home-repository.md — the retained set that
  determines what the home repository records.
