# Event Contracts

## session_created

Session record created in SQLite and tmux name assigned. Emitted when the base session is ready for commands.

## session_removed

Session cleanup completed. Tmux session killed and database record closed/removed.

## session_updated

Emitted whenever session metadata changes in the database (title, active_agent, last_output, etc.). This is the primary signal for UI refresh.

## agent_event

Wrapper for agent lifecycle events received via hooks. Includes `event_type`:

- `session_start`: Agent process initialized and stabilized.
- `prompt`: Agent started a new turn (user input received).
- `stop`: Agent completed its turn (output generated).
- `notification`: Agent requested human input or sent a notification.
- `session_end`: Agent process terminated.

## error

Emitted when a command fails or a system-level error occurs. Includes `message` and `source`.

## system_command

Internal coordination event for system-level actions like `deploy` or `health_check`.
