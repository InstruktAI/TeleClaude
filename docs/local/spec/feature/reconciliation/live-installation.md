---
description: The platform runs from an installation derived from a project revision and kept in the platform home — never from a project checkout — so development changes nothing live until a revision is activated, and agents operate that installation through `telec app`.
delivered_by:
  - platform-installation
---

# Live Installation — Spec

## What it is

A project is its development checkout. It exists first and carries the
workflow from its first moment: todos, worktrees, sessions, its integrator,
commits and pushes. The installation is what the platform runs. It is derived
from a project: a revision of that project's repository, put in place by an act
of installing or activating, in a location the platform owns inside its home.

The act that creates an installation records it as an installation of the
repository it came from. Nothing else makes a folder an installation: no flag,
no naming convention, no channel, no branch posture. A folder a person creates
or registers is a project; a folder installation created is an installation.
An installation is never registered as a project, never a home, and never the
place an agent session works, so it appears in no project listing, terminal
interface row or chat forum, and no workflow surface points at it.

The platform's services and its published `telec` command run from the
installation's active revision. Operating the live platform therefore never
runs code under construction. Code under construction is exercised only
through a worktree's own wrapper
(`local/projects/teleclaude/spec/feature/agent_runtime/checkout-code-selection`).

The model holds on every machine and for every fork. A contributor clones a
repository as their project and installs from it; the installation follows the
repository it was installed from. A machine with no project checkout runs and
updates its installation the same way. A side project that grows an
installation of its own follows the same model with its own installer.

## Canonical fields

### Installed revisions

- **Revisions.** Each installed revision is a clean checkout of exactly that
  revision, with its own environment and everything it builds. It depends on
  no project checkout: the live platform keeps running, restarting and
  activating when the project it was installed from is absent.
- **Active revision.** Exactly one installed revision is active. The services
  and the published `telec` run from it, and its revision is observable.
- **Previous revision.** The revision that was active before the latest
  activation stays installed, so the installation can return to it.
- **Release posture.** An installed revision has the exact-release posture of
  `local/projects/teleclaude/spec/feature/reconciliation/release-checkout`: it
  selects one immutable revision, and nothing edits or commits in it.

### Installing

Installing puts a chosen revision of the repository the installer runs from
into the installation and makes it active. Run from a project checkout,
installing leaves that checkout an ordinary project: its todos, worktrees,
claims and sessions stay where they are and stay under its workflow.

On a machine where the platform still runs from its project checkout, one
installer run creates the installation, makes it active and moves the services
and the published `telec` to it. Nothing of the workflow moves.

### Activation

Activation brings a pushed revision of the installation's repository into the
installation and makes it the active revision. It performs the installation,
migrations, dependency reconciliation, publication and daemon replacement that
revision owes, under the daemon availability guarantees of
`local/projects/teleclaude/policy/daemon-availability`. An activation whose
revision owes no daemon replacement leaves the daemon serving.

Activating the revision that is already active changes nothing. An activation
that cannot complete leaves the previously active revision active and serving,
and reports why.

Channel convergence
(`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`)
selects which revision an installation activates, and activates it into the
installation through this same activation.

### Rollback

Rollback makes the retained previous revision active again and restarts the
daemon on it. With no previous revision installed, rollback refuses and names
that condition.

### Operating surface

`telec app` operates the installation from any directory: `install`,
`activate` a revision, `rollback`, and `start`, `stop`, `restart` and `status`.
Every verb acts on the installation, whatever checkout the caller stands in.
`status` names the active revision alongside the daemon's health. Start, stop,
restart and status keep the lifecycle guarantees owned by
`local/projects/teleclaude/policy/daemon-availability`.

### Use cases

#### UC-LI1: An operator installs the platform and keeps developing in their project

```gherkin
Given an operator has a clone of the platform's repository with work in progress in it
When they install the platform from that clone
Then the platform runs from an installation in the platform's own location
And the clone remains an ordinary project with all its work
And the installation appears nowhere as a project
```

#### UC-LI2: Development in a project leaves the live platform untouched

```gherkin
Given the platform runs from its installation
When an agent working for the operator commits to the project's main branch
Then the live platform keeps running the revision it ran before
And no service is restarted by that commit
```

#### UC-LI3: An activated revision becomes the live platform

```gherkin
Scenario: Activating a pushed revision
  Given a revision of the platform's repository has been pushed
  When an agent acting for the operator activates that revision
  Then the live platform runs that revision
  And the revision that was active before stays installed

Scenario: An activation that cannot complete
  Given an activation of a pushed revision fails part-way
  When the operator looks at the installation's status
  Then the previously active revision is still active and serving
  And the failure and its reason are reported
```

#### UC-LI4: An operator returns to the previous revision

```gherkin
Given an activated revision misbehaves
When an agent acting for the operator rolls the installation back
Then the live platform runs the previously active revision again
```

#### UC-LI5: An agent in a project operates the live platform

```gherkin
Given an agent works in a project checkout whose code differs from the active revision
When it restarts the platform or asks for its status through telec app
Then the restarted platform runs the installation's active revision
And the status names that revision
And nothing in the project checkout is run or changed
```

#### UC-LI6: A machine running from its project moves to an installation in one step

```gherkin
Given a machine whose platform runs from the operator's project checkout
And that project holds todos, worktrees and claims
When the operator runs the installer once from that checkout
Then the platform runs from an installation in the platform's own location
And the project keeps every todo, worktree and claim where it was
```

## Known caveats

- Building installation machinery for projects other than the platform is
  outside this contract; a side project with its own daemon applies the model
  through its own installer and deploy.
