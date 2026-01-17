# API Overview (Target)

This document describes the intended resource-first API surface. All reads are cache-backed; handlers do not fetch.

Source of truth:
- Core resource models: `teleclaude/core/models.py`
- API and WS DTOs: `teleclaude/api_models.py` (target consolidation)

## Principles

- Resource-only endpoints, no aggregates like "projects with todos".
- Consistent shapes across API and WebSocket.
- Cache decides staleness and refresh; API returns cache only.
- Project identifiers are derived from full paths, not repo metadata.

## HTTP Endpoints

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| GET | /health | Health check | No cache |
| GET | /computers | List computers | Cache-backed |
| GET | /projects | List projects | `computer` filter optional |
| GET | /todos | List todos | Filters are optional; `project` and `computer` can be combined or omitted |
| GET | /sessions | List sessions | `computer` filter optional |
| GET | /agents/availability | Agent availability | Cache-backed |
| POST | /sessions | Create a new session | Command handler |
| DELETE | /sessions/{session_id} | End local session | Command handler |
| POST | /sessions/{session_id}/message | Send message to a session | Command handler |
| POST | /sessions/{session_id}/agent-restart | Restart agent | Command handler |
| GET | /sessions/{session_id}/transcript | Tail transcript | Command handler |

Notes:
- Read endpoints return cached data immediately.
- Cache refresh is triggered by TTL rules and invalidation signals, not by API handlers.
- Sessions list is a lightweight summary for fast tree rendering.
- Session details and live events are delivered via WebSocket when a session node is expanded.
- Unfiltered reads are allowed but scoped queries are preferred to reduce payload and churn.

Session summary shape:
- `session_id`, `origin_adapter`, `title`, `working_directory`, `thinking_mode`, `active_agent`, `status`, `created_at`, `last_activity`, `last_input`, `last_output`, `tmux_session_name`, `initiator_session_id`, `computer`

## WebSocket

| Path | Purpose | Notes |
| --- | --- | --- |
| /ws | Push updates and initial state | Clients subscribe to resources by scope. Server sends initial state from cache and pushes updates. |

### Subscription Scope (Target)

Subscriptions accept a rich scope object so the UI can match visible tree expansion:
- `types` (required array)
- `computer` (optional)
- `project` (optional)
- `session` (optional, for detail streams)

### WebSocket Messages (Client)

- Subscribe:
  - {"subscribe": {"types": ["computers", "projects", "todos", "sessions", "agents"], "computer": "raspi", "project": "TeleClaude"}}
- Subscribe to a session detail stream:
  - {"subscribe": {"types": ["session_detail"], "computer": "raspi", "session": "abc123"}}
- Unsubscribe:
  - {"unsubscribe": {"computer": "raspi"}}
- Refresh:
  - {"refresh": true}

### WebSocket Messages (Server)

- computers_initial / computer_updated
- projects_initial / project_updated / projects_updated
- todos_initial / todo_updated / todos_updated
- sessions_initial / session_updated / session_created / session_removed
- session_detail_initial / session_detail_updated
- agents_initial / agent_updated
