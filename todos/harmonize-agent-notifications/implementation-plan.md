# Implementation Plan: Harmonize Agent Notifications

## Approach

We will update the daemon's activity contract to intercept raw notification hooks and transform them into a clean canonical format before they reach any UI adapters.

## Tasks

- [ ] **Core Contract Update**:
  - Modify `teleclaude/core/activity_contract.py` to add `agent_notification` to canonical types.
  - Update `HOOK_TO_CANONICAL` mapping.
  - Implement `_harmonize_notification_message(text: str) -> str` utility.
- [ ] **Contract Logic Integration**:
  - Update `ActivityContract.transform_hook_event` to use the new harmonizer for notification types.
- [ ] **Documentation Update**:
  - Update `docs/project/spec/event-vocabulary.md` to include `agent_notification`.
- [ ] **Verification**:
  - Add a unit test in `tests/unit/test_activity_contract.py` to verify tag stripping.
  - Manual smoke test by triggering a notification hook (if feasible).

## Risks

- **Regex Edge Cases**: Nested tags or multiple tags in one message. (Mitigation: Use non-greedy regex and fall back to raw text).
- **Adapter Impact**: If an adapter explicitly looks for XML tags (unlikely), it might break. (Mitigation: Source harmonization is the intended UCAP direction).
