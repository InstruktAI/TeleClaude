# Requirements: Harmonize Agent Notifications

## Problem

Agent notification messages (input requests from sessions needing attention) are forwarded
to listener sessions with raw, unprocessed content. When Claude Code emits notifications
containing internal XML signaling tags (e.g., `<task-notification>`), these leak through
`handle_notification()` → `notify_input_request()` → tmux injection without cleaning.

This violates the UCAP principle of source-side harmonization: raw data should be cleaned
at the daemon before reaching any consumer.

Additionally, notifications have no canonical event representation. The activity contract
(`activity_contract.py`) maps only turn-lifecycle hooks (`user_prompt_submit`, `tool_use`,
`tool_done`, `agent_stop`). Notifications are control-plane events — semantically different
from activity events — but they still need a canonical form for Web/TUI adapters to consume
without relying on tmux injection.

## Goal

1. Clean notification messages at the source before any forwarding.
2. Emit a canonical `agent_notification` event so all adapters can consume notification
   state through the standard event bus.

## Functional Requirements

1. **Tag Stripping**: Extract clean text from notification messages by stripping internal
   XML signaling tags (`<task-notification>`, etc.) in `handle_notification()` before
   forwarding to `notify_input_request()` or `_forward_notification_to_initiator()`.

2. **Canonical Event Type**: Add `agent_notification` to the canonical activity vocabulary.
   - Extend `CanonicalActivityEventType` with `"agent_notification"`.
   - Add `"notification"` → `"agent_notification"` to `HOOK_TO_CANONICAL`.
   - Add optional `message: str | None` field to `CanonicalActivityEvent`.

3. **Canonical Event Emission**: Emit `agent_notification` via `_emit_activity_event()`
   in `handle_notification()` alongside the existing notification path (additive, not
   replacement). The cleaned message populates the `message` field.

4. **AgentActivityEvent Extension**: Add `message: str | None = None` to
   `AgentActivityEvent` in `events.py` so the bus can carry the notification text.

5. **Vocabulary Update**: Update `docs/project/spec/event-vocabulary.md`:
   - Add `agent_notification` to `canonical_outbound_activity_events`.
   - Add `notification` → `agent_notification` row to the hook-to-canonical mapping table.
   - Add `message` to the optional canonical payload fields table.

6. **Backward Compatibility**: Preserve original `hook_event_type` (`"notification"`)
   in the canonical event for auditability. The existing tmux injection + remote
   forwarding paths continue to work with cleaned messages.

## Non-Functional Requirements

- **Efficiency**: Tag stripping uses regex or simple string operations. No LLM calls.
- **Resilience**: If stripping fails, fall back to the raw message (never drop notifications).
- **Observability**: Log when tags are stripped (debug level) and when stripping falls back.

## Explicit Non-Scope

- Error hook (`error`) harmonization — separate concern, different semantics.
- Changing the notification delivery path (tmux injection + remote forwarding stays).
- Web/TUI adapter changes to consume `agent_notification` — deferred to adapter work.

## Success Criteria

1. Notification messages forwarded to listener sessions contain no XML signaling tags.
2. `agent_notification` events appear on the event bus with a clean `message` field.
3. Existing notification delivery (tmux injection, remote forwarding, DB flag) works unchanged.
4. Event vocabulary spec reflects the new canonical type.
