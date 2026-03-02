# Implementation Plan: truncated-user-input

## Overview

The bug was caused by a code path in the web SSE streaming endpoint that bypassed the canonical message processing route, skipping essential text transformations and retry logic. The fix consolidates all message delivery paths to use the unified `process_message` command, ensuring consistent handling across all adapters.

## Phase 1: Route Web SSE Messages Through Canonical Path

### Task 1.1: Replace Direct tmux_bridge Call with ProcessMessageCommand

**File(s):** `teleclaude/api/streaming.py`

- [x] Remove direct `tmux_bridge.send_keys_existing_tmux` call from `_stream_sse`
- [x] Import `ProcessMessageCommand` and `get_command_service`
- [x] Route user messages through `process_message` command with origin="web"
- [x] Add error handling with status update on delivery failure
- [x] Verify logs show "Web lane message delivery"

### Task 1.2: Verify Tests Pass

**File(s):** All test files

- [x] Run full test suite: 2678 tests pass
- [x] No new test failures introduced
- [x] Existing web SSE tests continue to pass

## Phase 2: Documentation

### Task 2.1: Update Bug Report

**File(s):** `todos/truncated-user-input/bug.md`

- [x] Document investigation findings
- [x] Document root cause
- [x] Document fix applied
- [x] Add verification notes

## Summary

Fixed the web SSE lane's message delivery by consolidating all user message paths through the canonical `process_message` route. This ensures:

- Proper text transformation via `wrap_bracketed_paste` (escaping, special char handling)
- Consistent retry and backoff logic
- Actor tracking and DB updates
- Compatibility with all agent types (Claude, Gemini, Codex)

The fix is minimal, focused, and eliminates the protocol violation of bypassing DRY adapter boundaries.
