# Implementation Plan: adapter-output-delivery

## Overview

Two cross-cutting fixes were implemented in the core adapter layer:

1. Continuous text delivery between tool calls.
2. Clear, actor-attributed input reflection with explicit origin/admin routing behavior.

Primary touch points: `agent_coordinator.py`, `adapter_client.py`, `polling_coordinator.py`, `daemon.py`, `command_mapper.py`, `command_handlers.py`, `commands.py`, `discord_adapter.py`, `telegram_adapter.py`, `telegram/input_handlers.py`, `mcp/handlers.py`, and `redis_transport.py`.

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

### Task 2.1: Enforce reflection fan-out contract

**File(s):** `teleclaude/core/adapter_client.py`

- [x] Keep input reflection routed to all provisioned UI adapters except the source adapter.
- [x] Ensure text, voice, hook, and MCP-origin input all use the same reflection rule.
- [x] Add reflection actor metadata fields to message metadata (`reflection_actor_id`, `reflection_actor_name`, `reflection_actor_avatar_url`).
- [x] Format reflected text using actor attribution (best effort actor name, then fallback).

### Task 2.2: Propagate actor identity through command boundaries

**File(s):** `teleclaude/types/commands.py`, `teleclaude/core/command_mapper.py`, `teleclaude/core/command_handlers.py`, `teleclaude/transport/redis_transport.py`

- [x] Add `actor_id`, `actor_name`, and `actor_avatar_url` to message and voice command models.
- [x] Map actor identity from adapter metadata into command payloads.
- [x] Carry actor identity through Redis/MCP command ingestion and command handlers.
- [x] Keep reflection behavior consistent regardless of source adapter.

### Task 2.3: Feed actor identity from adapters

**File(s):** `teleclaude/adapters/telegram/input_handlers.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`, `teleclaude/mcp/handlers.py`

- [x] Populate actor metadata for Telegram text and voice input.
- [x] Populate actor metadata for Discord text and voice input.
- [x] Resolve MCP actor identity for AI-to-AI flows and include it in emitted commands.
- [x] Apply best-effort actor naming fallback where upstream adapters do not provide a human-readable name.

### Task 2.4: Discord reflection rendering via webhook

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Add webhook-based reflection send path using reflection actor name/avatar when available.
- [x] Cache reflection webhooks per parent forum channel.
- [x] Fall back to standard bot send when webhook creation/send is unavailable.
- [x] Keep routing unchanged: this is presentation behavior only.

### Task 2.5: Preserve origin UX-only summary and notice behavior

**File(s):** `docs/project/spec/session-output-routing.md`, core delivery call sites

- [x] Keep notices/feedback/errors origin-only.
- [x] Keep `last_output_summary` origin UX-only and non-threaded/in-edit.
- [x] Keep threaded output flow separate from summary/notice routing.

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] Test `trigger_incremental_output` sends output for threaded sessions.
- [x] Test `trigger_incremental_output` is a no-op for non-threaded sessions.
- [x] Test `broadcast_user_input` reflects to all non-source adapters for text/voice/MCP flows.
- [x] Test actor metadata propagation and formatting for reflection paths.
- [x] Test Discord reflection send path behavior (webhook first, fallback safe path).
- [x] Run targeted adapter/core unit tests for changed modules.

### Task 3.2: Quality Checks

- [x] Run lint checks for changed files.
- [x] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes.
- [x] Confirm implementation tasks are all marked `[x]`.
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable).
