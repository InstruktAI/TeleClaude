---
description:
  In-memory listener registry that notifies callers when target sessions
  stop.
id: teleclaude/architecture/session-listeners
scope: project
type: architecture
---

# Session Listeners — Architecture

## Purpose

- @docs/concept/session-types

- Allow AI sessions to wait on other sessions and receive stop notifications.

- Inputs: listener registrations and session stop events.
- Outputs: injected notifications to caller sessions.

- Callers register a one-shot listener per target session.
- Stop events pop listeners and inject a notification into caller tmux sessions.
- Listeners are cleaned up when callers end or unsubscribe.

- Only one listener per caller-target pair.
- Listeners are in-memory and not persisted across daemon restarts.

- Daemon restarts drop listeners; callers must re-register.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
