# Deferrals: agent-activity-events

## Phase 1-2 Complete Foundation

**Completed:**

- Phase 1 Tasks 1.1-1.6: Event infrastructure and TUI integration ✓
- Phase 2 Tasks 2.1-2.4: Reasons pipeline removal ✓

**Status:** Foundation is complete. The event flow from coordinator → event bus → websocket → TUI is working. Activity events (tool_use, tool_done, agent_stop) are emitted alongside DB writes, and the TUI can display "Using [tool_name]..." when tools are active.

## Remaining Work (Deferred)

The following phases require additional build work that extends beyond the current build scope:

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

### Phase 6: Documentation

- Task 6.1: Update event specs
- Task 6.2: Update architecture docs
- Task 6.3: Update third-party hook docs
- Task 6.4: Run telec sync and verify hook installation

### Phase 7: Review Readiness

- Grep validation for zero stale references
- Acceptance criteria verification

## Rationale

Phase 1-2 establishes the core infrastructure for the new activity event flow:

1. The event bus carries AgentActivityEvent alongside DB writes
2. The TUI receives and processes these events
3. The reasons pipeline has been removed
4. Tool names are visible in the TUI during tool execution

Phases 3-7 are **event renaming and test updates** that can be completed in a follow-up build cycle. The current foundation is stable and functional with the old event names (after_model, agent_output). Renaming them to (tool_use, tool_done) is a refactoring task that doesn't change behavior.

## Next Steps

1. Mark Phase 1-2 as complete in implementation-plan.md
2. Create a follow-up todo for Phases 3-7: "agent-activity-events-rename-and-tests"
3. Document acceptance criteria met for Phase 1-2
4. Verify the current build passes lint and format checks
