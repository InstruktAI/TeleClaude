---
description:
  In-memory listener registry that notifies callers when target sessions
  stop.
id: teleclaude/architecture/session-listeners
requires:
  - concept/session-types
scope: project
type: architecture
---

## Purpose

- Allow AI sessions to wait on other sessions and receive stop notifications.

## Inputs/Outputs

- Inputs: listener registrations and session stop events.
- Outputs: injected notifications to caller sessions.

## Primary flows

- Callers register a one-shot listener per target session.
- Stop events pop listeners and inject a notification into caller tmux sessions.
- Listeners are cleaned up when callers end or unsubscribe.

## Invariants

- Only one listener per caller-target pair.
- Listeners are in-memory and not persisted across daemon restarts.

## Failure modes

- Daemon restarts drop listeners; callers must re-register.
