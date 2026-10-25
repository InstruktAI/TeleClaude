---
number: 131
date: 2026-10-25
description: The platform's published documentation and agent artifacts publish from its project's commits on main, like every project's; an install publishes them only on a machine where no platform project checkout does.
---

# The Platform's Documentation Publishes From Its Project's Commits — ADR

## Context

ADR-0130 separated the installation the platform runs from its project
checkout, and as one consequence moved the platform's published documentation
and agent artifacts from the commit on main to the install act. Documentation
was counted among the live effects a commit must no longer produce.

Documentation is not runtime. It is the working material of the agents working
in the project checkout: a preparer authors pending contracts on main, and the
builders and reviewers it dispatches read them next. With publication tied to
the install act, nothing a preparer commits reaches those agents until a
release containing it has been cut, admitted by the channel and installed, and
on a machine that has no installation yet it never does. Reviews and plans
stalled on contracts that existed on main and could not be read.

A machine with no project checkout of the platform still needs published
documentation, and there only the installed release can supply it, as the
installer did on release machines before ADR-0130.

## Decision

The platform's project publishes its published documentation and agent
artifacts at the commit boundary on its main, exactly as every other project
publishes its own. The install act publishes them from the installed release
only on a machine where no platform project checkout is registered; where one
is, installing a release leaves the documentation that checkout published in
place. Everything else ADR-0130 moved to the install act stays there.

## Consequences

- A contract committed on the platform's main is readable by every session on
  that machine as soon as commit-boundary maintenance has run, whatever release
  is installed.
- On a development machine the deployed documentation follows the checkout's
  main, not the installed release, so documentation and running code can
  describe different revisions. Agents read the contracts the work is held to;
  the running platform's behavior is read from the active release.
- Commit-boundary publication on a machine with an installation is built by the
  active release's code. A committed source that only newer publication code
  can build is skipped with its build error until a release carrying that code
  is installed and the checkout publishes again.
- A machine without a platform project checkout keeps the documentation of the
  release it installed, so its documentation and code always match.

## Alternatives Considered

- **Keep publication with the install act everywhere.** Every contract a
  preparer writes waits for a release cut, channel admission and an install
  before the agents it was written for can read it, and a machine without an
  installation never receives it.
- **Publish at both the commit and the install on a development machine.** The
  install would redeploy the installed release's older documentation over what
  the checkout's main already published, until the next commit restored it.
- **Have the install act republish the registered checkout's main.** It makes
  the installation depend on a project checkout and duplicates the commit
  boundary's publication path for no reader the commit does not already reach.
