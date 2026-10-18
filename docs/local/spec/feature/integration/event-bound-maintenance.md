---
description: A project binds platform events about itself to its own deterministic
  maintenance actions, which every computer holding the project's canonical checkout
  performs on that checkout, through the commit-boundary executor, without waking
  an agent.
visibility: internal
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

<!-- planned-change:central-shared-configuration -->

- **Selection.** An event selects the bindings of the project that is its home,
  and only of that project. An event whose home is another home, or that has no
  home, selects no project's event binding. Routing reads only the event's type
  and home; the event's data is never consulted to select a binding.

<!-- change:central-shared-configuration -->

- **Ordinary event selection.** An event selects ordinary event bindings only
  in the project that is its origin. Another origin, or no project origin,
  selects no ordinary event binding. This selection reads event type and
  origin. Configuration bindings use the separate declaration below after the
  configuration-change event reaches the integration consumer; generic event
  interest retains
  `local/projects/teleclaude/spec/feature/event-catalog/event-consumers`.

<!-- /planned-change:central-shared-configuration -->

- **Where it runs.** Every computer holding the project's registered canonical
  checkout performs the selected actions there, whichever computer the event
  originated on. Eligibility follows the maintenance location contract in
  `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`,
  including the installed release checkout. A computer without an eligible
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

<!-- planned:central-shared-configuration -->

### Configuration bindings and reconciliation

A project declares a configuration trigger separately from paths, ordinary
events and canonical-main activation triggers. It names cluster scope or that
project's own shared scope, exact logical key paths and action identities from
the existing maintenance registry. Configuration validation checks the paths
against the repository-owned shared schema and the actions against that
registry. Selection supplies no value predicate or expression language
(`sdlc/principle/design-fundamentals`).

Temporary shared-source unavailability leaves a running consumer on its last
successfully applied state and records reconciliation as unavailable. It
creates no successful application mark. Fresh runtime startup follows
`local/projects/teleclaude/spec/feature/config/machine-config-load`.

A cluster configuration change can select a declaring project's configuration
binding on each eligible computer, even though that event has no project
origin. A project-scoped change selects only that project's declarations.
Integration receives the unchanged source event, then decides from its subject
and changed logical paths which declared actions are relevant. It creates no
synthetic project event and enumerates no consumers in the configuration
writer. Execution location follows this contract's existing eligible-checkout
selection, including installed-source selection; declaring a configuration
binding grants no second execution in a development checkout.

Reconciliation uses the current authoritative snapshot, never event-carried
values. Each action receives its subject, schema and snapshot revision through
an input file and resolves values through the configuration owner. Ordinary
operator reads remain masked; built-in runtime application uses internal typed
configuration inputs. Configuration metadata or values never become command
arguments. Event creation and snapshot consistency belong to
`local/projects/teleclaude/spec/feature/config/shared-runtime-settings`.

The existing executor owns durable obligations, serialization, failure and
replay. Its maintenance persistence also retains successful applied progress
per computer, declaring project, stable consumer/action identity and shared
subject. Progress records the applied revision and schema, desired revision
and any failed attempt without configuration values or secret digests. A
consumer depending on several subjects retains a revision for each; one
subject's success cannot hide another's lag. Stream progress, a recorded
activation and a successful event handler do not establish applied progress
(`sdlc/policy/code-quality-practices`).

At startup, after reconnect, and after a stream-coverage gap, integration
establishes notification coverage before reading current subjects and
reconciling every declared configuration interest. It also recovers unfinished
configuration obligations from the existing maintenance records. A new
consumer and a newly available eligible checkout receive the same initial
reconciliation. This handover retains
`local/projects/teleclaude/design/architecture/event-delivery`.

Work is serialized per consumer and subject set. An old queued notification
reconciles the current head; it cannot reinstall its old snapshot. A completed
revision needs no repeated effect. Intermediate changes may coalesce; every
reconciliation compares the consumer's relevant current inputs with its last
successful inputs rather than trusting the arriving event's changed-path list.
When a completed input set is unchanged, confirming the current compatible
snapshot can advance progress without repeating the action. Interrupted work
retries idempotently; external effects retain their owner's guarantees under
`sdlc/policy/domain-ownership`.

The platform declares its built-in consumers for the migrated adapter/agent
settings and cloud speech/summary settings. Constructor-cached adapters and
agent settings use the existing stopped-daemon maintenance window and service
targets. Their progress advances only after startup constructs the consumers
from the actual shared snapshot and the window confirms the new runtime's
readiness. Live speech/summary application completes its owned refresh first;
the transcription provider's cached client is invalidated and live TTS mute is
preserved. A generic config-singleton reload is not application confirmation
(`local/projects/teleclaude/spec/feature/config/machine-config-load`).

Restart work is recorded before shutdown and runs outside the ordered event
handler. The handler returns after durable obligation registration and drain
launch; it never waits for a restart that depends on that handler settling.
Startup reports the snapshot actually applied, including when it is newer than
the initiating notification. A failed startup or apply retains the prior
successful revision and a replayable failed obligation. Status distinguishes a
stopped consumer from a currently running consumer and reports the latter's
runtime instance with its applied revision. It never presents a historical
success mark as evidence that a stopped service is running
(`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).
<!-- /planned:central-shared-configuration -->

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

<!-- planned:central-shared-configuration -->

#### UC-EBM11: An operator sees shared settings converge on a returning computer

```gherkin
Scenario: Apply the latest settings when a computer returns
  Given an operator has changed shared settings while a consuming computer was unavailable
  And that computer has a declared reaction to those settings
  When the computer returns to service
  Then its reaction applies the current accepted settings
  And the operator can distinguish its completed application from an outstanding or failed application
  And late information about an earlier change cannot restore an earlier setting

Scenario: Retain a failed application's evidence
  Given a declared reaction cannot apply the current shared settings
  When its application attempt fails
  Then the operator can identify its last successful application and the current failure
  And the operator can retry the unfinished application
```

<!-- /planned:central-shared-configuration -->

<!-- planned:release-development-checkouts -->

### Checkout-associated event targets

A logical project's installation event binding selects its installed checkout,
including when its registered development checkout is also present. A relayed
upstream change does not select both physical locations as two installations.
Development source refresh remains a source operation, independent of admitted
release activation (`local/projects/teleclaude/design/architecture/command-scope`).
<!-- /planned:release-development-checkouts -->

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
