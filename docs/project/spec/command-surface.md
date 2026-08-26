---
description: 'Command surface contract for TeleClaude client interfaces.'
visibility: 'public'
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
- Human-facing CLI mapping: `get_session_data` is surfaced as `telec sessions tail`.

- MCP CLI mappings:
  - `telec mcp list [--exclude <slug> ...]` lists configured MCP servers without starting them.
  - `telec mcp list-tools <slug>` initializes or reuses the daemon-owned lease for one server and prints its tool catalog.
  - `telec mcp call <slug> <tool> --json '<arguments>'` invokes one MCP tool through the daemon-owned lease and returns the tool result.

## Known caveats

- Some commands are adapter-specific (e.g., Telegram-only UX actions).
- Availability depends on adapter registration and permissions.
- `telec sessions run` accepts either a verified caller session identity or a verified terminal identity.
- When `x-caller-session-id` is absent, the request still runs if `verify_caller` resolves terminal identity from `x-telec-email` (or the single-user fallback); only child-session lineage is omitted.
