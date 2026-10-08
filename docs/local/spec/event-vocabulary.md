---
description: 'Authoritative vocabulary for TeleClaude internal and external events.'
visibility: 'public'
---

# Event Vocabulary — Spec

## What it is

The Event Vocabulary defines the shared language used between TeleClaude adapters, the daemon, and external clients.

## Canonical fields

### Machine-Readable Surface

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
  - pre_tool_use
  - post_tool_use
  - agent_stop
  - agent_idle
  - agent_blocked
  - agent_turn_failed
  - error

canonical_outbound_activity_events:
  - user_prompt_submit
  - agent_output_update
  - agent_stop
```

`agent_blocked` and `agent_turn_failed` are the distress kinds: a session
waiting on an approval or input decision it cannot resolve itself, and a turn
terminated by a runtime or provider failure. Which native provider event
produces each is owned by `local/projects/teleclaude/spec/hook-normalized-events`. They add no
canonical outbound activity type. `error` remains the platform's internal error
channel and no longer carries any provider turn state.

### Canonical Outbound Activity Vocabulary

Canonical activity events are the stable outbound vocabulary for all consumer adapters
(TUI, hooks). They are derived from agent hook events via the canonical contract
(`teleclaude/core/activity_contract.py`).

### Hook-to-canonical mapping

| Hook event           | Canonical type        | Notes                              |
| -------------------- | --------------------- | ---------------------------------- |
| `user_prompt_submit` | `user_prompt_submit`  | User turn start signal             |
| `pre_tool_use`       | `agent_output_update` | Agent working: tool call initiated |
| `agent_stop`         | `agent_stop`          | Agent turn complete                |

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
| `summary`      | str or null | `agent_stop` with summary            |

### Routing metadata

Activity events are control-plane signals (UI activity indicators, turn lifecycle).
They do not carry user-visible content and use `CTRL` delivery scope.

See `docs/local/spec/session-output-routing.md` for scope definitions.

### Compatibility notes

During phased UCAP migration, the `hook_event_type` field preserves the original
hook-level event type so existing consumers that inspect `type`/`event_type` remain
functional. Downstream adapters (`ucap-tui-adapter-alignment`)
will migrate to consume `canonical_type` directly in later phases.

### Event type names

Every platform event type name is dotted, and its first segment names the
type's owner:

| First segment                                        | Owner                          | Covers                                                                                                |
| ---------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `teleclaude`                                         | the platform itself            | its own operation: sessions, job runs, deployments, node presence, configuration, event-stream health |
| a published domain's name, such as `sdlc`            | that domain                    | the domain's work, such as todo preparation, build, review, and integration                           |
| the domain an inbound source declares, such as `erp` | the external producer's domain | events relayed from external systems, named `<domain>.<name>`                                         |

Each type's name, declaration, and data fields are read from the generated
catalog with `telec events list` and `telec events schema <type>`; this
vocabulary does not restate them.

A `teleclaude` type that reports the state of a thing ends in a state segment
under its lifecycle family, from the closed vocabulary the event catalog owns
(`local/projects/teleclaude/spec/domain/event-catalog`).

### Expansion Joint

`EventEnvelope` accepts additional fields beyond its declared schema via
`model_config = ConfigDict(extra="allow")`. This is the mechanism for organic schema
evolution: nodes can attach fields that are not yet part of the formal vocabulary,
and useful fields are promoted through governance.

**Wire format:** Extra fields are JSON-encoded into a single `_extra` key in the Redis
stream dict during `to_stream_dict()`, and restored from `_extra` in `from_stream_dict()`.
This preserves the flat `dict[str, str]` Redis stream constraint.

**Promotion path:** Extra fields start in `_extra`, gain usage across nodes, are proposed
via `schema.proposed`, adopted via `schema.adopted`, and finally declared as first-class
`EventEnvelope` fields in a schema-version bump.

### JSON Schema for External Consumers

The canonical JSON Schema document for `EventEnvelope` can be generated without importing
Python code:

```bash
python -m teleclaude.events.schema_export [output_path]
```

Or programmatically:

```python
from teleclaude.events.schema_export import export_json_schema, export_json_schema_file

schema = export_json_schema()           # returns dict
export_json_schema_file(Path("envelope-schema.json"))  # writes to disk
```

The schema is versioned by `SCHEMA_VERSION` in `teleclaude.events/envelope.py` and
regenerated on each release that changes the envelope structure.

## Known caveats

- Removal or renaming of a standard event type is a breaking change (Minor bump).
- Changes to the mapping of agent-specific hooks to these standard types are breaking changes.
- Adding a new event type is a feature addition (Minor bump).
- Canonical outbound activity vocabulary is versioned via the contract module; renaming
  canonical types requires a compatibility migration window.

## See Also

- docs/local/spec/domain/agent_runtime.md
