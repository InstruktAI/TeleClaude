# Implementation Plan: Harmonize Agent Notifications

## Approach

We will update the daemon's activity contract and coordinator to intercept raw notification and error hooks, harmonizing them into a clean canonical format using selective property plugging.

## Tasks

- [ ] **Event Schema Expansion**:
  - Add `message: str | None = None` to `CanonicalActivityEvent` in `teleclaude/core/activity_contract.py`.
  - Add `message: str | None = None` to `AgentActivityEvent` in `teleclaude/core/events.py`.
- [ ] **Core Contract Mapping**:
  - Update `HOOK_TO_CANONICAL` in `teleclaude/core/activity_contract.py`:
    - `notification` -> `agent_notification`
    - `error` -> `agent_error`
- [ ] **Coordinator Logic Alignment**:
  - Update `AgentCoordinator.handle_notification` to plug clean semantic fields from the payload instead of passing raw stringified data.
  - Update `AgentCoordinator._emit_activity_event` to support the new `message` field.
- [ ] **Documentation Update**:
  - Update `docs/project/spec/event-vocabulary.md` to include `agent_notification` and `agent_error`.
- [ ] **Verification**:
  - Verify that `notification` events across all outputs (Web, TUI, tmux/Discord) no longer contain XML implementation markers.
