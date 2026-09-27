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
- Explicit terminal inspection uses `telec sessions tail <session-id> --pane`
  and the session pane read endpoint. The default transcript query is unchanged;
  the session-transcript-retrieval feature spec owns the observation contract.

- MCP CLI mappings:
  - `telec mcp list [--exclude <slug> ...]` lists configured MCP servers without starting them.
  - `telec mcp list-tools <slug>` initializes or reuses the daemon-owned lease for one server and prints its tool catalog.
  - `telec mcp call <slug> <tool> --json '<arguments>'` invokes one MCP tool through the daemon-owned lease and returns the tool result.

## Known caveats

- Some commands are adapter-specific (e.g., Telegram-only UX actions).
- Availability depends on adapter registration and permissions.
- `telec sessions run` runs for a caller the CLI resolved to a session or to a person at a terminal (`project/spec/identity-and-auth` §6).
- When the caller is not a session, the request still runs for the person the terminal's login names (or the sole registered person); only child-session lineage is omitted.
