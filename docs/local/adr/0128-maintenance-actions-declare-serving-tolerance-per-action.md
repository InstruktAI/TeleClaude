---
visibility: internal
number: 0128
date: 2026-10-24
description: Whether a maintenance action runs while the daemon serves is declared per action in the platform base or a project overlay, and such actions run only after a verified start; configuration-schema publication is declared so.
---

# Maintenance Actions Declare Serving Tolerance Per Action — ADR

## Context

ADR-0127 moved Blueprint maintenance and publication out of the stopped
window and placed the declaration that allows it in the platform base alone,
so that a project-declared action would always run inside the window.
Configuration-schema publication is a project overlay action of this
repository. It exports model schemas as the JSON schema files editors use to
check configuration. Runtime configuration loading validates through the
Python models and never reads those files, and the daemon's only contact with
them is linking a worktree's schema directory to the published one. It
replaces nothing the daemon runs on, yet a base-only declaration kept it
holding the daemon down.

ADR-0127 also let an on-demand run perform these actions after a start that
did not verify, or after it had stopped the daemon again and left an
overtaking activation to the drain. In that last case the run still holds the
drain lock while the daemon is stopped, so running them would keep the stopped
interval open for the drain that has to finish it.

The fork was whether the declaration stays a base-only property or becomes
declarable by an overlay, and whether these actions may run without a verified
start.

## Decision

Whether a maintenance action runs while the daemon serves is declared per
action, by the platform base or by a project overlay through an optional key.
This repository's overlay declares it for configuration-schema publication. An
action that does not declare it runs inside the window whenever its activation
owes one. Such actions run only after a verified start, with the daemon left
serving. A commit-boundary drain keeps them recorded when the start does not
verify. An on-demand run names them as not performed when its start does not
verify or when it leaves the daemon stopped for the drain, and running it
again is their recovery.

## Consequences

- The project configuration gains an optional key, with a version step that
  marks where documents may carry it, so an older installation refuses such a
  document as newer instead of failing on an unknown key.
- A step leaves the window only once it is shown to replace nothing the daemon
  runs on; the default remains ADR-0124's stopped execution.
- No stopped interval is held open by an action that does not need it, on
  either the commit-boundary or the on-demand path.

## Alternatives Considered

- **Keep the declaration in the platform base.** No configuration version step
  would be needed, but an overlay action shown to tolerate a serving daemon
  would keep holding the daemon down.
- **Let an on-demand run perform them whatever the start's outcome.** It keeps
  no records, so this avoids a skipped step, but after a handoff it holds the
  drain lock while the daemon is stopped and delays the drain's own start.
