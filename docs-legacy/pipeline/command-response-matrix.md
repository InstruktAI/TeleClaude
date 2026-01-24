# Command Response Matrix

## Response Modes

- **Sync**: returns full result immediately
- **Async**: returns `command_id` only, completion via events
- **Hybrid**: returns `command_id` + partial identifiers, completion via events

## Matrix (Use Case → Response Mode)

| Use Case                                 | Response Mode  | Immediate Return                  | Completion Signal          |
| ---------------------------------------- | -------------- | --------------------------------- | -------------------------- |
| Create empty session                     | Hybrid         | `session_id`, `tmux_session_name` | session_created            |
| Create session with agent                | Hybrid         | `session_id`, `tmux_session_name` | agent_event(session_start) |
| Create session with agent + initial task | Hybrid         | `session_id`, `tmux_session_name` | agent_event(stop)          |
| Resume existing agent session            | Async          | success/error                     | agent_event(session_start) |
| Restart agent in session                 | Async          | success/error                     | agent_event(session_start) |
| Send command/message to session          | Async          | success/error                     | session_updated            |
| View live output from session            | Async (stream) | stream subscription               | output chunks              |
| Attach to session in TUI                 | Sync           | session attachment handle         | attached                   |
| End session                              | Async          | success/error                     | session_removed            |
