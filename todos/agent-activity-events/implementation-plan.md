# Implementation Plan: Agent Activity Events

## Behavioral model

Two observable agent modes during a turn: **generating** (model produces text + reasoning, fused) and **executing** (a tool is running). Four activity events drive the TUI:

```
USER ──user_prompt_submit──▸ GENERATING ──tool_use──▸ EXECUTING ──tool_done──▸ GENERATING ──agent_stop──▸ STOPPED
                                              │                        │                          │
                                              │ (tool_name)            │ (transcript)             │ (final output)
                                              ▼                        ▼                          ▼
                                         "Using Read..."          "thinking..."              permanent highlight
```

## Architecture change

**Current flow** (DB-mediated, 4 hops):

```
coordinator → db.update_session(reasons=...) → event_bus SESSION_UPDATED
  → API server re-reads session → builds SessionSummary → pushes to cache
  → cache fires change → serializes full DTO + reasons → websocket → TUI parses reasons
```

**New flow** (direct, 1 hop):

```
coordinator → event_bus.emit(AGENT_ACTIVITY, AgentActivityEvent(...))
  → API server serializes lightweight DTO → websocket → TUI reacts to typed event
  (DB write happens in parallel as a persistence side-effect, no event emission)
```

---

## Phase 1: Event type and bus wiring

### Task 1.1: Define `AgentActivityEvent` dataclass

**File:** `teleclaude/core/events.py`

- [ ] Add `AgentActivityEvent` dataclass:
  ```python
  @dataclass(frozen=True)
  class AgentActivityEvent:
      session_id: str
      event_type: AgentHookEventType
      tool_name: str | None = None
      timestamp: str | None = None
  ```
- [ ] Add `AGENT_ACTIVITY = "agent_activity"` to `TeleClaudeEvents`
- [ ] Add `AgentActivityEvent` to the `EventContext` union

### Task 1.2: Coordinator emits activity events

**File:** `teleclaude/core/agent_coordinator.py`

Coordinator already knows the event type. Emit it directly, alongside existing DB writes (dual-emit for safe migration).

- [ ] In `handle_after_model()`: emit `AgentActivityEvent(type="after_model", tool_name=...)` after DB write
- [ ] In `handle_agent_output()` / `_maybe_send_incremental_output()`: emit `AgentActivityEvent(type="agent_output")` after DB write
- [ ] In `handle_agent_stop()`: emit `AgentActivityEvent(type="agent_stop")` after DB write
- [ ] In `handle_user_prompt_submit()`: emit `AgentActivityEvent(type="user_prompt_submit")`

Note: uses OLD event type names during Phase 1. Rename happens in Phase 4.

### Task 1.3: API server subscribes and pushes to websocket

**File:** `teleclaude/api_server.py`

- [ ] Subscribe to `AGENT_ACTIVITY` event on bus
- [ ] Handler serializes lightweight `AgentActivityEventDTO` and pushes directly to websocket subscribers — no cache update, no session re-read
- [ ] Add `AgentActivityEventDTO` to `teleclaude/api_models.py`:
  ```python
  class AgentActivityEventDTO(BaseModel):
      event: Literal["agent_activity"] = "agent_activity"
      session_id: str
      type: str
      tool_name: str | None = None
  ```

### Task 1.4: TUI receives and parses activity events

**Files:** `teleclaude/cli/models.py`, `teleclaude/cli/tui/app.py`

- [ ] Add `AgentActivityEvent` to TUI event model imports
- [ ] In `app.py` `process_events()`: handle `AgentActivityEvent` alongside existing `SessionUpdatedEvent`
- [ ] Dispatch new `AGENT_ACTIVITY` intent with `event_type`, `session_id`, `tool_name`

### Task 1.5: TUI state machine handles activity events

**File:** `teleclaude/cli/tui/state.py`

- [ ] Add `AGENT_ACTIVITY` to `IntentType`
- [ ] Add handler that branches on `event_type`:
  - `user_prompt_submit` → add to `input_highlights`, clear output highlights
  - `after_model` → add to `temp_output_highlights`, store tool_name in new `active_tool` dict
  - `agent_output` → add to `temp_output_highlights`, clear `active_tool`
  - `agent_stop` → clear input/temp, add to `output_highlights`
