---
visibility: internal
number: 0129
date: 2026-10-24
description: Whether a maintenance action runs while the daemon serves is declared per action by the platform base or a project overlay, so this repository's configuration-schema publication also leaves the stopped window.
---

# Overlays Can Declare Maintenance Actions That Run While the Daemon Serves — ADR

## Status

Superseded by ADR-0130: a commit changes nothing live, so no maintenance run
replaces the daemon and whether an action runs while the daemon serves no
longer decides anything.

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

The fork was whether the declaration stays a property of the platform base or
becomes declarable by a project overlay.

## Decision

Whether a maintenance action runs while the daemon serves is declared per
action, by the platform base or by a project overlay through an optional key.
This repository's overlay declares it for configuration-schema publication. An
action that does not declare it runs inside the window whenever its activation
owes one.

## Consequences

- The project configuration gains an optional key, with a version step that
  marks where documents may carry it, so an older installation refuses such a
  document as newer instead of failing on an unknown key.
- This repository's tracked document receives the declaration through that
  step's migration run, which canonical-main maintenance performs while the
  daemon is stopped; no hand edit places the key in front of a daemon that does
  not know it.
- A step leaves the window only once it is shown to replace nothing the daemon
  runs on; the default remains ADR-0124's stopped execution.

## Alternatives Considered

- **Keep the declaration in the platform base.** No configuration version step
  would be needed, but an overlay action shown to tolerate a serving daemon
  would keep holding the daemon down.
