# OpenAPI Requirements

## Purpose

Define the human‑readable requirements for the OpenAPI spec. The spec is generated from these requirements.

## Endpoints

### GET /sessions

List all sessions from cache. Support `computer` filter.

### POST /sessions

Create a new session. Accepts `project_path`, `launch_intent`, etc.

### DELETE /sessions/{session_id}

End a local session.

### POST /sessions/{session_id}/message

Send a message/command to a session.

### POST /sessions/{session_id}/agent-restart

Restart the agent in a session.

### GET /sessions/{session_id}/transcript

Retrieve the tail of the session transcript.

### GET /computers

List all discovered computers.

### GET /projects

List all trusted projects.

### GET /todos

List todos across projects.

## Response Requirements

### Standard Response Envelope

- Most write operations return `{"status": "success", "data": ...}` or `{"status": "error", "error": "..."}`.
- Create session returns `session_id` and `tmux_session_name` in data.
