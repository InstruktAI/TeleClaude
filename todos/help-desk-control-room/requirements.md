# Requirements: help-desk-control-room

## Goal

Enable threaded output mode for the entire Discord experience — all sessions, all agents. The same proven pattern currently running for Gemini on Telegram, extended to every Discord session. The existing Discord channel structure IS the control room; no new channels are needed.

## Problem

- Threaded output mode is hardcoded to Gemini-only (`is_threaded_output_enabled` checks `AgentName.GEMINI`)
- `send_threaded_output` in `UiAdapter` is coupled to `telegram_meta.char_offset` — won't work for Discord
- `AgentCoordinator` also directly references `telegram_meta.char_offset` when clearing turn state
- Discord `close_channel` archives+locks threads instead of deleting them; for help desk sessions, close should delete
- The existing Discord help desk channels (customer-sessions + escalations) already have thread-per-session and admin message routing — but output is the standard poller mode (one big edited message), not per-turn threaded messages

## Intended Outcome

- Threaded output mode is the default for ALL Discord sessions, regardless of channel or agent
- `char_offset` pagination state is adapter-agnostic (not hardcoded to Telegram metadata)
- Discord threads are deleted (not archived) when sessions close
- Admins see per-turn output in Discord threads — same experience as the Telegram Gemini experiment

## Requirements

### R1: Decouple `char_offset` from Telegram metadata

**Files:** `teleclaude/core/models.py`, `teleclaude/adapters/ui_adapter.py`, `teleclaude/core/agent_coordinator.py`

- `char_offset` must be accessible per-adapter, not only from `telegram_meta`
- Either promote `char_offset` to session-level (like `output_message_id` was promoted) or add it to a shared base in adapter metadata that both Telegram and Discord metadata implement
- `send_threaded_output` in UiAdapter must read/write `char_offset` without assuming Telegram
- `AgentCoordinator.handle_agent_stop` must reset `char_offset` without assuming Telegram

### R2: Open threaded output feature flag beyond Gemini

**Files:** `teleclaude/core/feature_flags.py`, `experiments.yml`

- Remove the `AgentName.GEMINI` hardcheck in `is_threaded_output_enabled`
- Threaded output should be gateable by experiment config, not by hardcoded agent name
- The experiment config already supports an `agents` list — if agents list includes the active agent, enable it

### R3: Enable threaded output for ALL Discord sessions

**Files:** `teleclaude/core/feature_flags.py`, `teleclaude/adapters/discord_adapter.py`

- ALL Discord sessions use threaded output mode — no channel-specific gating
- The gate logic is simple: if the session's origin adapter is Discord, threaded output is on
- This applies to all agents (Claude, Gemini, Codex) on Discord
- The Discord adapter's `_build_metadata_for_thread()` override should return appropriate metadata for Discord (no MarkdownV2 parse mode — Discord uses standard markdown)

### R4: Discord close_channel = delete thread

**Files:** `teleclaude/adapters/discord_adapter.py`

- `close_channel` should delete the Discord thread, not archive+lock it
- When a session closes (72h sweep), the adapter receives a close event — the thread is deleted
- `delete_channel` remains for permanent cleanup (same behavior — delete)
- This matches the user's expectation: closed = gone from Discord

### R5: AdapterClient threaded output broadcast

**Files:** `teleclaude/core/adapter_client.py`

- Currently `send_threaded_output` in AdapterClient uses `broadcast=False` — only origin adapter
- For admin observation: threaded output from Telegram-origin sessions should also appear in Discord control room threads (and vice versa)
- Change to broadcast to observer adapters so cross-platform mirroring works

## Out of Scope

- New Discord channels or forums — the existing channel structure is sufficient
- WhatsApp adapter integration — comes later as a separate todo
- Forum tags / thread categorization — nice-to-have, not part of this delivery

## Constraints

- Must not break existing Telegram threaded output (Gemini experiment)
- Must not break standard poller output for sessions that don't use threaded mode
- Must not break existing Discord help desk or escalation flows
- `char_offset` migration must be backward-compatible (existing sessions with Telegram char_offset must keep working)

## Success Criteria

- [ ] Threaded output works for ALL Discord sessions (any channel, any agent)
- [ ] `char_offset` is not coupled to `telegram_meta` — works for any adapter
- [ ] Existing Gemini threaded output on Telegram still works
- [ ] Discord threads are deleted (not archived) when sessions close
- [ ] Admin typing in a Discord thread sends input to the session (already works — verify not broken)
- [ ] Standard poller output still works for Telegram non-Gemini sessions

## Risks

- Promoting `char_offset` to session-level may require a DB migration if stored as a column
- Changing `close_channel` to delete could surprise admins if they expect to find archived threads (mitigated: help desk threads are ephemeral by nature)
- Discord message rate limits when threaded output sends many messages per turn (mitigated: existing pagination in `send_threaded_output`)
