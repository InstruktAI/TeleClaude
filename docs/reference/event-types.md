---
id: teleclaude/reference/event-types
type: reference
scope: project
description: TeleClaude event names used between adapters, daemon, and clients.
---

# Event Types — Reference

## What it is

- Canonical list of event names exchanged between adapters, daemon, and clients.

- `session_started`: session created and ready.
- `session_updated`: session metadata updated.
- `session_closed`: session closed and cleaned up.
- `agent_event`: agent lifecycle wrapper with payload types (`session_start`, `prompt`, `stop`, `notification`, `session_end`, `error`).
- `error`: system failure or unexpected adapter error.
- `system_command`: internal system command event (e.g., deploy).

- Event names must match the event contract definitions.

- Adapter/client handling differs by event type; only publish supported events.

- TBD.

- TBD.

- TBD.

## Canonical fields

- TBD.

## Allowed values

- TBD.

## Known caveats

- TBD.
