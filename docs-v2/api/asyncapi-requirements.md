# AsyncAPI Requirements

## Purpose

Define the human‑readable requirements for the AsyncAPI spec. The spec is generated from these requirements.

## Event Channels

Events are published to channels named after the event:

- `events/session_created`
- `events/agent_ready`
- `events/task_delivered`
- `events/agent_resumed`
- `events/agent_restarted`
- `events/command_delivered`
- `events/message_delivered`
- `events/session_closed`
- `events/command_failed`

## Event Requirements

### Common fields

- `request_id`
- `event`
- `timestamp`

`request_id` is the public name. Internally this maps to the command pipeline’s `command_id`.

### Event-specific fields

- Defined in `docs/event-contracts.md`
