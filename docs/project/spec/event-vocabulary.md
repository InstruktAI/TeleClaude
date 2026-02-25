---
id: 'project/spec/event-vocabulary'
type: 'spec'
scope: 'project'
description: 'Authoritative vocabulary for TeleClaude internal and external events.'
---

# Event Vocabulary — Spec

## Definition

The Event Vocabulary defines the shared language used between TeleClaude adapters, the daemon, and external clients.

## Machine-Readable Surface

```yaml
standard_events:
  - session_started
  - session_closed
  - session_updated
  - agent_event
  - agent_activity
  - error
  - system_command

agent_hook_events:
  - session_start
  - user_prompt_submit
  - tool_use
  - tool_done
  - agent_stop
  - session_end
  - notification
  - error

canonical_outbound_activity_events:
  - user_prompt_submit
  - agent_output_update
  - agent_output_stop
```

## Canonical Outbound Activity Vocabulary

Canonical activity events are the stable outbound vocabulary for all consumer adapters
(Web, TUI, hooks). They are derived from agent hook events via the canonical contract
(`teleclaude/core/activity_contract.py`).

### Hook-to-canonical mapping

| Hook event           | Canonical type        | Notes                              |
| -------------------- | --------------------- | ---------------------------------- |
| `user_prompt_submit` | `user_prompt_submit`  | User turn start signal             |
| `tool_use`           | `agent_output_update` | Agent working: tool call initiated |
| `tool_done`          | `agent_output_update` | Agent working: tool call completed |
| `agent_stop`         | `agent_output_stop`   | Agent turn complete                |

### Canonical payload fields

All canonical outbound activity events carry the following required fields:

| Field             | Type | Description                                              |
| ----------------- | ---- | -------------------------------------------------------- |
| `session_id`      | str  | TeleClaude session identifier                            |
| `canonical_type`  | str  | Canonical activity event type (vocabulary above)         |
| `hook_event_type` | str  | Original hook event type (preserved for compatibility)   |
| `timestamp`       | str  | ISO 8601 UTC timestamp                                   |
| `message_intent`  | str  | Routing intent (`ctrl_activity` for all activity events) |
| `delivery_scope`  | str  | Routing scope (`CTRL` for all activity events)           |

Optional fields (event-specific):

| Field          | Type        | Present when                         |
| -------------- | ----------- | ------------------------------------ |
| `tool_name`    | str or null | `agent_output_update` with tool info |
| `tool_preview` | str or null | `agent_output_update` with preview   |
| `summary`      | str or null | `agent_output_stop` with summary     |

### Routing metadata

Activity events are control-plane signals (UI activity indicators, turn lifecycle).
They do not carry user-visible content and use `CTRL` delivery scope.

See `docs/project/spec/session-output-routing.md` for scope definitions.

### Compatibility notes

During phased UCAP migration, the `hook_event_type` field preserves the original
hook-level event type so existing consumers that inspect `type`/`event_type` remain
functional. Downstream adapters (`ucap-web-adapter-alignment`, `ucap-tui-adapter-alignment`)
will migrate to consume `canonical_type` directly in later phases.

## Constraints

- Removal or renaming of a standard event type is a breaking change (Minor bump).
- Changes to the mapping of agent-specific hooks to these standard types are breaking changes.
- Adding a new event type is a feature addition (Minor bump).
- Canonical outbound activity vocabulary is versioned via the contract module; renaming
  canonical types requires a compatibility migration window.
