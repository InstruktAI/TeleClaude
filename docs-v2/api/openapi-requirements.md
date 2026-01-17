# OpenAPI Requirements

## Purpose
Define the human‑readable requirements for the OpenAPI spec. The spec is generated from these requirements.

## Endpoints

### POST /sessions
Create a session. Request maps to internal `create_session` command.

### POST /sessions/{session_id}/messages
Send a user message to a session. Maps to internal `send_message` command.

### POST /sessions/{session_id}/commands
Send a command to a session. Maps to internal `agent_command` command.

### POST /sessions/{session_id}/agent/restart
Restart an agent for a session. Maps to internal `agent_restart` command.

### POST /sessions/{session_id}/agent/resume
Resume an agent using native session id. Maps to internal `agent_resume` command.

### DELETE /sessions/{session_id}
End a session. Maps to internal `end_session` command.

### GET /requests/{request_id}
Return the status of an asynchronous request by `request_id`.

## Request Requirements

### REST Requests
Each endpoint accepts a REST‑native payload and is translated into the internal command contract.

Payload fields and implicit behavior are defined in `docs-v2/contracts/command-contracts.md`.

## Response Requirements

### Response Envelope (immediate)
- Must include: `request_id`
- Must include: `expected_events` (ordered list)
- Must include: `event_timeouts_ms` (per event)
- May include: `partial_result`

### Request Status
- Must include: `request_id`, `status`
- `status` is one of: `queued`, `running`, `success`, `failed`
- May include: `last_event`, `error`

## Naming

`request_id` is the public name. Internally this maps to the command pipeline’s `command_id`.
