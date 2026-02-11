# Implementation Plan: agent-activity-events-phase-3-7

## Overview

Rename legacy event vocabulary (`after_model`/`agent_output`) to semantic names (`tool_use`/`tool_done`) across DB columns, event constants, handler names, TUI state machine, tests, and documentation. Each phase is committed independently.

## Phase 3: DB Decoupling and Column Rename

### Task 3.1: Write DB migration (007) for column rename

**File(s):** `teleclaude/core/migrations/007_rename_activity_columns.py`

- [x] Create migration that renames `last_after_model_at` -> `last_tool_use_at` and `last_agent_output_at` -> `last_tool_done_at`
- [x] SQLite column rename via ALTER TABLE RENAME COLUMN (supported in SQLite 3.25.0+)
- [x] Idempotent: skip if new columns already exist

### Task 3.2: Rename DB model columns

**File(s):** `teleclaude/core/db_models.py`

- [x] Rename `last_agent_output_at` -> `last_tool_done_at`
- [x] Rename `last_after_model_at` -> `last_tool_use_at`

### Task 3.3: Update Session dataclass and SessionField enum

**File(s):** `teleclaude/core/models.py`

- [x] Rename Session fields: `last_agent_output_at` -> `last_tool_done_at`, `last_after_model_at` -> `last_tool_use_at`
- [x] Rename SessionField enum: `LAST_AGENT_OUTPUT_AT` -> `LAST_TOOL_DONE_AT`, `LAST_AFTER_MODEL_AT` -> `LAST_TOOL_USE_AT`
- [x] Update `to_dict()` / `from_dict()` serialization references

### Task 3.4: Update DB access layer column references

**File(s):** `teleclaude/core/db.py`

- [x] Update row-to-model mapping: `last_agent_output_at` -> `last_tool_done_at`, `last_after_model_at` -> `last_tool_use_at`
- [x] Update datetime field set for dynamic updates

### Task 3.5: Update coordinator column references and handler names

**File(s):** `teleclaude/core/agent_coordinator.py`

- [x] Rename `handle_after_model()` -> `handle_tool_use()`
- [x] Rename `handle_agent_output()` -> `handle_tool_done()`
- [x] Update all `last_after_model_at` -> `last_tool_use_at` references
- [x] Update all `last_agent_output_at` -> `last_tool_done_at` references
- [x] Update handler dispatch in `handle_event()`

---

## Phase 4: Event Vocabulary Rename

### Task 4.1: Rename type literals and constants

**File(s):** `teleclaude/core/events.py`

- [x] In `AgentHookEventType` literal: rename `"agent_output"` -> `"tool_done"`, `"after_model"` -> `"tool_use"`
- [x] In `AgentHookEvents` class: rename `AGENT_OUTPUT` -> `TOOL_DONE`, `AFTER_MODEL` -> `TOOL_USE`
- [x] Update `SUPPORTED_PAYLOAD_TYPES` references
- [x] Update `build_agent_payload()` comparisons
- [x] Update `AgentActivityEvent` docstring

### Task 4.2: Update hook event maps

**File(s):** `teleclaude/core/events.py`

- [x] Claude map: `"PreToolUse"` -> `TOOL_USE`, `"PostToolUse"/"PostToolUseFailure"/"SubagentStart"/"SubagentStop"` -> `TOOL_DONE`
- [x] Gemini map: `"AfterModel"` -> `TOOL_USE`, `"AfterTool"` -> `TOOL_DONE`

### Task 4.3: Update receiver forwarding allowlist

**File(s):** `teleclaude/hooks/receiver.py`

- [x] Update `_HANDLED_EVENTS`: `AGENT_OUTPUT` -> `TOOL_DONE`, `AFTER_MODEL` -> `TOOL_USE`

### Task 4.4: Update TUI state machine event type strings

**File(s):** `teleclaude/cli/tui/state.py`

- [x] Update `event_type` comment to list `"tool_use"`, `"tool_done"`
- [x] Update `event_type == "after_model"` -> `event_type == "tool_use"`
- [x] Update `event_type == "agent_output"` -> `event_type == "tool_done"`
- [x] Update highlight reason `"agent_output"` -> `"tool_done"` (SESSION_UPDATED intent)
- [x] Update log messages

### Task 4.5: Update remaining source file references

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [x] Update comment: `(after_model, agent_output)` -> `(tool_use, tool_done)`

### Task 4.6: Update API models docstring

**File(s):** `teleclaude/api_models.py`

- [x] Update `AgentActivityEventDTO` docstring to reflect `tool_use`, `tool_done`

---

## Phase 5: Tests

### Task 5.1: Update test_agent_coordinator.py

**File(s):** `tests/unit/test_agent_coordinator.py`

- [x] Update handler name references and event type strings

### Task 5.2: Update test_tui_state.py

**File(s):** `tests/unit/test_tui_state.py`

- [x] Update event type strings in state machine tests

### Task 5.3: Update test_ansi_stripping.py

**File(s):** `tests/unit/test_ansi_stripping.py`

- [x] Update handler name references

### Task 5.4: Update remaining test files

**File(s):** `tests/unit/test_daemon_agent_stop_forwarded.py`, `tests/unit/test_threaded_output_updates.py`

- [x] Update all `after_model`/`agent_output` references in remaining test files

### Task 5.5: Write new tests for AgentActivityEvent emission

**File(s):** `tests/unit/test_agent_activity_events.py`

- [x] Test `event_bus.emit(AGENT_ACTIVITY, ...)` is called from coordinator
- [x] Validate `AgentActivityEvent` fields (session_id, event_type, tool_name, timestamp)
- [x] Test coordinator `handle_tool_use()` emits activity event
- [x] Test coordinator `handle_tool_done()` emits activity event
- [x] Test coordinator `handle_agent_stop()` emits activity event with summary

### Task 5.6: Write new tests for API server broadcast

**File(s):** `tests/unit/test_agent_activity_broadcast.py`

- [x] Test API server `_handle_agent_activity_event` broadcasts to WebSocket clients
- [x] Test TUI state machine `AGENT_ACTIVITY` intent handling for `tool_use`, `tool_done`, `agent_stop`, `user_prompt_submit`

---

## Phase 6: Documentation

### Task 6.1: Update event specs and architecture docs

**File(s):** `docs/project/spec/event-types.md`, `docs/project/design/architecture/outbox.md`, `docs/project/design/architecture/checkpoint-system.md`, `docs/project/design/ux/session-highlight.md`, `docs/project/design/ux/session-highlight/implementation-plan.md`

- [x] Replace all `after_model`/`agent_output` references with `tool_use`/`tool_done`

---

## Phase 7: Review Readiness

### Task 7.1: Grep validation for zero stale references

- [x] Run grep across codebase for `after_model`, `agent_output`, `AFTER_MODEL`, `AGENT_OUTPUT` -- zero hits in production code (only migration files)
- [x] Confirm all tests pass (`make test`) -- 11 pre-existing failures, zero new failures
- [x] Confirm lint passes (`make lint`)
- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`

### Task 7.2: Fix pre-existing snapshot test failure

- [x] Fixed `tests/snapshots/tui/sessions_basic.txt` -- stale snapshot from before output rendering decoupling (commit `5eca88ef`)
