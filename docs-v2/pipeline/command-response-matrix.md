# Command Response Matrix

## Response Modes

- **Sync**: returns full result immediately
- **Async**: returns `request_id` only, completion via events
- **Hybrid**: returns `request_id` + partial identifiers, completion via events

## Matrix (Use Case → Response Mode)

| Use Case | Interfaces | Response Mode | Immediate Return | Completion Signal |
| --- | --- | --- | --- | --- |
| Create empty session (escape hatch) | Telegram UI only | Hybrid | `request_id`, `session_id`, `tmux_session_name` | session_created |
| Create session with agent | UI adapters, API | Hybrid | `request_id`, `session_id`, `tmux_session_name` | agent_ready |
| Create session with agent + initial task | UI adapters, API, MCP | Hybrid | `request_id`, `session_id`, `tmux_session_name` | agent_ready → task_delivered |
| Resume existing agent session | UI adapters, API, MCP | Async | `request_id` | agent_resumed |
| Restart agent in session | UI adapters, API, MCP | Async | `request_id` | agent_restarted |
| Send command to session | UI adapters, API, MCP | Async | `request_id` | command_delivered |
| Send message to session | UI adapters, API, MCP | Async | `request_id` | message_delivered |
| View live output from session | UI adapters (WS), API (WS) | Async (stream) | stream subscription | output events |
| End (close) session | UI adapters, API, MCP | Async | `request_id` | session_closed |
