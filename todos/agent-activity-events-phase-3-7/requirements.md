# Requirements: agent-activity-events-phase-3-7

## Goal

Complete the agent-activity-events pipeline by renaming DB columns and event vocabulary from legacy names (`after_model`/`agent_output`) to semantic names (`tool_use`/`tool_done`), adding comprehensive test coverage for event emission and broadcast, and updating documentation.

## Scope

### In scope:

- DB column rename: `last_after_model_at` → `last_tool_use_at`, `last_agent_output_at` → `last_tool_done_at`
- Event vocabulary rename: `after_model` → `tool_use`, `agent_output` → `tool_done`
- DB migration (007) for column rename
- Update all code references: models, coordinator, events, hooks, TUI, receiver, DB access
- Update all test files for new vocabulary
- Write new tests for AgentActivityEvent emission and API server broadcast
- Update documentation (event specs, architecture docs)
- Final grep validation for zero stale references

### Out of scope:

- New event types beyond the rename
- Changes to `agent_stop` or `user_prompt_submit` vocabulary
- Hook installation changes (hooks still map from agent-native names to internal types)

## Success Criteria

- [x] All DB columns renamed (`last_tool_use_at`, `last_tool_done_at`)
- [x] All event types use new vocabulary (`tool_use`, `tool_done`)
- [x] Zero references to old event names (`after_model`, `agent_output`) in production code
- [x] Comprehensive test coverage for event emission and broadcast
- [x] All test files pass with new column/event names
- [x] Documentation reflects new event vocabulary

## Constraints

- SQLite requires table recreation for column rename (no ALTER TABLE RENAME COLUMN in older versions)
- Migration must be idempotent and handle both old and new column states
- Hook event maps translate from agent-native names to internal types — the internal type changes, not the agent-native names

## Risks

- Migration on existing databases with data in old columns — migration must copy data
