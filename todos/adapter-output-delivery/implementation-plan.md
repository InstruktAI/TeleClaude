# Implementation Plan: adapter-output-delivery

## Overview

Two cross-cutting fixes to the core adapter layer: text delivery between tool calls and user input reflection. Touches `agent_coordinator.py`, `adapter_client.py`, `polling_coordinator.py`, `daemon.py`, `command_handlers.py`, `mcp/handlers.py`, and `command_mapper.py`.

---

## Phase 1: Text Delivery Fix

### Task 1.1: Add `trigger_incremental_output` to AgentCoordinator

**File(s):** `teleclaude/core/agent_coordinator.py`

- [ ] Add public method `trigger_incremental_output(session_id: str) -> bool` after `_maybe_send_incremental_output`.
- [ ] Fast-path: fetch session, check `is_threaded_output_enabled(session.active_agent)`, return False if not enabled.
- [ ] Construct minimal `AgentOutputPayload()` with defaults (the existing method falls back to `session.active_agent` and `session.native_log_file`).
- [ ] Delegate to `self._maybe_send_incremental_output(session_id, payload)`.

### Task 1.2: Expose AgentCoordinator to the poller

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/daemon.py`

- [ ] Add `self.agent_coordinator: "AgentCoordinator | None" = None` to `AdapterClient.__init__`.
- [ ] Add `TYPE_CHECKING` import for `AgentCoordinator`.
- [ ] In `daemon.py`, after `self.client.agent_event_handler = self.agent_coordinator.handle_event`, add `self.client.agent_coordinator = self.agent_coordinator`.

### Task 1.3: Trigger incremental output from the poller

**File(s):** `teleclaude/core/polling_coordinator.py`

- [ ] In the `OutputChanged` handler, after the `send_output_update` call, call `coordinator.trigger_incremental_output(event.session_id)` when coordinator is present.
- [ ] Guard failures with warning logging; do not crash event handling.

---

## Phase 2: User Input Reflection and Ownership

### Task 2.1: Keep routing origin-agnostic (no MCP suppression)

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Ensure `process_message()` reflection fanout is not blocked by `InputOrigin.MCP`.
- [ ] Keep reflection routing uniform across origins.

### Task 2.2: Resolve MCP ownership from lineage

**File(s):** `teleclaude/mcp/handlers.py`, `teleclaude/core/command_mapper.py`

- [ ] For local MCP sends, resolve actor ownership from caller session lineage.
- [ ] If caller session has human identity, propagate it.
- [ ] If no human identity is present, mark ownership as system.
- [ ] Keep remote fallback semantics system-owned when explicit actor metadata is absent.

### Task 2.3: Keep single-send invariant

**File(s):** `teleclaude/core/agent_coordinator.py`, `teleclaude/core/command_handlers.py`

- [ ] Non-headless path reflects once in `handle_user_prompt_submit`.
- [ ] Headless path reflects once via `process_message`.
- [ ] No duplicate reflection fanout for one input event.

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Test `trigger_incremental_output` sends output for threaded sessions.
- [ ] Test `trigger_incremental_output` is a no-op for non-threaded sessions.
- [ ] Test `broadcast_user_input` is called for hook-origin input (both headless and non-headless paths).
- [ ] Test MCP-origin injected input is reflected with resolved ownership attribution (human lineage or system owner).
- [ ] Run `make test`.

### Task 3.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
