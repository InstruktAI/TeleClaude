# Agent Activity Events: Phase 3-7 Completion

## Context

Phase 1-2 of agent-activity-events established the core infrastructure:

- Event bus carries AgentActivityEvent alongside DB writes
- TUI receives and processes these events
- Reasons pipeline removed (4 test regressions fixed)
- Tool names visible in TUI during tool execution

The foundation is stable and functional with the old event names (after_model, agent_output). This todo completes the remaining phases: DB column rename, event vocabulary rename, comprehensive tests, documentation updates, and final validation.

## Scope

### Phase 3: DB Decoupling and Column Rename

- Task 3.1: Rename DB model columns (last_after_model_at → last_tool_use_at, last_agent_output_at → last_tool_done_at)
- Task 3.2: Update DB access layer column references
- Task 3.3: Write DB migration
- Task 3.4: Rename coordinator column references and handler names

### Phase 4: Event Vocabulary Rename

- Task 4.1: Rename type literals and constants (after_model → tool_use, agent_output → tool_done)
- Task 4.2: Update hook event maps (Claude/Gemini)
- Task 4.3: Update receiver forwarding allowlist
- Task 4.4: Update TUI state machine event type strings
- Task 4.5: Update all activity event emissions

### Phase 5: Tests

- Task 5.1-5.7: Update all test files for new event types, handler names, column names, and reasons removal
- **Critical gap:** Write tests for AgentActivityEvent emission and API server broadcast
  - Verify `event_bus.emit(AGENT_ACTIVITY, ...)` is called
  - Validate `AgentActivityEvent` fields (session_id, event_type, tool_name, timestamp)
  - Test API server `_handle_agent_activity_event`
  - Test TUI state machine `AGENT_ACTIVITY` intent handling

### Phase 6: Documentation

- Task 6.1: Update event specs
- Task 6.2: Update architecture docs
- Task 6.3: Update third-party hook docs
- Task 6.4: Run telec sync and verify hook installation

### Phase 7: Review Readiness

- Grep validation for zero stale references
- Acceptance criteria verification

## Acceptance Criteria

1. All DB columns renamed (last_tool_use_at, last_tool_done_at)
2. All event types use new vocabulary (tool_use, tool_done)
3. Zero references to old event names (after_model, agent_output) in codebase
4. Comprehensive test coverage for event emission and broadcast
5. All test files pass with new column/event names
6. Documentation reflects new event vocabulary
7. Hook specs updated and hooks installed via telec sync

## Risk Assessment

**Old event names remain (pre-Phase 4):**

- Risk: Developer confusion between `after_model` vs. `tool_use` duality
- Mitigation: Complete Phase 4 before any new features touch the event pipeline

**No activity event tests (pre-Phase 5):**

- Risk: Regressions in event emission go undetected
- Mitigation: Manual TUI testing during development + Phase 5 must complete before next major event pipeline change

**DB column names stale (pre-Phase 3):**

- Risk: Confusion about what timestamps mean
- Mitigation: Column comments are accurate; complete Phase 3 before adding new timestamp columns

## Test Status

**4 Critical Regressions Fixed (commit 714a7c5c):**

1. `test_handle_agent_stop_skips_whitespace_only_agent_output` - removed reasons assertions
2. `test_update_session_notifies_subscribers` - expect session directly (not dict with reasons)
3. `test_digest_update_with_reasons_still_emits_session_updated` - renamed to test_field_update_emits_session_updated
4. `test_threaded_output_subsequent_update_edits_message` - check cursor not updated (don't require update_session call)

**14 Remaining Test Failures (Unrelated):**

All 14 remaining test failures are pre-existing issues unrelated to agent-activity-events:

- **Adapter boundary tests (2)**: pre-existing adapter API issues
- **Checkpoint hook tests (3)**: pre-existing checkpoint timing issues
- **MLX TTS tests (4)**: pre-existing TTS backend refactoring needed
- **Next machine tests (4)**: pre-existing next-machine HITL output format changes
- **MCP wrapper tests (1)**: pre-existing role-based tool blocking issue

These failures existed before agent-activity-events work began and are tracked separately.
