# Requirements: Harmonize Agent Notifications

## Problem

`notification` and `error` agent hooks bypass the canonical activity contract. `handle_notification()` routes to tmux listeners and remote initiators but never emits a `CanonicalActivityEvent`. `error` hooks have no handler at all — they silently fall through `handle_event()`. Web and TUI never see either event type.

## Goal

Route `notification` and `error` hooks through the canonical activity contract so all consumers receive `agent_notification` and `agent_error` events.

## Functional Requirements

1. Add `agent_notification` and `agent_error` to `CanonicalActivityEventType` and `_CANONICAL_TYPES`.
2. Add `"notification": "agent_notification"` and `"error": "agent_error"` to `HOOK_TO_CANONICAL`.
3. Add `message: str | None = None` to `CanonicalActivityEvent`, `AgentActivityEvent`, and `serialize_activity_event()`.
4. Add `message` parameter to `_emit_activity_event()` and wire it through.
5. Call `_emit_activity_event()` in `handle_notification()` with `payload.message`.
6. Add `handle_error()` to the coordinator, emit `_emit_activity_event()` with the error message. Wire it into `handle_event()`.
7. Update `docs/project/spec/event-vocabulary.md` with both new canonical types.

## Out of Scope

- Adapter-side rendering of these events.
