# Implementation Plan: Harmonize Agent Notifications

## Tasks

- [x] **1. Extend canonical activity types** (`teleclaude/core/activity_contract.py`):
  - Add `"agent_notification"` to `CanonicalActivityEventType`, `_CANONICAL_TYPES`, and `HOOK_TO_CANONICAL`.
  - Add `message: str | None = None` to `CanonicalActivityEvent`.
  - Add `message` param to `serialize_activity_event()` and pass through.

- [x] **2. Add message field to consumer event** (`teleclaude/core/events.py`):
  - Add `message: str | None = None` to `AgentActivityEvent`.

- [x] **3. Wire message through coordinator** (`teleclaude/core/agent_coordinator.py`):
  - Add `message: str | None = None` param to `_emit_activity_event()`, pass to serializer and event constructor.
  - In `handle_notification()`, call `_emit_activity_event(session_id, AgentHookEvents.AGENT_NOTIFICATION, message=str(message))`.

- [x] **4. Update event vocabulary** (`docs/project/spec/event-vocabulary.md`):
  - Add `notification -> agent_notification` to mapping table.
  - Add `message` to optional payload fields.
  - Add `agent_notification` to canonical events list.

- [x] **5. Tests**:
  - Serializer: `notification` hook produces `agent_notification` canonical type with `message`.
  - Coordinator: `handle_notification` emits activity event.
