---
visibility: internal
number: 0127
date: 2026-10-24
description: A maintenance run that replaces the daemon performs Blueprint maintenance and publication after the window's verified start instead of inside the stopped window, because both already run against a serving daemon whenever no replacement is owed.
---

# Maintenance Runs Serving-Tolerant Steps After the Verified Start — ADR

## Status

Superseded in part by ADR-0129: the declaration is made per action in the
platform base or a project overlay.

Superseded by ADR-0130: a commit changes nothing live, so no maintenance run
replaces the daemon and no step runs after a window's start.

## Context

ADR-0124 made a maintenance run that owes the daemon's replacement a
stopped-daemon window in which every owed step runs. Every canonical-main
activation owes Blueprint maintenance, and most code activations also owe
publication, so both ran inside every window. Over the week before
2026-10-24 the structured maintenance records show forty windows lasting 57 to
91 seconds. Inside them Blueprint maintenance took a median of 50 seconds and
publication 13 seconds, while every other routinely owed step took under a
second; the start and its verification took about 17 seconds. Most of each
window was spent on two steps that do not replace anything the daemon runs.

Both steps already run while a daemon serves: an activation that owes no
replacement runs them with the daemon up, which the records show more than
350 times in that week. Neither replaces the code, dependencies, configuration
or service definitions the daemon runs on: Blueprint maintenance converges a
graph that command-line queries read, and publication writes the
documentation and agent artifacts that agents read.

The fork was where those steps run when a window is owed: inside it, as
ADR-0124 decided; before the stop, against the old daemon; or after the
verified start, against the new one. A further option was staging the
dependency environment beside the running one so dependency synchronization
could also leave the window.

## Decision

The maintenance registry declares which actions run while the daemon serves,
and the platform base declares it for Blueprint maintenance and publication.
In a run that replaces the daemon, those actions run after the window's
verified start, in their precedence waves; every other owed action still runs
inside the stopped window. The window opens, holds the daemon stopped and
closes on the actions that run inside it alone. Whether a run owes the
replacement at all is decided by the same declaration: only path-selected
actions that do not run while the daemon serves owe it.

## Consequences

- A code commit keeps the daemon down for the stop, the steps that change what
  it runs on, and the start: about 25 seconds instead of about 80.
- Blueprint and publication meet only a daemon running the code they were
  produced from, exactly as they do for every activation that owes no
  replacement; no step meets a daemon older than the code it runs.
- Publication becomes the declared case of the existing rule that a
  publication-only activation owes no replacement, rather than an exception
  named in the window's derivation.
- An activation's restart obligation is held only while its actions that run
  inside a window remain recorded, so replaying a failed Blueprint or
  publication action never stops the daemon.
- When a window's start does not verify, the actions that run while the daemon
  serves stay recorded and a later drain performs them, in step with the
  drain's existing halt on a failed window.
- The declaration belongs to the platform base. A project-declared action runs
  inside the window, which is ADR-0124's guarantee for any step whose safety
  against a serving daemon has not been established.

## Alternatives Considered

- **Run them before the stop.** The old daemon would serve while steps of the
  new code produce their outputs, which is the exposure ADR-0124 closed, and
  nothing about these steps needs the old daemon.
- **Stage the dependency environment and swap it in.** Dependency
  synchronization took a median of 0.2 seconds and at most 5 inside the
  windows recorded, while it rewrites the environment the running daemon
  imports from. A staging and swap mechanism would add a second environment
  to keep consistent for a few seconds of downtime.
- **Move every sub-second step whose safety can be argued.** Configuration
  schema generation and the declaration-view discard each take under a second.
  Declaring them would extend the project configuration schema, with its
  version migration, for no measurable gain.
