---
description: A project binds platform events about itself to its own deterministic maintenance actions, which every computer holding the project's canonical checkout performs on that checkout, through the commit-boundary executor, without waking an agent.
visibility: internal
delivered_by:
  - checkpoint-event-bindings
---

# Event-Bound Maintenance — Spec

## Required reads

@docs/local/spec/feature/integration/post-commit-maintenance.md

## What it is

A project reacts to events about itself without an agent. In its own
`teleclaude.yml` it binds event types to actions from its maintenance registry,
the same actions its committed paths can owe. When an event whose home is that
project reaches a computer, every action bound to the event's type is performed
in that computer's canonical checkout of the project, through the executor the
commit boundary uses (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`).

A relayed external event is one such event: a GitHub push or release to a
project's repository arrives as `github.push` or `github.release` with that
project as its home. The platform keeps itself current this way: its own
repository binds those two events to the action that converges an installation
to its channel (`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`).

Reactions that need judgment belong to procedures, which wake a standing agent
on the computer where the event originated. Event-bound maintenance runs a
declared command on every computer that holds the project.

**Business value:** a project gets a deterministic reaction to its repository,
its deployments or its business events, declared once beside the code it acts
on, and every machine that carries the project applies it to its own copy. No
agent is spent on a reaction that carries no decision, and no reaction reaches a
project that did not declare it.

## Canonical fields

- **Binding.** A checkpoint binding names `events` instead of a path `scope`,
  together with the action ids it owes. An entry is an exact event type or a
  group pattern ending in `.*`, matched at a segment boundary by the platform's
  shared event-type matcher (`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`).
  A binding names one trigger kind, events or paths, never both.
- **Bound actions.** An event binding names actions from the maintenance
  registry, base or overlay. A judgment action from the checkpoint registry has
  no agent to surface to, and a binding naming one is rejected when the
  project's configuration is validated.
- **Selection.** An event selects the bindings of the project that is its home,
  and only of that project. An event whose home is another home, or that has no
  home, selects no project's event binding. Routing reads only the event's type
  and home; the event's data is never consulted to select a binding.
- **Where it runs.** Every computer on which the project has a registered
  canonical checkout performs the selected actions in that checkout, on its main
  branch, whichever computer the event originated on. A computer without such a
  checkout performs nothing. A worktree never performs event-bound maintenance.
- **What an action receives.** A command may name `{event_file}`, a file holding
  the whole event as the platform recorded it: its id, type, time, origin, home
  and data. It may also name `{event_type}` and `{event_id}`. The event's data
  reaches a command only through that file, never as part of its arguments.
  Whether the event calls for work, such as which branch a push touched or
  whether a release was published, is the action's own decision, made from the
  file.
- **Activation identity.** An event activation is identified by the event's id
  and the declaring project. A computer performs each bound action at most once
  per event activation within the platform's retained delivery records, so a
  replayed event performs nothing a second time.
- **Execution.** The executor performs an event activation's actions as it
  performs a commit activation's: precedence waves, concurrent within a wave,
  under the same drain lock, with each attempt and terminal outcome in the
  structured records and the same masking of declared secrets. Activations are
  drained in the order the computer recorded them. A failed action leaves its
  record failed for review and replay, as at the commit boundary.
- **Commit activations are unchanged.** A binding with a path scope keeps its
  meaning; an event binding is never selected by a commit, a merge, or an
  on-demand run.

### Use cases

#### UC-EBM1: An event about a project performs the actions the project bound to it

```gherkin
Given a project binds pushes to its repository to one of its maintenance actions
And a computer holds that project's canonical checkout
When the platform event of a push to that project's repository reaches the computer
Then the bound action is performed in that checkout
And an agent reading the structured records observes the event activation, the action, and its outcome
```

#### UC-EBM2: A binding to a family of events selects every event in it

```gherkin
Given a project binds every event its repository host sends about it to a maintenance action
When a release event and a pull-request event about that project arrive
Then the bound action is performed once for each of those events
But an event of a family whose name merely begins with the same letters selects no binding
```

#### UC-EBM3: An event about another project performs nothing here

```gherkin
Given a project binds pushes to its repository to a maintenance action
When the platform event of a push to a different project's repository arrives
Then no action of the first project is performed
And an event that concerns no home performs none either
```

#### UC-EBM4: Every computer holding the project acts on its own checkout

```gherkin
Given two computers each hold a canonical checkout of the same project
And the project binds an event to a maintenance action
When one such event about the project is published on any computer
Then each of the two computers performs the bound action once, in its own checkout
And a computer that does not hold the project performs nothing
```

#### UC-EBM5: The action decides from the event it receives

```gherkin
Given a project binds pushes to its repository to an action that acts only on its main branch
When a push to another branch arrives as an event about that project
Then the action is performed and reads the event it was handed
And it completes without acting, reporting that the event called for nothing
```

#### UC-EBM6: Event data never reaches a command line

```gherkin
Given an action's command asks for the event it reacts to
When an event whose data carries shell metacharacters arrives
Then the command receives only the location of a file holding the event
And no part of the event's data appears among the command's arguments
```

#### UC-EBM7: A replayed event performs nothing a second time

```gherkin
Given a computer has performed the actions bound to an event
When the same event is delivered to that computer again within the retained delivery records
Then no bound action is performed again
```

#### UC-EBM8: A failed event action stays visible and replayable

```gherkin
Given an event activation owes an action that fails
When the drain continues with other owed work
Then the failed action remains identifiable by its event activation and action identity
And an agent can replay it through the executor with the same structured records as the first attempt
```

#### UC-EBM9: A judgment action cannot be bound to an event

```gherkin
Given a project declares an event binding naming an action that needs an agent's judgment
When the project's configuration is validated
Then the declaration is rejected, naming the binding and the action
```

#### UC-EBM10: A commit never selects an event binding

```gherkin
Given a project declares both a path binding and an event binding
When a commit on canonical main changes paths the path binding matches
Then only the path binding's actions are owed
And the event binding's actions are not performed
```

## Known caveats

- An event type names what happened at the source, not every detail: GitHub's
  action (`opened`, `published`) is part of the event's data, so a binding on
  `github.release` is selected by every release action and the bound command
  decides which ones call for work.
- An action bound to an event performs what its command does on every computer
  holding the project. Work that must happen once in the whole cluster belongs
  to a procedure, which acts only on the computer where the event originated.

## See Also

- docs/local/design/architecture/checkpoint-system.md — the registries and bindings these actions are declared in.
- docs/local/spec/feature/integration/post-commit-maintenance.md — the executor that performs them.
- docs/local/spec/feature/reconciliation/channel-gated-self-update.md — the platform's own use of an event binding.
