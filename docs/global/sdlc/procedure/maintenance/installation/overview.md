---
description: "The installation's standing inspector on its own computer: answers every installation event its role carries and routes each to the procedure that handles it, working on the installation and never on a project."
visibility: 'public'
delivered_by:
  - installation-activation-inspection
subscriptions:
  - teleclaude.installation.assessment.owed
subscription_home: platform
event_delivery: sequential
interruptible: false
role: installation-inspector
dispatch:
  agent: [claude, codex]
  thinking_mode: slow
---

# Installation Inspection — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/event-handling/overview.md

## Goal

Look after the installation on its own computer, whether or not a development
checkout exists there. One standing agent answers every installation event this
role carries and handles each through its route below. The work stays on the
installation: it synchronizes no main, publishes nothing and enters nothing in
an integration queue. A defect in the source becomes a bug or todo in the
project it belongs to and is never fixed in an installed release.

## Preconditions

- The session was activated by an event this procedure subscribes to, in the
  platform home of the computer that emitted it.
- `telec app status` reports the installation on this computer.

## Steps

1. **Route each supplied event by its type.**
   - **`teleclaude.installation.assessment.owed`** — an install is owed an
     assessment. Load `sdlc/procedure/maintenance/installation/assessment` with
     `telec docs get` and apply it to this event.
2. **End the activation** when every supplied event is accounted for.

## Outputs

- Each supplied event handled by its route, with that route's outputs.

## Recovery

- **A route's procedure cannot be loaded.** Report the failure and leave the
  event's work unfinished; never handle it from memory.
