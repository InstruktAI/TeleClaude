# Implementation Plan: adapter-output-delivery

## Overview

Two cross-cutting fixes to the core adapter layer: text delivery between tool calls and user input reflection. Touches `agent_coordinator.py`, `adapter_client.py`, `polling_coordinator.py`, and `daemon.py`.

---

## Phase 1: Text Delivery Fix

### Task 1.1: Add `trigger_incremental_output` to AgentCoordinator

**File(s):** `teleclaude/core/agent_coordinator.py`

- [x] Add public method `trigger_incremental_output(session_id: str) -> bool` after `_maybe_send_incremental_output`.
- [x] Fast-path: fetch session, check `is_threaded_output_enabled(session.active_agent)`, return False if not enabled.
- [x] Construct minimal `AgentOutputPayload()` with defaults (the existing method falls back to `session.active_agent` and `session.native_log_file`).
- [x] Delegate to `self._maybe_send_incremental_output(session_id, payload)`.

### Task 1.2: Expose AgentCoordinator to the poller

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/daemon.py`

- [x] Add `self.agent_coordinator: "AgentCoordinator | None" = None` to `AdapterClient.__init__`.
- [x] Add `TYPE_CHECKING` import for `AgentCoordinator`.
- [x] In `daemon.py`, after `self.client.agent_event_handler = self.agent_coordinator.handle_event` (line 251), add `self.client.agent_coordinator = self.agent_coordinator`.

### Task 1.3: Trigger incremental output from the poller

**File(s):** `teleclaude/core/polling_coordinator.py`

- [x] In the `OutputChanged` handler, after the `send_output_update` call (after line 764), add:
  ```python
  coordinator = adapter_client.agent_coordinator
  if coordinator:
      try:
          await coordinator.trigger_incremental_output(event.session_id)
      except Exception:
          logger.warning("Poller-triggered incremental output failed for %s", session_id[:8], exc_info=True)
  ```
- [x] This fires for ALL sessions but `trigger_incremental_output` fast-rejects non-threaded sessions before any I/O.

---

## Phase 2: User Input Reflection Fix

### Task 2.1: Remove HOOK from `_NON_INTERACTIVE` filter

**File(s):** `teleclaude/core/adapter_client.py`

- [x] At line 562, change `_NON_INTERACTIVE = {InputOrigin.MCP.value, InputOrigin.HOOK.value}` to `_NON_INTERACTIVE = {InputOrigin.MCP.value}`.
- [ ] The filter was added in commit `5598ff0a` with the assumption that hook origins are "not user-facing sessions." That assumption is wrong — terminal sessions are user-facing and their input arrives via the `user_prompt_submit` hook.
- [ ] MCP remains filtered because MCP-originated input is genuinely non-interactive.

### Task 2.2: Add `broadcast_user_input` call for non-headless sessions

**File(s):** `teleclaude/core/agent_coordinator.py`

- [x] In `handle_user_prompt_submit`, before the early return at line 426-427 (`if session.lifecycle_status != "headless": return`), add:
  ```python
  await self.client.broadcast_user_input(session, prompt_text, InputOrigin.HOOK.value)
  ```
- [x] This ensures terminal user input is reflected to Discord/Telegram regardless of headless status.
- [x] The headless path already calls `broadcast_user_input` via `process_message` — with the filter fix in Task 2.1, that path now works too.

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] Test `trigger_incremental_output` sends output for threaded sessions.
- [x] Test `trigger_incremental_output` is a no-op for non-threaded sessions.
- [x] Test `broadcast_user_input` is called for hook-origin input (both headless and non-headless paths).
- [x] Test `broadcast_user_input` still blocks MCP-origin input.
- [x] Run `make test`.

### Task 3.2: Quality Checks

- [x] Run `make lint`.
- [x] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes.
- [x] Confirm implementation tasks are all marked `[x]`.
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable).
