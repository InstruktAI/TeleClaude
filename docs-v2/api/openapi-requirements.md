# OpenAPI Requirements

## Purpose
Define the human‑readable requirements for the OpenAPI spec. The spec is generated from these requirements.

## Endpoints

### POST /commands
Accept a command request and return the command response envelope immediately.

### GET /commands/{command_id}
Return the status of a command by `command_id`.

## Request Requirements

### Command Request
- Must include: `command`, `payload`
- `command` is one of: `create_session`, `agent_restart`, `agent_command`, `send_message`, `end_session`
- `payload` fields are defined in `docs/command-contracts.md`

## Response Requirements

### Command Response (immediate)
- Must include: `command_id`
- Must include: `expected_events` (ordered list)
- Must include: `event_timeouts_ms` (per event)
- May include: `partial_result`

### Command Status
- Must include: `command_id`, `status`
- `status` is one of: `queued`, `running`, `success`, `failed`
- May include: `last_event`, `error`
