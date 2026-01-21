# AsyncAPI Requirements

## Purpose

Define the human‑readable requirements for the AsyncAPI spec. The spec is generated from these requirements.

## Event Channels

Events are pushed to the `/ws` channel based on client subscriptions:

- `session_created` / `session_updated` / `session_removed`
- `sessions_initial`
- `projects_initial` / `projects_updated`
- `todos_initial` / `todos_updated`
- `computer_updated`
- `agent_updated`

## Event Requirements

### Common fields

- `event` (type of event)
- `data` (payload)

### Event-specific payloads

- **session_updated**: Full `SessionSummary` DTO.
- **projects_updated**: `RefreshData` DTO with computer/project info.
- **todos_updated**: `RefreshData` DTO with computer/project info.
