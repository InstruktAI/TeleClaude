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
```

## Constraints

- Removal or renaming of a standard event type is a breaking change (Minor bump).
- Changes to the mapping of agent-specific hooks to these standard types are breaking changes.
- Adding a new event type is a feature addition (Minor bump).
