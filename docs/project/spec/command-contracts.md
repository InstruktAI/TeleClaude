---
id: 'project/spec/command-contracts'
type: 'spec'
scope: 'project'
description: 'Command contract highlights for session creation, messaging, and agent control.'
---

# Command Contracts — Spec

## What it is

- Command contract highlights for session creation, messaging, and agent control.

- Commands require explicit session identifiers and payloads.
- Command intent must be explicit and stable across interfaces.
- Enumerated intent values are treated as strict contracts.

- Enumerated intent fields must match the declared command contract.

- Commands are rejected when the target session is missing or closed.

## Canonical fields

- `command`: command name.
- `session_id`: target session UUID (required for send/end).
- `payload`: command-specific data (message, agent, computer, etc.).
- `request_id`: unique correlation id for transport requests.
- `source`: originating adapter/client.

## Allowed values

- `command`: `start_session`, `send_message`, `end_session`, `run_agent_command`, `get_session_data`.
- `payload.intent`: `user_message`, `system_command`, `agent_control` (where applicable).
- CLI mapping: `get_session_data` backs `telec sessions tail` in user-facing workflows.

## Known caveats

- Transport layer may wrap commands in request/response envelopes.
- Missing or invalid `session_id` leads to immediate rejection.
