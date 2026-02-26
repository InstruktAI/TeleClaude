# Requirements: Harmonize Agent Notifications

## Problem

Raw agent notification hooks are currently leaking internal XML signaling tags (e.g., `<task-notification>`) directly into the event stream. This causes unharmonized, "ugly" output in client interfaces (Web, TUI) and violates the UCAP (Unified Client Adapter Pipeline) principle of source-side harmonization.

## Goal

Intercept raw `notification` hooks at the daemon source, strip internal signaling tags, and emit a clean, canonical `agent_notification` activity event.

## Functional Requirements

1.  **Event Mapping**: Add `notification` hook to the `HOOK_TO_CANONICAL` mapping in the activity contract.
2.  **Tag Stripping**: Implement robust extraction/stripping for `<task-notification>` tags.
3.  **Canonical Payload**: Emit a structured `agent_notification` event with a clean `message` field.
4.  **Vocabulary Update**: Update the project's event vocabulary documentation.
5.  **Backward Compatibility**: Preserve the original `hook_event_type` for auditability.

## Non-Functional Requirements

- **Efficiency**: Extraction logic must be fast (regex or simple string slicing).
- **Resilience**: Handle malformed or missing tags gracefully (fall back to raw text if stripping fails).
- **Observability**: Ensure the transition is visible in daemon logs.
