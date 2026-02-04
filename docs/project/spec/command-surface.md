---
id: project/spec/command-surface
type: spec
scope: project
description: Command surface contract for TeleClaude client interfaces.
---

# Command Surface — Spec

## What it is

- Stable public interface exposed by the TeleClaude API.

- Session lifecycle actions.
- Agent control actions.
- Help and control signals.

- Interface actions must match the API contract definitions.

- Command semantics remain stable; changes require documentation updates.
- Commands are available according to adapter registration and master-bot policy.

## Canonical fields

- `command`: command name (string).
- `session_id`: target session identifier (optional for list/create).
- `payload`: command-specific data (dict/object).
- `source`: adapter or client origin (optional).
- `created_at`: timestamp when issued.

## Allowed values

- `command`: `start_session`, `send_message`, `end_session`, `get_session_data`, `run_agent_command`, `stop_notifications`, `list_sessions`, `list_projects`.

## Known caveats

- Some commands are adapter-specific (e.g., Telegram-only UX actions).
- Availability depends on adapter registration and permissions.
