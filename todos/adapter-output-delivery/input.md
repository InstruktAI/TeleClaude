# Adapter Output & Input Delivery

## Problem Statement

Two cross-cutting delivery gaps in the adapter layer: threaded adapters miss text output between tool calls, and terminal user input is not reflected to other UI adapters.

## Specific Issues

### 1. Missing text output between tool calls (CRITICAL)

When threaded output mode is active, the poller (`send_output_update`) is suppressed. The incremental renderer (`_maybe_send_incremental_output`) only fires on hook events: `tool_use`, `tool_done`, `agent_stop`. Text written between tools has NO trigger to deliver it.

**Root cause:** `agent_coordinator.py` only calls `_maybe_send_incremental_output` from hook event handlers. There is no text-streaming trigger for threaded output mode.

**Affected:** Claude/Discord, Gemini/Telegram, Gemini/Discord.

### 2. User input not reflected to other UI adapters from terminal

When a user types in the terminal, that input is not broadcast to Discord/Telegram as a formatted reflection message (e.g. "TUI @ MozBook:\n\n{text}").

**Root cause (non-headless):** `handle_user_prompt_submit` in `agent_coordinator.py` returns at line 427 for non-headless sessions without ever calling `broadcast_user_input`.

**Root cause (headless):** Falls through to `process_message` which calls `broadcast_user_input` with origin `hook` — but `_NON_INTERACTIVE` filter at `adapter_client.py:562` blocks `InputOrigin.HOOK.value` based on the incorrect assumption that hook origins are "not user-facing sessions" (commit `5598ff0a`).

## Files Involved

- `teleclaude/core/agent_coordinator.py` — incremental output trigger, user prompt handling
- `teleclaude/core/adapter_client.py` — `broadcast_user_input`, `_NON_INTERACTIVE` filter
- `teleclaude/core/polling_coordinator.py` — poller OutputChanged handler
- `teleclaude/daemon.py` — wiring
