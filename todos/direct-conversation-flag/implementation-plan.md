# Implementation Plan: direct-conversation-flag

## Overview

A surgical change: add one boolean parameter to two MCP tool handlers and guard three listener registration call sites (two in `start_session` local/remote paths, one in `send_message`). The MCP dispatch layer and model pass the flag through. Default `False` preserves all existing behavior.

**Scope correction:** L643/L701 belong to `run_agent_command` and L720 to `get_session_data` — all out of scope per requirements. Only 3 call sites are guarded, not 5.

---

## Phase 1: Handler Changes

### Task 1.1: Add `direct` parameter to `teleclaude__send_message`

**File(s):** `teleclaude/mcp/handlers.py`

- [x] Add `direct: bool = False` to `teleclaude__send_message` signature
- [x] Wrap `_register_listener_if_present` call in `if not direct:`

### Task 1.2: Add `direct` parameter to `teleclaude__start_session`

**File(s):** `teleclaude/mcp/handlers.py`

- [x] Add `direct: bool = False` to `teleclaude__start_session` signature
- [x] Thread `direct` through to `_start_local_session` and `_start_remote_session`
- [x] Wrap `_register_listener_if_present` call in `_start_local_session` in `if not direct:`
- [x] Wrap `_register_remote_listener` call in `_start_remote_session` in `if not direct:`

---

## Phase 2: MCP Schema and Dispatch

### Task 2.1: Update `StartSessionArgs` model

**File(s):** `teleclaude/core/models.py`

- [x] Add `direct: bool = False` field to `StartSessionArgs`
- [x] Parse `direct` from MCP arguments in `from_mcp()`

### Task 2.2: Update MCP dispatch layer

**File(s):** `teleclaude/mcp_server.py`

- [x] Extract `direct` from arguments in `_handle_send_message` and pass to handler
- [x] `_handle_start_session` already passes via `StartSessionArgs.__dict__` — no change needed

### Task 2.3: Update tool schema definitions

**File(s):** `teleclaude/mcp/tool_definitions.py`

- [x] Add `direct` property to `teleclaude__start_session` schema
- [x] Add `direct` property to `teleclaude__send_message` schema

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] All 28 MCP tests pass (`test_mcp_server.py`, `test_mcp_handlers.py`)
- [x] All 16 model tests pass (`test_models.py`)
- [x] `make lint` passes (0 errors, 0 warnings)
- [x] 30 pre-existing failures in unrelated modules (TUI, threaded output) — none introduced by this change

### Task 3.2: Quality Checks

- [x] `make lint` passes
- [x] No unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [x] Requirements reflected in code changes
- [x] All implementation tasks marked `[x]`
- No deferrals