- [ ] Add `active_tool: dict[str, str]` to sessions state (session_id → tool_name)

Note: still uses OLD event type names. Rename happens in Phase 4.

### Task 1.6: TUI shows tool name during tool_use

**File:** `teleclaude/cli/tui/views/sessions.py`

- [ ] Update `_thinking_placeholder_text()` (or add parallel function) to check `active_tool` dict
- [ ] If `active_tool[session_id]` is set → show "Using [tool_name]..." instead of "thinking..."
- [ ] When `active_tool` is cleared (on `agent_output`/`agent_stop`) → fall back to "thinking..."

---

## Phase 2: Remove reasons pipeline

Now that TUI consumes activity events directly, cut the old path.

### Task 2.1: Remove reasons from session update path

**File:** `teleclaude/core/db.py`

- [ ] Delete `_infer_update_reasons()` function entirely
- [ ] Remove `reasons` parameter from `update_session()`
- [ ] Remove `reasons` from `SessionUpdatedContext` emission — just emit with `session_id` and `updated_fields`

**File:** `teleclaude/core/events.py`

- [ ] Remove `reasons` field from `SessionUpdatedContext`

**File:** `teleclaude/core/models.py`

- [ ] Delete `SessionUpdateReason` type entirely

### Task 2.2: Remove reasons from coordinator

**File:** `teleclaude/core/agent_coordinator.py`

- [ ] Remove all `reasons=("agent_output",)` and `reasons=("agent_stopped",)` from `db.update_session()` calls
- [ ] DB writes now only pass persistence fields (cursor timestamps, digest, status)

### Task 2.3: Remove reasons from API models and websocket

**File:** `teleclaude/api_models.py`

- [ ] Remove `reasons` field from `SessionUpdatedEventDTO`

**File:** `teleclaude/api_server.py`

- [ ] Remove `reasons` extraction from `_on_cache_change` for `session_updated` events
- [ ] Cache update in `_handle_session_updated_event` no longer passes reasons

### Task 2.4: Remove reasons from TUI

**Files:** `teleclaude/cli/tui/state.py`, `teleclaude/cli/tui/app.py`

- [ ] Remove `SESSION_ACTIVITY` intent type and its handler (replaced by `AGENT_ACTIVITY`)
- [ ] Remove reason-string dispatching from `SessionUpdatedEvent` processing in `app.py`
- [ ] `SessionUpdatedEvent` now only triggers data refresh, not highlight changes

### Task 2.5: Remove output digest diffing from sessions view

**File:** `teleclaude/cli/tui/views/sessions.py`

- [ ] Remove `_update_activity_state()` output digest comparison (lines 531-536) — `tool_done` event IS the signal
- [ ] Rename `_on_agent_output` / `on_agent_output` callback → `_on_tool_done` / `on_tool_done`
- [ ] Rename `_on_agent_output` in `app.py` → `_on_tool_done`
- [ ] Banner animation now triggers from `AGENT_ACTIVITY` events with type `agent_output` (→ `tool_done` after Phase 4)

---

## Phase 3: DB decoupling and column rename

### Task 3.1: Rename DB model columns

**File:** `teleclaude/core/db_models.py`

- [ ] `Session.last_after_model_at` → `Session.last_tool_use_at`
- [ ] `Session.last_agent_output_at` → `Session.last_tool_done_at`

**File:** `teleclaude/core/models.py`

- [ ] `SessionField` enum: update field name strings

### Task 3.2: Rename DB access layer column references

**File:** `teleclaude/core/db.py`

- [ ] All `last_after_model_at` → `last_tool_use_at`
- [ ] All `last_agent_output_at` → `last_tool_done_at`

### Task 3.3: Write DB migration

**File:** `teleclaude/core/migrations/NNN_rename_hook_event_columns.py` (new)

- [ ] `ALTER TABLE session RENAME COLUMN last_after_model_at TO last_tool_use_at`
- [ ] `ALTER TABLE session RENAME COLUMN last_agent_output_at TO last_tool_done_at`
- [ ] Follow existing migration pattern

