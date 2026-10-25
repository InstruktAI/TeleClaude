---
description: The platform runs from installed releases of a project's repository, kept under the XDG data directory apart from the project and the platform home, so development changes nothing live until a revision is installed; `telec app` installs forward, rolls back one migration-free step, and operates the live platform from any directory.
visibility: internal
delivered_by:
  - platform-installation
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
- **Ran migrations.** Every owner whose store the platform migrates — through
  a migration ledger or when the store is opened — reports, before it changes
  anything, that it is beginning a migration, and afterwards what that
  migration did: changed its store, left it unchanged as the owner can
  establish, or had effects it cannot establish. An install migrated state when
  any begun migration changed its store or had unknown effects, or when an
  owner could not report. An install ran migrations when it migrated state; a
  migration refused with its store established unchanged is not one. An install
  that ran migrations is never undone by rollback.
- **Failure.** An install completes once the daemon is verified serving the new
  release. An install that fails without having migrated state — including one
  whose begun migrations all left their stores unchanged — leaves the
  previously active release active and serving, and reports why. One that fails
  after it migrated state reports the failure and which stores were changed or
  are unknown, is never reported as complete, and is repaired forward.
- **Publication follows the install.** Publishing the installed release's
  documentation and schemas
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
it, only while no migration has changed state or had unknown effects since the
active release became active — neither during its install nor afterwards, when
the active release first opens a store. Store owners report every migration the
active release begins to the installation, whenever it begins. When a migration
has changed state or its effects are unknown, or no previous release is
installed, rollback refuses, names the condition, and changes nothing. No state
is backed up or restored.

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
`stop`, `restart`, `install [<revision>]` and `rollback`. Every verb acts on
the installation, whatever checkout the caller stands in. `status` names the
active release alongside the daemon's health. The lifecycle verbs keep the
guarantees of `local/projects/teleclaude/policy/daemon-availability`.

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

Scenario: An install that fails without having migrated state
  Given an install of a newer revision fails while no migration has changed a store or had unknown effects
  When the operator looks at the installation's status
  Then the previously active release is still active and serving
  And the failure and its reason are reported

Scenario: An install that fails after it migrated state
  Given an install of a newer revision fails after a migration changed a store or had unknown effects
  When the operator looks at the installation's status
  Then the install is reported as failed, not complete
  And the report names which stores were changed or are unknown
```

#### UC-IR3: An agent returns the platform to the previous release

```gherkin
Scenario: The active release has migrated nothing
  Given no migration has changed state since the active release became active
  When an agent acting for the operator rolls the installation back
  Then the platform runs the previously active release again

Scenario: The active release has migrated state
  Given a migration has changed state since the active release became active
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

## Known caveats

- Installation machinery for projects other than the platform is outside this
  contract; a side project keeps its own checkout and deploy.
- Rollback returns one step only. After an install that ran migrations the way
  back is a forward repair.
- Whether state migrated is what the store owners report. The install opens,
  inside its stopped window, every store the daemon opens at startup and every
  registered project's todo store, so their migrations run there; a store the
  active release first opens later reports its migration then, and from that
  moment rollback is no longer offered.
