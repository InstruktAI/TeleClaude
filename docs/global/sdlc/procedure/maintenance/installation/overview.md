---
description: "The installation's standing inspector on its own computer: answers
  every installation event its role carries and routes each to the procedure that
  handles it, working on the installation's own state."
visibility: public
subscriptions:
  - teleclaude.installation.assessment.owed
  - teleclaude.installation.release.held
subscription_home: platform
event_delivery: sequential
interruptible: false
role: installation-inspector
dispatch:
  agent:
    - claude
    - codex
  thinking_mode: slow
---

# Installation Inspection — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/event-handling/overview.md

## Goal

Look after the installation on its own computer, whether or not a development
checkout exists there. One standing agent answers every installation event this
role carries and handles each through its route below. Its work is the
installation's own state, as `telec app status` reports it: the active release,
its health and what it owes. What the work finds in a project's source goes to
that project as a bug or todo, where the project's own lifecycle fixes it.

## Preconditions

- The session was activated by an event this procedure subscribes to, in the
  platform home of the computer that emitted it.
- `telec app status` reports the installation on this computer.

## Steps

1. **Route each supplied event by its type.**
   - **`teleclaude.installation.assessment.owed`** — an install is owed an
     assessment. Load `sdlc/procedure/maintenance/installation/assessment` with
     `telec docs get` and apply it to this event.
   - **`teleclaude.installation.release.held`** — the installation holds a
     release beyond its compatibility series. Load
     `sdlc/procedure/maintenance/installation/breaking-release-upgrade` with
     `telec docs get` and apply it to this event.
2. **End the activation** when every supplied event is accounted for: handled,
   or waiting on a person's answer its route asked for.

## Outputs

- Each supplied event handled by its route, with that route's outputs.

## Recovery

- **A route's procedure cannot be loaded.** Report the failure and leave the
  event's work unfinished; never handle it from memory.
