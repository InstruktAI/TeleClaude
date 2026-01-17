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

| Command | Mode | Immediate Return | Completion Signal(s) |
| --- | --- | --- | --- |
| new_session | Hybrid | `session_id`, `tmux_session_name` | `session_created`, `agent_event(session_start)` |
| agent_restart | Async | success/error status | `agent_event(session_start)` |
| message | Async | success/error status | `session_updated` |
| end_session | Async | success/error status | `session_removed` |
| get_session_data | Sync | transcript content | n/a |
| next_prepare | Sync | instructions / status | n/a |
| next_work | Sync | instructions / status | n/a |

## Completion Semantics

- **session_created**: Session record + tmux name assigned.
- **agent_event(session_start)**: Agent process injected and stabilized.
- **agent_event(stop)**: Agent completed its turn (often triggers summarization).
- **session_updated**: Catch-all for metadata updates (title, last activity).
- **session_removed**: Session cleanup completed.
