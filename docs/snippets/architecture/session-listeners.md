---
id: teleclaude/architecture/session-listeners
type: architecture
scope: project
description: In-memory listener registry that notifies callers when target sessions stop.
requires:
  - ../concept/session-types.md
---

Purpose
- Allow AI sessions to wait on other sessions and receive stop notifications.

Primary flows
- Callers register a one-shot listener per target session.
- Stop events pop listeners and inject a notification into caller tmux sessions.
- Listeners are cleaned up when callers end or unsubscribe.

Invariants
- Only one listener per caller-target pair.
- Listeners are in-memory and not persisted across daemon restarts.
