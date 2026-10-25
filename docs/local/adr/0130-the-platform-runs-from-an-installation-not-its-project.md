---
number: 130
date: 2026-10-25
description: The platform runs from installed releases kept apart from every project and from the platform home; a commit changes nothing live, an install is the only path to live, and agents operate the installation through telec app.
---

# The Platform Runs From An Installation, Not Its Project — ADR

## Context

The platform's own repository checkout was at once the project where its
development happens and the live platform every session on the machine runs
on. The installer converted the checkout it ran from into the live platform,
commit-boundary maintenance replaced the live daemon with every commit on that
checkout's main (ADR-0087, ADR-0124), the platform's published documentation
deployed from those commits (ADR-0088), channel self-update advanced the same
checkout, and agents restarted the platform through that checkout's `make`
targets (ADR-0041). Code under construction therefore reached the live platform
with each commit, and a mistake in development took the platform down for
every session on the machine. The operator develops on the machine that runs
the platform, which the v1 maintenance stance admits as an operator need
(ADR-0074).

## Decision

The platform runs from an installation: installed releases of its repository,
each a worktree of one repository kept under the XDG data directory, apart from
every project and from the platform home, with every live surface bound to the
active release through one pointer. A commit in any project changes nothing
live. Installing a revision — forward only — is the one path by which a revision
becomes live, whether the bootstrap, the channel reaction or an explicit
`telec app install` starts it. Returning to the previous release is offered only
after an install that migrated no state, as the store owners report it, and
state is never backed up or migrated down. Agents and the integrator operate
the installation through `telec app` from any directory.

## Consequences

- The platform's project is an ordinary project: its commits keep their
  project-level maintenance and local documentation, and activate nothing.
- The platform's published documentation and agent artifacts deploy from the
  installed release, after an install, not from a commit.
- The integrator's runtime judgment follows the install of the revision it
  pushed, after publication of that revision to the repository, instead of
  preceding publication.
- Store owners report the migrations they begin and what each did, so that an
  install's failure handling and rollback rest on what actually changed.
- Runtime state — the machine environment file, the daemon's process record,
  the install record — lives outside every release.
- A machine with no project checkout runs and updates its installation the same
  way; project-declared jobs and help desks stay with the project that declares
  them.

## Alternatives Considered

- **Keep the checkout live and guard it.** Every guard leaves the coupling in
  place; one missed path still brings development to the live platform.
- **Declare the existing checkout the installation and add a second
  development checkout beside it.** It makes the project the special case, and
  the installation remains a registered checkout that shows up as a project
  with work hanging under it.
- **Place the installation inside the platform home.** Mixes installed code
  with the configuration and state every release reads, and couples the home's
  history to code versions.
- **Back up migrated stores to make every install reversible.** Restoring
  discards everything written since the install while the commits and worktrees
  it belongs to remain, so state and work diverge; it also adds copying
  machinery the maintenance stance does not admit.
- **Require migrations within a major to stay readable by the previous
  release.** Guaranteeing it needs either a second installed version under test
  or a validator judging migrations, both excluded; offering rollback only when
  nothing migrated needs neither.
- **Let the integrator install each revision it pushes.** The channel reaction
  already installs every pushed revision on its channel; a second path acts on
  the same revision again, races the first, and puts unadmitted revisions on
  machines whose channel does not take them.

## Status

Superseded in part by ADR-0131: the platform's published documentation and agent artifacts publish from its project's commits, and from an install only where no platform project checkout is registered.
