# Implementation Plan: Harmonize Agent Notifications

## Approach

We will update the daemon's activity contract and coordinator to intercept raw notification and error hooks, harmonizing them into a clean canonical format. This involves expanding the event schema to support message payloads and ensuring all handled hooks emit UI activity signals.

## Tasks

- [ ] **Event Schema Expansion**:
  - Add `message: str | None = None` to `CanonicalActivityEvent` in `teleclaude/core/activity_contract.py`.
  - Add `message: str | None = None` to `AgentActivityEvent` in `teleclaude/core/events.py`.
- [ ] **Core Contract Update**:
  - Modify `teleclaude/core/activity_contract.py` to add `agent_notification` and `agent_error` to canonical types.
  - Update `HOOK_TO_CANONICAL` mapping:
    - `notification` -> `agent_notification`
    - `error` -> `agent_error`
  - Implement `_harmonize_notification_message(text: str) -> str` utility to strip `<task-notification>` tags.
  - Update `serialize_activity_event` to accept and process the `message` field.
- [ ] **Agent Coordinator Alignment**:
  - Update `AgentCoordinator.handle_notification` to call `self._emit_activity_event`.
  - Update `AgentCoordinator._emit_activity_event` to pass the `message` field to `serialize_activity_event`.
- [ ] **Documentation Update**:
  - Update `docs/project/spec/event-vocabulary.md` to include `agent_notification` and `agent_error`.
- [ ] **Verification**:
  - Add unit tests in `tests/unit/test_activity_contract.py` for tag stripping and new mappings.
  - Verify that `notification` events now carry `message_intent: ctrl_activity` and `delivery_scope: CTRL`.

## Risks

- **Overloading Activity Stream**: High-frequency notifications could spam the UI. (Mitigation: Notifications are typically low-frequency user-action requests).
- **Schema Drift**: Downstream consumers (Web/TUI) must be updated to look for the new `message` field. (Mitigation: Part of the broader UCAP alignment).
