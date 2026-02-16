# DOR Report: help-desk-control-room

## Draft Assessment (v3)

**Status:** Draft — artifacts updated after user feedback on scope (all Discord, not help-desk-only).

**Key corrections:**

1. (v2) The first draft described a new "control room" Discord forum channel. Wrong. The existing Discord channels ARE the control room. The actual work is extending threaded output mode and decoupling it from Telegram-specific state.
2. (v3) Threaded output scope expanded from "Discord help desk channels only" to "ALL Discord sessions" — the entire Discord experience uses threaded output, regardless of channel.

## Gate Analysis

### 1. Intent & Success — Strong

Problem is explicit: threaded output is Gemini-only and Telegram-coupled. Outcome is concrete: threaded output for all Discord sessions, any channel, any agent. Success criteria are testable.

### 2. Scope & Size — Good

Core changes:

- `feature_flags.py`: remove Gemini hardcheck, add Discord adapter gate (~15 lines)
- `models.py`: promote `char_offset` (~5 lines + migration)
- `ui_adapter.py`: replace `telegram_meta.char_offset` access (~10 lines)
- `agent_coordinator.py`: replace `telegram_meta.char_offset` reset (~3 lines)
- `discord_adapter.py`: override `_build_metadata_for_thread`, fix `close_channel` (~15 lines)
- `adapter_client.py`: toggle broadcast flag (~1 line)

Fits a single session. No cross-cutting changes outside the adapter/coordinator layer.

### 3. Verification — Strong

Each requirement maps to clear unit tests. The existing `test_threaded_output_updates.py` provides patterns for new tests. Regression coverage exists for the Gemini/Telegram path.

### 4. Approach Known — Strong

Threaded output is already production-proven for Gemini/Telegram. The implementation is:

1. Remove artificial constraints (agent name, Telegram coupling)
2. Add Discord adapter gate (origin is Discord → threaded output on)
3. Fix lifecycle (close = delete)

No new architectural patterns. All code paths exist; they just need to be unblocked.

### 5. Research — Satisfied

No new third-party dependencies. Discord.py thread deletion is straightforward (`thread.delete()`). The existing codebase already creates and manages Discord forum threads.

### 6. Dependencies & Preconditions — Resolved

- `help-desk-discord` is now delivered — dependency satisfied
- `help-desk-whatsapp` dependency removed from `dependencies.json`
- Config: Discord adapter config (`guild_id`, `help_desk_channel_id`, `escalation_channel_id`) already in `config.yml`
- Experiment: `experiments.yml` already exists and loads at startup

### 7. Integration Safety — Strong

- Adapter-gated: threaded output activates for all Discord-origin sessions (simple adapter check)
- `close_channel` change affects only Discord adapter (Telegram behavior unchanged)
- `char_offset` promotion is additive (keep backward compat with existing Telegram metadata)
- Broadcast toggle is for observer adapters only (best-effort, doesn't affect origin delivery)

### 8. Tooling Impact — N/A

No scaffolding or tooling changes.

## Assumptions

1. `help-desk-discord` delivery includes working thread creation in `help_desk_channel_id` and `escalation_channel_id`
2. The `AgentCoordinator` handle_tool_done path works for Discord-origin sessions (session resolution, transcript reading)
3. Discord.py `thread.delete()` is a simple async call (confirmed by existing `delete_channel` implementation)
4. `char_offset` can be promoted to session-level without performance concerns (it's a simple integer)

## Open Questions

1. **`char_offset` approach:** Session-level column vs shared adapter metadata base? Session-level is simpler but adds a migration. Shared base is cleaner but more refactoring. Recommend session-level for simplicity.
2. **Broadcast scope:** Should threaded output broadcast to ALL observer adapters? Recommend: yes, broadcast always (aligns with existing `send_message` broadcast behavior).

## Blockers

None. All dependencies are met, approach is known, implementation is bounded.
