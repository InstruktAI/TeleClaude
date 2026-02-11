---
id: 'project/spec/event-types'
type: 'spec'
scope: 'project'
description: 'TeleClaude event names used between adapters, daemon, and clients.'
---

# Event Types — Spec

## What it is

- Canonical list of event names exchanged between adapters, daemon, and clients.

- `session_started`: session created and ready.
- `session_updated`: session metadata updated.
- `session_closed`: session closed and cleaned up.
- `agent_event`: agent lifecycle wrapper with payload types (`session_start`, `user_prompt_submit`, `tool_use`, `tool_done`, `agent_stop`, `notification`, `session_end`, `error`).
- `error`: system failure or unexpected adapter error.
- `system_command`: internal system command event (e.g., deploy).

- Event names must match the event contract definitions.

- Adapter/client handling differs by event type; only publish supported events.

## Canonical fields

- `event_type`: string event name (e.g., `session_started`).
- `session_id`: UUID for the session (optional for system events).
- `payload`: event-specific data (dict/object).
- `created_at`: timestamp (ISO 8601) when emitted.

## Allowed values

- `session_started`, `session_updated`, `session_closed`, `agent_event`, `error`, `system_command`.
- `agent_event` payload types: `session_start`, `user_prompt_submit`, `tool_use`, `tool_done`, `agent_stop`, `notification`, `session_end`, `error`.

## Known caveats

- Some adapters emit adapter-specific metadata in payload; consumers must ignore unknown fields.
- `error` events may omit `session_id` when failure is global.
- `session_end` is part of the normalized type universe, but the hook receiver currently forwards only handled events (`session_start`, `user_prompt_submit`, `tool_use`, `tool_done`, `agent_stop`, `notification`, `error`) into `hook_outbox`.