### Task 3.4: Rename coordinator column references

**File:** `teleclaude/core/agent_coordinator.py`

- [ ] All `last_after_model_at` → `last_tool_use_at`
- [ ] All `last_agent_output_at` → `last_tool_done_at`
- [ ] Rename `handle_after_model()` → `handle_tool_use()`
- [ ] Rename `handle_agent_output()` → `handle_tool_done()`
- [ ] Rename `_extract_agent_output()` → `_extract_turn_output()`
- [ ] Update dispatch in `handle_agent_event()`

---

## Phase 4: Event vocabulary rename

Now that the plumbing is clean, rename the constants.

### Task 4.1: Rename type literals and constants

**File:** `teleclaude/core/events.py`

- [ ] `AgentHookEventType`: `"after_model"` → `"tool_use"`, `"agent_output"` → `"tool_done"`
- [ ] Remove dropped literals: `"before_model"`, `"before_tool_selection"`, `"before_tool"`, `"after_tool"`, `"pre_tool_use"`, `"post_tool_use"`, `"post_tool_use_failure"`, `"subagent_start"`, `"subagent_stop"`
- [ ] `AgentHookEvents`: `AFTER_MODEL` → `TOOL_USE`, `AGENT_OUTPUT` → `TOOL_DONE`
- [ ] Remove unused constants
- [ ] Rename `AgentOutputPayload` → `ToolDonePayload`
- [ ] Update `build_agent_payload` branches

### Task 4.2: Update hook event maps

**File:** `teleclaude/core/events.py`

