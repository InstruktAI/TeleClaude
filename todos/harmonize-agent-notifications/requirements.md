# Requirements: Harmonize Agent Notifications

## Problem

`notification` hooks bypass the canonical activity contract. `handle_notification()` routes to tmux listeners and remote initiators but never emits a `CanonicalActivityEvent`. Web and TUI never see notification events.

## Goal

Route `notification` hooks through the canonical activity contract so all consumers receive `agent_notification` events.

## Functional Requirements

1. Add `agent_notification` to `CanonicalActivityEventType` and `_CANONICAL_TYPES`.
2. Add `"notification": "agent_notification"` to `HOOK_TO_CANONICAL`.
3. Add `message: str | None = None` to `CanonicalActivityEvent`, `AgentActivityEvent`, and `serialize_activity_event()`.
4. Add `message` parameter to `_emit_activity_event()` and wire it through.
5. Call `_emit_activity_event()` in `handle_notification()` with `payload.message`.
6. Update `docs/project/spec/event-vocabulary.md` with the new canonical type.

## Out of Scope

- `error` hooks (already handled via `ErrorEventContext` → `TeleClaudeEvents.ERROR` in daemon.py:753).
- Adapter-side rendering of `agent_notification` events.
