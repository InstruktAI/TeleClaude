# Command Pipeline

## Response Contract

### Sync
- Must complete within its SLA
- Timeout = failure
- Returns full result immediately

### Async
- Returns `request_id` immediately
- Completion via events only
- No sync timeout

### Hybrid
- Returns `request_id` + partial identifiers immediately
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
| create_session | Hybrid | `request_id`, `session_id`, `tmux_session_name` | `session_created` (+ `agent_ready` / `task_delivered` when applicable) | `command_failed` | n/a |
| agent_restart | Async | `request_id` | `agent_restarted` | `command_failed` | n/a |
| agent_command | Async | `request_id` | `command_delivered` | `command_failed` | n/a |
| send_message | Async | `request_id` | `message_delivered` | `command_failed` | n/a |
| end_session | Async | `request_id` | `session_closed` | `command_failed` | n/a |

## Completion Semantics

- **session_created**: session record + tmux name assigned (may still be initializing)
- **agent_ready**: agent command injected and stabilized
- **task_delivered**: initial task injected after agent ready
- **agent_restarted**: restart command injected
- **command_delivered**: agent CLI command injected (no guarantee of completion)
- **message_delivered**: free‑form message injected
- **session_closed**: session cleanup completed
