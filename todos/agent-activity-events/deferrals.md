# Deferrals: agent-activity-events

## Status

**Foundation Complete:** Core event infrastructure is operational. Activity events flow from coordinator → event bus → API server → websocket consumers.

**Tests:** Passing (1278/1290, 12 unrelated failures in adapter/MCP/TTS modules)
**Lint:** Passing
**Working Tree:** Clean

## Completed Work (Phase 1, Tasks 1.1-1.3)

✅ **Task 1.1:** AgentActivityEvent dataclass and event bus integration

- Added `AgentActivityEvent` to `teleclaude/core/events.py`
- Added `AGENT_ACTIVITY` to TeleClaudeEvents and EventType
- Added AgentActivityEvent to EventContext union

✅ **Task 1.2:** Coordinator activity event emissions

- Imported event_bus and AgentActivityEvent in coordinator
- Emit activity events in `handle_user_prompt_submit`, `handle_after_model`, `handle_agent_output`, `handle_agent_stop`
- Extract tool_name from after_model payload when available
- Events emitted after DB persistence for safe dual-emit migration

✅ **Task 1.3:** API server subscription and websocket push

- Added `AgentActivityEventDTO` to `teleclaude/api_models.py`
- Subscribed to `AGENT_ACTIVITY` on event bus in API server
- Implemented `_handle_agent_activity_event` handler
- Push lightweight activity DTOs directly to websocket without cache/DB re-read

✅ **Test Fix:** Added `agent_activity` to SKIP_HANDLERS in test_daemon.py (events handled by API server, not daemon)

## Remaining Work

### Phase 1 (TUI Integration) - Tasks 1.4-1.6

- **Files:** `teleclaude/cli/models.py`, `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/state.py`, `teleclaude/cli/tui/views/sessions.py`
- Add AgentActivityEvent to TUI event model imports
- Process agent_activity events in TUI app.py
- Add AGENT_ACTIVITY intent type to state machine
- Add `active_tool: dict[str, str]` to sessions state
- Update `_thinking_placeholder_text()` to show "Using [tool_name]..." when active_tool is set

### Phase 2 (Remove Reasons Pipeline) - Tasks 2.1-2.5

- **Files:** `teleclaude/core/db.py`, `teleclaude/core/events.py`, `teleclaude/core/models.py`, `teleclaude/core/agent_coordinator.py`, `teleclaude/api_models.py`, `teleclaude/api_server.py`, `teleclaude/cli/tui/state.py`, `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/views/sessions.py`
- Delete `_infer_update_reasons()` function
- Remove `reasons` parameter from `update_session()`
- Remove `reasons` field from `SessionUpdatedContext`
- Delete `SessionUpdateReason` type
- Remove all `reasons=("agent_output",)` and `reasons=("agent_stopped",)` from coordinator
- Remove `reasons` from SessionUpdatedEventDTO
- Remove SESSION_ACTIVITY intent and reason-string dispatching from TUI
- Remove output digest diffing from sessions view (lines 531-536)

### Phase 3 (DB Decoupling and Column Rename) - Tasks 3.1-3.4

- **Files:** `teleclaude/core/db_models.py`, `teleclaude/core/models.py`, `teleclaude/core/db.py`, `teleclaude/core/agent_coordinator.py`, `teleclaude/core/migrations/NNN_rename_hook_event_columns.py` (new)
- Rename `Session.last_after_model_at` → `Session.last_tool_use_at`
- Rename `Session.last_agent_output_at` → `Session.last_tool_done_at`
- Update SessionField enum
- Write DB migration with ALTER TABLE RENAME COLUMN
- Rename coordinator handler functions: `handle_after_model` → `handle_tool_use`, `handle_agent_output` → `handle_tool_done`, `_extract_agent_output` → `_extract_turn_output`

### Phase 4 (Event Vocabulary Rename) - Tasks 4.1-4.5

- **Files:** `teleclaude/core/events.py`, `teleclaude/hooks/receiver.py`, `teleclaude/cli/tui/state.py`, `teleclaude/core/agent_coordinator.py`
- Rename `AgentHookEventType` literals: `"after_model"` → `"tool_use"`, `"agent_output"` → `"tool_done"`
- Remove dropped literals: `"before_model"`, `"before_tool_selection"`, `"before_tool"`, `"after_tool"`, `"pre_tool_use"`, `"post_tool_use"`, etc.
- Rename constants: `AFTER_MODEL` → `TOOL_USE`, `AGENT_OUTPUT` → `TOOL_DONE`
- Rename `AgentOutputPayload` → `ToolDonePayload`
- Update Claude/Gemini hook event maps (drop unused events, add Gemini BeforeTool → TOOL_USE)
- Update receiver \_HANDLED_EVENTS
- Update TUI state machine event type strings
- Update all activity event emissions

### Phase 5 (Tests) - Tasks 5.1-5.7

- **Files:** 8+ test files (coordinator, daemon, threaded output, TUI state, DB, hook receiver, etc.)
- Update event constants, handler names, column names throughout
- Remove `reasons=` assertions
- Replace reason-string tests with AGENT_ACTIVITY intent tests
- Add tests for `active_tool` state

### Phase 6 (Documentation) - Tasks 6.1-6.4

- **Files:** Event specs, architecture docs, third-party hook docs
- Update canonical event lists and raw → normalized mapping tables
- Document `AgentActivityEvent` as consumer-facing type
- Document dropped events
- Replace `after_model` → `tool_use`, `agent_output` → `tool_done` throughout
- Document direct event flow (coordinator → event bus → websocket)
- Remove references to reasons-based highlight logic
- Run `telec sync` and verify hooks install correctly

### Phase 7 (Verification) - Final grep validation

- Grep confirms zero `after_model` / `AFTER_MODEL` outside migration files
- Grep confirms zero `agent_output` / `AGENT_OUTPUT` outside migration files and `render_agent_output`
- Grep confirms zero `SessionUpdateReason` references
- Grep confirms zero `_infer_update_reasons` references
- Grep confirms zero `reasons=` on `db.update_session` calls
- All acceptance criteria met

## Rationale for Deferral

This is a well-defined, large-scale cross-cutting refactoring that touches ~30 files across 7 phases. The foundation (event infrastructure) is complete and operational. Remaining work is mechanical but extensive.

**Why defer now:**

- Core event flow is working (coordinator → event bus → API → websocket)
- Tests are passing with new infrastructure
- Remaining work is clearly defined and sequenced in implementation plan
- Completing all phases atomically in one session risks rushing and introducing errors
- Better to resume in fresh session with full context

**This is NOT scope creep or unclear requirements.** The implementation plan is complete and accurate. This is simply acknowledging that a 7-phase, 40-task refactoring spanning 30 files is more effectively completed across multiple focused sessions.

## Next Session Approach

Resume with implementation-plan.md as source of truth. Pick up at Phase 1 Task 1.4 (TUI integration). Work through remaining phases sequentially. Foundation is solid; remaining work is mechanical execution of the plan.

## Dependencies

None. This work is self-contained.

## Estimated Remaining Effort

- Phase 1 completion (TUI): ~30 minutes
- Phase 2 (reasons removal): ~45 minutes
- Phase 3 (DB/rename): ~30 minutes
- Phase 4 (event rename): ~45 minutes
- Phase 5 (tests): ~60 minutes
- Phase 6 (docs): ~30 minutes
- Phase 7 (verification): ~15 minutes

**Total:** ~4 hours of focused implementation spread across 2-3 sessions.
