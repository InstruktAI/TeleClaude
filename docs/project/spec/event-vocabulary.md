---
id: 'project/spec/event-vocabulary'
type: 'spec'
scope: 'project'
description: 'Authoritative vocabulary for TeleClaude internal and external events.'
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
  - tool_use
  - tool_done
  - agent_stop
  - session_end
  - error

canonical_outbound_activity_events:
  - user_prompt_submit
  - agent_output_update
  - agent_output_stop
```

### Canonical Outbound Activity Vocabulary

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

### Core Event Taxonomy

The platform registers the following root-level event families as built-in catalog entries.
Each family uses a flat prefix pattern. The existing `system.*` and `domain.*` families
coexist alongside the newer flat families — both patterns are valid.

| Family         | Levels                    | Visibility | Description                              |
| -------------- | ------------------------- | ---------- | ---------------------------------------- |
| `system`       | INFRASTRUCTURE, OPERATIONAL | CLUSTER  | Platform health and worker lifecycle     |
| `domain`       | WORKFLOW, BUSINESS        | LOCAL      | Domain-specific events (e.g. software-development) |
| `node`         | INFRASTRUCTURE, OPERATIONAL | CLUSTER  | Node presence and metadata updates       |
| `deployment`   | WORKFLOW, BUSINESS        | LOCAL      | Deployment lifecycle (start → complete → fail → rollback) |
| `content`      | WORKFLOW, BUSINESS        | LOCAL      | Content capture, processing, publication |
| `notification` | WORKFLOW, BUSINESS        | LOCAL      | Escalation and resolution meta-events    |
| `schema`       | OPERATIONAL               | CLUSTER    | Schema change proposals and adoptions    |

### Event type registration

All built-in event types are registered in `teleclaude.events/schemas/` and wired
into `register_all()` in `teleclaude.events/schemas/__init__.py`. Domain-specific
cartridges may register additional types in the same catalog.

### Prepare lifecycle events (software-development domain)

The `domain.software-development.prepare.*` family covers every observable transition
in the prepare state machine. All events carry `slug` as a payload field unless noted.

| Event type | Level | Description | Key payload fields |
|---|---|---|---|
| `prepare.phase_skipped` | WORKFLOW | Phase skipped via split inheritance | `slug`, `phase`, `reason` |
| `prepare.input_consumed` | WORKFLOW | Input consumed by discovery, requirements production started | `slug` |
| `prepare.artifact_produced` | WORKFLOW | Artifact written and lifecycle-tracked in state | `slug`, `artifact`, `digest` |
| `prepare.artifact_invalidated` | OPERATIONAL | Upstream change cascaded staleness to artifact | `slug`, `artifact` |
| `prepare.finding_recorded` | WORKFLOW | Finding recorded by reviewer with severity and summary | `slug`, `finding_id`, `severity`, `summary` |
| `prepare.finding_resolved` | WORKFLOW | Finding resolved via auto-remediation or human action | `slug`, `finding_id`, `resolution_method` |
| `prepare.review_scoped` | WORKFLOW | Scoped re-review dispatched targeting open findings | `slug`, `finding_ids` |
| `prepare.split_inherited` | WORKFLOW | Child todo inherited parent's approved prepare phase | `parent_slug`, `child_slug`, `inherited_phase` |

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
