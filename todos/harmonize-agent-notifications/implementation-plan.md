# Implementation Plan: Harmonize Agent Notifications

## Tasks

- [ ] **1. Extend canonical activity types** (`teleclaude/core/activity_contract.py`):
  - Add `"agent_notification"` and `"agent_error"` to `CanonicalActivityEventType`, `_CANONICAL_TYPES`, and `HOOK_TO_CANONICAL`.
  - Add `message: str | None = None` to `CanonicalActivityEvent`.
  - Add `message` param to `serialize_activity_event()` and pass through.

- [ ] **2. Add message field to consumer event** (`teleclaude/core/events.py`):
  - Add `message: str | None = None` to `AgentActivityEvent`.

- [ ] **3. Wire message through coordinator** (`teleclaude/core/agent_coordinator.py`):
  - Add `message: str | None = None` param to `_emit_activity_event()`, pass to serializer and event constructor.
  - In `handle_notification()`, call `_emit_activity_event(session_id, AgentHookEvents.AGENT_NOTIFICATION, message=str(message))`.
  - Add `handle_error()` method: extract message from payload, call `_emit_activity_event(session_id, AgentHookEvents.AGENT_ERROR, message=...)`.
  - Add `elif context.event_type == AgentHookEvents.AGENT_ERROR` branch to `handle_event()`.

- [ ] **4. Update event vocabulary** (`docs/project/spec/event-vocabulary.md`):
  - Add both `notification -> agent_notification` and `error -> agent_error` to mapping table.
  - Add `message` to optional payload fields.
  - Add both to canonical events list.

- [ ] **5. Tests**:
  - Serializer: `notification` and `error` hooks produce correct canonical types with `message`.
  - Coordinator: `handle_notification` and `handle_error` emit activity events.
