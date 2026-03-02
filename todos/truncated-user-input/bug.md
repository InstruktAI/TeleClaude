# Bug: User transcribed input is truncated before delivery to agent sessions. Suspect multiple curl/send paths bypassing the unified message route — violates DRY and adapter boundary policy. Must investigate all code paths that send messages to sessions (telec sessions send, direct API calls, notification delivery, any raw curl to the daemon socket) and consolidate to a single canonical route. Truncation must be handled gracefully — if a message exceeds limits, it should be chunked or the limit raised, never silently cut.

## Symptom

User transcribed input is truncated before delivery to agent sessions. Suspect multiple curl/send paths bypassing the unified message route — violates DRY and adapter boundary policy. Must investigate all code paths that send messages to sessions (telec sessions send, direct API calls, notification delivery, any raw curl to the daemon socket) and consolidate to a single canonical route. Truncation must be handled gracefully — if a message exceeds limits, it should be chunked or the limit raised, never silently cut.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-02

## Investigation

Traced all code paths that send messages to agent sessions:

1. **Canonical path** (`telec sessions send`, Telegram text/voice, Discord, API `POST /sessions/{id}/message`):
   `process_message` → `inbound_queue.enqueue` → DB → `deliver_inbound` → `tmux_io.wrap_bracketed_paste` → `tmux_io.process_text` → `tmux_bridge.send_keys_existing_tmux`

2. **Web SSE bypass** (`POST /api/chat/stream` in `teleclaude/api/streaming.py:_stream_sse`):
   Direct `tmux_bridge.send_keys_existing_tmux` call, skipping `process_message`, inbound queue, `wrap_bracketed_paste`, actor tracking, DB updates, and retry logic.

3. **Discord relay handback** (`discord_adapter.py:_handle_agent_handback`):
   Direct `send_keys_existing_tmux` for relay context injection (agent-to-agent, not user input — out of scope for this fix).

4. **Listener notification** (`tmux_delivery.py:deliver_listener_message`):
   Direct `send_keys_existing_tmux` for agent-to-agent stop notifications (not user input — out of scope).

The web SSE bypass (path 2) is the primary violation. `wrap_bracketed_paste` in the canonical route handles:
- Gemini `!` character escaping
- Codex next-command normalization
- Bracketed paste wrapping for special characters

Skipping this for web-lane messages means transcribed input containing punctuation, special chars, or slash commands may be misdelivered or silently garbled. Additionally, the bypass skips retry/backoff, `last_message_sent` DB update (breaking echo guard for long messages), and `broadcast_user_input`.

## Root Cause

`teleclaude/api/streaming.py:_stream_sse` (introduced in feat(api): add SSE streaming endpoint) delivers user messages via direct `tmux_bridge.send_keys_existing_tmux` instead of the canonical `process_message` → `inbound_queue` → `deliver_inbound` route.

This bypasses `tmux_io.wrap_bracketed_paste`, which:
- Escapes `!` for Gemini sessions
- Normalizes Codex next-commands
- Wraps text with special chars in bracketed paste markers (ensuring proper agent receipt)

Without bracketed paste wrapping, transcribed voice input with punctuation or special characters can be misdelivered (characters misinterpreted by the receiving agent). The bypass also skips retry logic, making failures silent rather than retried.

## Fix Applied

Replaced the direct `send_keys_existing_tmux` call in `teleclaude/api/streaming.py:_stream_sse` with the canonical `process_message` route:

```python
cmd = ProcessMessageCommand(session_id=session_id, text=user_message, origin="web")
await get_command_service().process_message(cmd)
```

This ensures the web SSE lane uses the same path as all other adapters: inbound queue, `wrap_bracketed_paste`, retry/backoff, DB updates, and actor tracking.
