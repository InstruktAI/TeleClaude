# Implementation Plan: Harmonize Agent Notifications

## Approach

Source-side harmonization of agent notification messages: strip internal XML tags at the
daemon entry point (`handle_notification`) and emit a canonical `agent_notification` event
through the standard activity contract. Existing notification delivery paths remain unchanged.

## Tasks

### 1. Tag stripping utility

- [ ] Add a `strip_signaling_tags(message: str) -> str` function in
      `teleclaude/core/agent_coordinator.py` (or a shared utility if one exists). - Strip `<task-notification>...</task-notification>` and similar XML wrapper tags. - Use regex: `re.sub(r'</?[\w-]+>', '', message).strip()` or targeted pattern. - Return raw message unchanged if no tags found. - Log at debug level when tags are stripped.

**Traces to**: FR-1 (Tag Stripping)

### 2. Apply stripping in handle_notification

- [ ] In `AgentCoordinator.handle_notification()` (`agent_coordinator.py:~1286`): - Call `strip_signaling_tags(payload.message)` to produce `clean_message`. - Pass `clean_message` to `notify_input_request()` (line ~1295). - Pass `clean_message` to `_forward_notification_to_initiator()` (line ~1299). - Keep `payload.message` available as the raw original for canonical event emission.

**Traces to**: FR-1 (Tag Stripping), FR-6 (Backward Compatibility)

### 3. Extend canonical activity vocabulary

- [ ] In `teleclaude/core/activity_contract.py`: - Extend `CanonicalActivityEventType` Literal to include `"agent_notification"`. - Add `"notification": "agent_notification"` to `HOOK_TO_CANONICAL`. - Add `message: str | None = None` field to `CanonicalActivityEvent`. - Update `_CANONICAL_TYPES` frozenset with `"agent_notification"`. - Update `serialize_activity_event()` to accept and pass through `message` kwarg.

**Traces to**: FR-2 (Canonical Event Type)

### 4. Extend AgentActivityEvent

- [ ] In `teleclaude/core/events.py`: - Add `message: str | None = None` field to `AgentActivityEvent` dataclass.

**Traces to**: FR-4 (AgentActivityEvent Extension)

### 5. Emit canonical event from handle_notification

- [ ] In `AgentCoordinator.handle_notification()`: - After the existing notification path, call `self._emit_activity_event()` with
      `event_type="notification"` and `message=clean_message` (the stripped text). - Update `_emit_activity_event()` to accept and forward `message` parameter to both
      `serialize_activity_event()` and `AgentActivityEvent`.

**Traces to**: FR-3 (Canonical Event Emission)

### 6. Update event vocabulary documentation

- [ ] In `docs/project/spec/event-vocabulary.md`: - Add `agent_notification` to the `canonical_outbound_activity_events` YAML list. - Add row to hook-to-canonical mapping table:
      `| notification | agent_notification | Agent needs input (cleaned) |` - Add `message` to optional canonical payload fields table:
      `| message | str or null | agent_notification with notification text |`

**Traces to**: FR-5 (Vocabulary Update)

### 7. Verification

- [ ] Run `make test` — existing tests pass.
- [ ] Run `make lint` — no new violations.
- [ ] Manual verification: trigger a notification from a Claude Code session and confirm: - tmux-injected message has no XML tags. - `agent_notification` event visible on event bus (via daemon logs at debug level). - Remote forwarding carries the cleaned message.

**Traces to**: Success Criteria 1-4

## Dependency Graph

```
[1] Tag stripping utility
 ↓
[2] Apply in handle_notification ← [3] Extend canonical vocabulary
                                  ← [4] Extend AgentActivityEvent
 ↓
[5] Emit canonical event
 ↓
[6] Update docs
 ↓
[7] Verification
```

Tasks 1, 3, and 4 are independent and can be implemented in parallel.
Task 2 depends on 1. Task 5 depends on 2, 3, and 4.