- [ ] Claude `HOOK_EVENT_MAP`: `PreToolUse` → `TOOL_USE`, `PostToolUse` → `TOOL_DONE`; remove `PermissionRequest`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`
- [ ] Gemini `HOOK_EVENT_MAP`: `BeforeTool` → `TOOL_USE`, `AfterTool` → `TOOL_DONE`; remove `AfterModel`, `BeforeModel`, `BeforeToolSelection`

### Task 4.3: Update receiver forwarding allowlist

**File:** `teleclaude/hooks/receiver.py`

- [ ] `_HANDLED_EVENTS`: `AGENT_OUTPUT` → `TOOL_DONE`, `AFTER_MODEL` → `TOOL_USE`

### Task 4.4: Update TUI state machine event type strings

**File:** `teleclaude/cli/tui/state.py`

- [ ] `AGENT_ACTIVITY` handler branches: `"after_model"` → `"tool_use"`, `"agent_output"` → `"tool_done"`

### Task 4.5: Update all activity event emissions

**File:** `teleclaude/core/agent_coordinator.py`

- [ ] All `AgentActivityEvent` emissions use new type names

---

## Phase 5: Tests

### Task 5.1: Coordinator tests

**File:** `tests/unit/test_agent_coordinator.py`

- [ ] Update event constants, handler names, column names
- [ ] Add tests for `AgentActivityEvent` emission
- [ ] Remove `reasons=` assertions

### Task 5.2: Daemon tests

**Files:** `tests/unit/test_daemon.py`, `tests/unit/test_daemon_agent_stop_forwarded.py`

- [ ] Same renames and reason removal

### Task 5.3: Threaded output tests

**File:** `tests/unit/test_threaded_output_updates.py`

- [ ] Event constants, handler names, column names
- [ ] Remove `reasons=` assertions

### Task 5.4: TUI state tests

**File:** `tests/unit/test_tui_state.py`

- [ ] Replace reason-string tests with `AGENT_ACTIVITY` intent tests
- [ ] Add tests for `active_tool` state

### Task 5.5: DB tests

**File:** `tests/unit/test_db.py`

- [ ] Remove `_infer_update_reasons` tests
- [ ] Remove `reasons` parameter tests
- [ ] Update column name references

### Task 5.6: Other affected tests

**Files:** `tests/unit/test_ansi_stripping.py`, `tests/unit/test_telegram_adapter.py`, `tests/unit/test_hook_receiver.py`

- [ ] Replace old event name references

### Task 5.7: Run full test suite

- [ ] `make test` passes
- [ ] `make lint` passes

---

## Phase 6: Documentation

### Task 6.1: Event specs

**Files:** `docs/project/spec/event-types.md`, `docs/project/spec/hook-normalized-events.md`

- [ ] Update canonical event list
- [ ] Update raw → normalized mapping tables
- [ ] Document `AgentActivityEvent` as the consumer-facing event type
- [ ] Document dropped events

### Task 6.2: Architecture docs

**Files:** `docs/project/design/architecture/checkpoint-system.md`, `docs/project/design/architecture/outbox.md`, `docs/project/design/architecture/agent-activity-streaming-target.md`, `docs/project/design/ux/session-highlight.md`

- [ ] Replace `after_model` → `tool_use`, `agent_output` → `tool_done`
- [ ] Document the new direct event flow (coordinator → event bus → websocket)
- [ ] Remove references to reasons-based highlight logic

### Task 6.3: Third-party hook docs

**Files:** `docs/third-party/claude-code/hooks.md`, `docs/third-party/gemini-cli/hooks.md`

- [ ] Update mapping sections

### Task 6.4: Run telec sync

- [ ] `telec sync` succeeds
- [ ] Reinstall hooks: verify correct entries for both agents

---

## Phase 7: Review readiness

- [ ] Grep confirms zero `after_model` / `AFTER_MODEL` outside migration files
- [ ] Grep confirms zero `agent_output` / `AGENT_OUTPUT` outside migration files and `render_agent_output`
- [ ] Grep confirms zero `SessionUpdateReason` references
- [ ] Grep confirms zero `_infer_update_reasons` references
- [ ] Grep confirms zero `reasons=` on `db.update_session` calls
- [ ] All acceptance criteria met

## Deliberate non-changes

| Item                                                   | Why kept                                                                      |
| ------------------------------------------------------ | ----------------------------------------------------------------------------- |
| `render_agent_output()`, `render_clean_agent_output()` | Names describe the action (render output), not the event                      |
| `summarize_agent_output()`                             | Same — summarizes output text                                                 |
| `adapter_client.send_threaded_output()`                | Message delivery to Telegram — different concern, works fine                  |
| Cache + `session_updated` websocket path               | Still needed for state snapshots (title, status, session list loads)          |
| `SessionUpdatedContext` on event bus                   | Still emitted by DB writes for state changes — just no longer carries reasons |
| 3-second streaming timer logic                         | Driven by `temp_output_highlights` set membership — works identically         |

## Files affected

Core:

- `teleclaude/core/events.py`
- `teleclaude/core/agent_coordinator.py`
- `teleclaude/core/db_models.py`
- `teleclaude/core/models.py`
- `teleclaude/core/db.py`
- `teleclaude/hooks/receiver.py`
- `teleclaude/api_models.py`
- `teleclaude/api_server.py`
- `teleclaude/core/migrations/NNN_rename_hook_event_columns.py` (new)

TUI:

- `teleclaude/cli/tui/state.py`
- `teleclaude/cli/tui/views/sessions.py`
- `teleclaude/cli/tui/app.py`
- `teleclaude/cli/models.py`

Tests:

- `tests/unit/test_agent_coordinator.py`
- `tests/unit/test_daemon.py`
- `tests/unit/test_daemon_agent_stop_forwarded.py`
- `tests/unit/test_threaded_output_updates.py`
- `tests/unit/test_tui_state.py`
- `tests/unit/test_db.py`
- `tests/unit/test_ansi_stripping.py`
- `tests/unit/test_telegram_adapter.py`
- `tests/unit/test_hook_receiver.py`

Docs:

- `docs/project/spec/event-types.md`
- `docs/project/spec/hook-normalized-events.md`
- `docs/third-party/claude-code/hooks.md`
- `docs/third-party/gemini-cli/hooks.md`
- `docs/project/design/architecture/checkpoint-system.md`
- `docs/project/design/architecture/outbox.md`
- `docs/project/design/architecture/agent-activity-streaming-target.md`
- `docs/project/design/ux/session-highlight.md`
