---
description: "Assess the release an install made live on the installation's own computer: read its status, the log window from the earliest owed install through the verified start, and its health; repair forward or roll back while that is still offered; record the assessment."
visibility: 'public'
delivered_by:
  - installation-activation-inspection
subscriptions:
  - teleclaude.installation.assessment.owed
subscription_home: platform
event_delivery: sequential
interruptible: false
role: integrator
dispatch:
  agent: [claude, codex]
  thinking_mode: slow
---

# Installation Assessment — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/event-handling/overview.md

## Goal

Judge whether the release an install made live behaves, on the installation's
own computer, whether or not a development checkout exists there. Every install
owes this assessment, whatever reached it: channel convergence, an explicit
`telec app install`, or the move off a project checkout. This assignment
assesses and recovers; it synchronizes no main, publishes nothing and enters
nothing in an integration queue.

## Preconditions

- The activating event announces that an install is owed an assessment.
- `telec app status` lists every owed install by number and revision.
- `telec app status`, `telec app rollback`, `telec app assessed` and
  `instrukt-ai-logs` are available.

## Steps

1. **Confirm an assessment is owed.** Read `telec app status`. When no install
   is owed an assessment, the event is satisfied; end the activation.
2. **Read the window.** Read the logs from the earliest owed install through
   the verified start of the active release and onwards to now, and the
   platform's health as `telec app status` reports it. A queued install or an
   accepted restart is not a healthy result; judge the running release.
3. **Recover what misbehaves.** Repair a bounded operational failure forward.
   While `telec app status` still offers a return to the previous release, use
   `telec app rollback` when the active release cannot be repaired in place.
   A defect in the source becomes a bug or todo in the project it belongs to;
   it is never fixed in the installed release.
4. **Record the assessment.** Run `telec app assessed <install>` with the
   number of the newest owed install the window covered, as `telec app status`
   lists it. It discharges that install and every earlier one, and keeps a
   later install owed.

## Outputs

- Every owed install up to the assessed install is discharged, with recovery
  performed or a bug or todo filed for what remains.

## Recovery

- **The daemon does not serve the active release.** `telec app assessed`
  refuses; the runtime that never returned is a recovery matter, not a
  completed assessment. Restore service, then assess.
- **A later install arrives during the assessment.** Its obligation stays
  owed, and the daemon announces it again while it is owed.
