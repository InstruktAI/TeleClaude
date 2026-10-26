---
description: The platform runs from installed releases of a project's repository,
  kept under the XDG data directory apart from the project and the platform home,
  so development changes nothing live until a revision is installed; `telec app` installs
  forward, rolls back one migration-free step, and operates the live platform from
  any directory.
visibility: internal
---

# Installed Releases — Spec

## What it is

A project is its development checkout. It exists first and carries the
workflow from its first moment: todos, worktrees, sessions, its integrator,
commits and pushes. The installation is what the platform runs: installed
releases of a project's repository, put in place by an install act. Nobody
develops in an installation, and nothing in the workflow points at one.

The platform's services and its published `telec` run from the installation's
active release. Operating the live platform therefore never runs code under
construction; code under construction runs only through a worktree's own
wrapper (`local/projects/teleclaude/spec/feature/agent_runtime/checkout-code-selection`).

The model holds on every machine and for every fork: a contributor clones a
repository as their project and installs from the repository they follow, and
a machine with no project checkout runs and updates its installation the same
way.

## Canonical fields

### Location

The installation lives under the XDG data directory, in the platform's own
folder there, the way the platform's logs live under the XDG state directory.
It holds one release per installed revision and a pointer to the active
release. The platform home stays separate: it holds the configuration and
state every installed release reads, and no release carries any of it.

### Releases

- **A release** is a git worktree, at exactly one revision, of the one
  repository the installation keeps — a clone of the repository it was
  installed from — with its own environment built in place. It depends
  on no project checkout: the live platform keeps running, restarting,
  installing and rolling back when the project it came from is absent.
- **The active release** is the one the services and the published `telec` run
  from. Exactly one release is active, and its revision is observable.
- **The previous release** — the one active before the most recent install —
  stays installed.

- **A release a running terminal interface runs from** stays installed for as
  long as that interface's registry record names it
  (`local/projects/teleclaude/design/architecture/tui-state-layout`), whether
  or not it is the active or previous release. When the registry cannot be
  read, or a running interface's record names no release, an install removes
  no release.

- **Posture.** A release selects one immutable revision; nothing edits or
  commits in it. Release identity and source preservation follow
  `local/projects/teleclaude/spec/feature/reconciliation/release-checkout`.
- **Not a project.** Installing never registers a release or the installation
  as a project, never declares it a home, and starts no agent session in it.

### Installing

Installing moves the platform forward to another revision; rollback, below, is
the only other act that changes which release is active. Installing prepares
the chosen revision as a new release beside the active one, stops the daemon, runs the new release's migrations, makes it the active release and
starts the daemon on it, under the guarantees of
`local/projects/teleclaude/policy/daemon-availability`.

- **Target.** A named revision, or without one, the target the installation's
  channel resolves for the repository it follows
  (`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`).
- **Forward only.** A revision older than the active release is refused and
  nothing changes. Ordering follows the release transitions that channel
  contract supports.
- **Idempotent.** Installing the revision that is already active changes
  nothing.
- **Ran migrations.** Any migration that starts since the active release
  became active, in any store, counts as having changed state, whatever it
  does — a migration interrupted before its ledger write included. Every owner
  whose store the platform migrates, through a migration ledger or when the
  store is opened, signals that it is starting a migration before it changes
  anything; an owner that cannot signal counts as having started one. An
  install ran migrations when any migration started during it. An install that
  ran migrations is never undone by rollback.
- **Failure.** An install completes once the daemon is verified serving the new
  release, whether a daemon was serving before it or was stopped. The one
  exception is initial provisioning — the bootstrap's install on a machine with
  no installed release and no daemon serving — which completes once its release
  is active and `telec` is published. The move off a project checkout, where
  that checkout's daemon serves, completes like any other install. An install
  that fails before any migration started leaves the previously active release
  active and serving, and reports why. One that fails after a migration started
  reports the failure and which stores its migrations reached, is never
  reported as complete, and is repaired forward.

- **Running terminal interfaces move with the install.** A completed install
  reloads every running terminal interface onto the new active release
  (`local/projects/teleclaude/design/architecture/tui-state-layout`), so the
  operator never restarts one to reach installed code. An interface the reload
  does not reach is reported and keeps its release installed under Releases; it
  never changes the install's outcome.

- **Publication follows the install.** Publishing the installed release's
  configuration schemas
  (`local/projects/teleclaude/spec/feature/reconciliation/config-schema-publication`)
  and, where the machine holds no project checkout of the platform to publish
  them, its documentation and agent artifacts
  (`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`)
  follows a completed install. A publication failure is reported and replayed;
  it never changes which release is active.

- **Every route is this act.** The bootstrap, channel convergence and an
  explicit `telec app install` all reach the live platform through it. What a
  commit on a project's main owes is
  `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`'s,
  and it never changes the active release.

### Rollback

Rollback makes the previous release active again and restarts the daemon on
it, only while no migration has started since the active release became
active — neither during its install nor afterwards, when the active release
first opens a store. Store owners signal every migration the active release
starts to the installation, whenever it starts. When a migration has started,
or no previous release is installed, rollback refuses, names the condition, and
changes nothing. No state is backed up or restored.

### Assessment after an install

Every install that opens its stopped window — the daemon stopped, or none
serving — owes one assessment of the release that runs after it, whichever
route reached the install and whether or not the machine performs any source
integration. For initial provisioning that is the release its first start
serves.

