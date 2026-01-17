# Command Pipeline

## Response Contract

### Sync
- Must complete within its SLA
- Timeout = failure
- Returns full result immediately

### Async
- Returns `command_id` immediately
- Completion via events only
- No sync timeout

### Hybrid
- Returns `command_id` + partial identifiers immediately
- Completion via events only
- No sync timeout

## Timeout Rules

- **Sync**: timeout = failure
- **Async/Hybrid**: no sync timeout; completion handled by events
- External rate‑limit backoff does **not** count toward internal timeouts

## Retry Rules

- Retries are **internal only** and **context-driven**
- The public contract does **not** expose retry counts or policies
- Use standard signals where available (e.g., HTTP `Retry-After`, transport backoff)

## Command Matrix

| Command | Mode | Immediate Return | Success Event(s) | Failure Event | Timeout |
| --- | --- | --- | --- | --- | --- |
| create_session | Hybrid | `command_id`, `session_id`, `tmux_session_name` | `session_created` (+ `agent_ready` / `task_started` when applicable) | `command_failed` | n/a |
| agent_restart | Async | `command_id` | `agent_restarted` | `command_failed` | n/a |
| agent_command | Async | `command_id` | `agent_command_delivered` | `command_failed` | n/a |
| send_message | Async | `command_id` | `message_delivered` | `command_failed` | n/a |
| end_session | Async | `command_id` | `session_ended` | `command_failed` | n/a |

## Completion Semantics

- **session_created**: session record + tmux name assigned (may still be initializing)
- **agent_ready**: agent command injected and stabilized
- **task_started**: initial task injected after agent ready
- **agent_restarted**: restart command injected
- **agent_command_delivered**: agent CLI command injected (no guarantee of completion)
- **message_delivered**: free‑form message injected
- **session_ended**: session cleanup completed
