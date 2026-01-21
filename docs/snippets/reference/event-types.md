---
id: teleclaude/reference/event-types
type: reference
scope: project
description: TeleClaude event names used between adapters, daemon, and clients.
requires: []
---

## What it is

- Canonical list of event names exchanged between adapters, daemon, and clients.

## Canonical fields

- `session_started`: session created and ready.
- `session_updated`: session metadata updated.
- `session_closed`: session closed and cleaned up.
- `agent_event`: agent lifecycle wrapper with payload types (`session_start`, `prompt`, `stop`, `notification`, `session_end`, `error`).
- `error`: system failure or unexpected adapter error.
- `system_command`: internal system command event (e.g., deploy).

## Allowed values

- Event names must match the event contract definitions.

## Known caveats

- Adapter/client handling differs by event type; only publish supported events.
