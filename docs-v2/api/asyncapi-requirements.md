# AsyncAPI Requirements

## Purpose
Define the human‑readable requirements for the AsyncAPI spec. The spec is generated from these requirements.

## Event Channels
Events are published to channels named after the event:
- `events/session_created`
- `events/agent_ready`
- `events/task_started`
- `events/agent_resumed`
- `events/agent_restarted`
- `events/agent_command_delivered`
- `events/message_delivered`
- `events/session_ended`
- `events/command_failed`

## Event Requirements

### Common fields
- `command_id`
- `event`
- `timestamp`

### Event-specific fields
- Defined in `docs/event-contracts.md`