- **Owed before the restart.** The release being installed numbers the install
  and records it as owed when its stopped window opens, before any migration
  starts, so the obligation outlives the restart and every outcome the install
  can end in — whichever release's installer performs the install. An install
  that ends before its stopped window — refused, unchanged, failed while
  preparing, or with its stop withheld — owes none. An install whose obligation
  cannot be recorded fails inside its stopped window.
- **Announced while owed.** Each time the daemon starts while an install is
  owed, and again at a fixed interval for as long as one stays owed, it
  announces the owed assessment, so an announcement that found no recipient is
  repeated. The announcement activates the installation inspector on the
  installation's own computer
  (`sdlc/procedure/maintenance/installation/overview`), answered by one
  standing agent for the installation
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`).
- **Recorded by the inspector.** `telec app assessed <install>` records that
  the install `telec app status` shows under that number has been assessed. It
  discharges that install and every earlier owed one; an install numbered after
  it stays owed, a later attempt at the same revision included. It refuses,
  naming what is owed, when no owed install carries that number, and while the
  daemon is not serving the active release.
- **Never fabricated.** A queued install, an accepted restart or a completed
  install is not an assessment. An install whose daemon does not return stays
  owed beside the failure `telec app status` reports, until a start serves
  again and its assessment is recorded.

### First install

A bootstrap command checks the machine's prerequisites, installs the
repository's latest release through the install act and publishes `telec`.
Configuration is completed in the terminal interface or with `telec config`.
Once the configuration is valid, starting the platform installs its services
and starts the daemon; the terminal interface starts it by itself.

### Moving off a project checkout

On a machine where the platform runs from its project checkout, one run
creates the installation, installs a release through the install act, and
moves the services, the published `telec` and the home-level links to it. The checkout stays where it is, an ordinary project
with all its todos, worktrees and claims.

### Operating surface

`telec app` operates the installation from any directory: `status`, `start`,
`stop`, `restart`, `install [<revision>]`, `rollback` and
`assessed <install>`. Every verb acts on the installation, whatever checkout
the caller stands in. `status` names the active release alongside the daemon's
health, the installs whose assessment is owed by number and revision, and
the most recent recorded assessment. The lifecycle verbs keep the guarantees of
`local/projects/teleclaude/policy/daemon-availability`.

### Use cases

#### UC-IR1: An operator installs the platform on a new machine

```gherkin
Given an operator's machine has no TeleClaude platform
When they run the bootstrap and complete the configuration in the terminal interface
Then the platform runs from the active release of a new installation
And the operator cloned no repository and typed no service command
```

#### UC-IR2: An agent installs a pushed revision

```gherkin
Scenario: Installing a newer revision
  Given the platform runs from its installation
  And a newer revision of its repository has been pushed
  When an agent acting for the operator installs that revision
  Then the platform runs that revision
  And the release that was active before stays installed
  And the installation's status names the new active release

Scenario: Installing an older revision
  Given the platform runs from its installation
  When an agent acting for the operator installs a revision older than the active release
  Then the install is refused
  And the platform keeps running the active release

Scenario: An install that fails before any migration started
  Given an install of a newer revision fails before any migration started
  When the operator looks at the installation's status
  Then the previously active release is still active and serving
  And the failure and its reason are reported

Scenario: An install that fails after a migration started
  Given an install of a newer revision fails after one of its migrations started
  When the operator looks at the installation's status
  Then the install is reported as failed, not complete
  And the report names which stores its migrations reached
```

#### UC-IR3: An agent returns the platform to the previous release

```gherkin
Scenario: No migration has started since activation
  Given no migration has started since the active release became active
  When an agent acting for the operator rolls the installation back
  Then the platform runs the previously active release again

Scenario: A migration has started since activation
  Given a migration has started since the active release became active
  When an agent acting for the operator rolls the installation back
  Then the rollback is refused with that reason
  And the platform keeps running the active release
```

#### UC-IR4: An agent in a project operates the live platform

```gherkin
Given an agent works in a project checkout whose code differs from the active release
When it restarts the platform or asks for its status through telec app
Then the restarted platform runs the installation's active release
And the status names that release
And nothing in the project checkout is run or changed
```

#### UC-IR5: A machine running from its project moves to an installation in one step

```gherkin
Given a machine whose platform runs from the operator's project checkout
And that project holds todos, worktrees and claims
When the operator runs the move once
Then the platform runs from an installation
And the project keeps every todo, worktree and claim where it was
```

#### UC-IR6: An operator keeps working in the terminal interface across installs

```gherkin
Given an operator's terminal interface is running from the active release
When an agent installs a newer revision, and later another one
Then the terminal interface runs the most recently installed revision without the operator restarting it
And no release a running terminal interface runs from is removed
```

## Known caveats

- Installation machinery for projects other than the platform is outside this
  contract; a side project keeps its own checkout and deploy.
- Rollback returns one step only. After an install that ran migrations the way
  back is a forward repair.

- An install whose started daemon does not verify, and that cannot then stop
  that daemon, leaves the release it attempted active and its daemon running,
  and reports why; while no migration has started, rollback returns the
  platform once that daemon can be stopped.

- Whether a migration started is what the store owners signal. The install
  opens, inside its stopped window, every store the daemon opens at startup and
  every registered project's todo store, so their migrations start there; a
  store the active release first opens later signals its migration then, and
  from that moment rollback is no longer offered. A started migration that
  changed nothing still withdraws rollback.

- A recorded assessment states that an install was assessed, not what the
  assessment concluded; its findings travel through the inspector's recovery
  and the project's bug process.
