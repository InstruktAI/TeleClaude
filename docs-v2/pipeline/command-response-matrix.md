# Command Response Matrix

## Response Modes

- **Sync**: returns full result immediately
- **Async**: returns `command_id` only, completion via events
- **Hybrid**: returns `command_id` + partial identifiers, completion via events

## Matrix (Use Case → Response Mode)

| Use Case | Response Mode | Immediate Return | Completion Signal |
| --- | --- | --- | --- |
| Create empty session | Hybrid | `command_id`, `session_id`, `tmux_session_name` | session_created / session_ready |
| Create session with agent | Hybrid | `command_id`, `session_id`, `tmux_session_name` | session_ready (agent started) |
| Create session with agent + initial task | Hybrid | `command_id`, `session_id`, `tmux_session_name` | task_started / task_ready |
| Resume existing agent session | Async | `command_id` | agent_resumed |
| Restart agent in session | Async | `command_id` | agent_restarted |
| Send command/message to session | Async | `command_id` | command_completed |
| View live output from session | Async (stream) | stream subscription | output events |
| Attach to session in TUI | Sync | session attachment handle | attached |
| End session | Async | `command_id` | session_ended |
