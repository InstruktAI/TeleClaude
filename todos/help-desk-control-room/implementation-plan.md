# Implementation Plan: help-desk-control-room

## Overview

Extend the threaded output experiment from Telegram/Gemini-only to all Discord sessions. This requires decoupling `char_offset` from Telegram metadata, opening the feature flag, and fixing the Discord thread lifecycle.

The threaded output mechanism is proven — it runs in production for Gemini on Telegram. The work here is removing artificial constraints (Gemini-only, Telegram-coupled state) and enabling it for the entire Discord experience.

## Phase 1: Decouple `char_offset` from Telegram metadata

### Task 1.1: Promote `char_offset` to session-level or shared adapter state

**File(s):** `teleclaude/core/models.py`

- [x] Determine approach: session-level column (like `output_message_id`) or shared field in adapter metadata base
- [x] If session-level: add `char_offset: int = 0` to `Session` model
- [ ] ~~If shared metadata: add `char_offset` to a base that `TelegramAdapterMetadata` and `DiscordAdapterMetadata` both inherit~~ (N/A — chose session-level)
- [x] Keep `telegram_meta.char_offset` for backward compatibility during migration, but read from the new location

### Task 1.2: Update `send_threaded_output` in UiAdapter

**File(s):** `teleclaude/adapters/ui_adapter.py`

- [x] Replace `telegram_meta = session.get_metadata().get_ui().get_telegram()` with adapter-agnostic access
- [x] Read `char_offset` from the new location (session-level or shared metadata)
- [x] Write `char_offset` updates to the new location
- [x] Keep pagination logic unchanged — only the state access changes

### Task 1.3: Update `AgentCoordinator` char_offset reset

**File(s):** `teleclaude/core/agent_coordinator.py`

- [x] `handle_agent_stop` (line ~562): replace `telegram_meta.char_offset = 0` with adapter-agnostic reset
- [x] Use the same access pattern as Task 1.2

### Task 1.4: DB migration (if session-level approach)

**File(s):** `teleclaude/core/migrations/` (new migration)

- [x] Add `char_offset INTEGER DEFAULT 0` column to sessions table
- [x] Migrate existing `telegram_meta.char_offset` values to the new column for active sessions

---

## Phase 2: Open Feature Flag

### Task 2.1: Remove Gemini hardcheck

**File(s):** `teleclaude/core/feature_flags.py`

- [ ] Remove `if normalized_agent != AgentName.GEMINI.value: return False`
- [ ] `is_threaded_output_enabled` should check experiment config for the agent, without agent-name restriction
- [ ] If no agent specified in experiment config agents list (empty/None), experiment applies to all agents

### Task 2.2: Add Discord adapter gate

**File(s):** `teleclaude/core/feature_flags.py`

- [ ] Add `is_threaded_output_enabled_for_session(session)` that checks both:
  - Experiment flag (existing mechanism)
  - OR session's origin adapter is Discord
- [ ] If origin is Discord, threaded output is on — no channel-specific gating needed
- [ ] Update callers (`AgentCoordinator`, `UiAdapter`, `AdapterClient`) to use the session-aware check where session is available

---

## Phase 3: Discord Adapter Changes

### Task 3.1: Override `_build_metadata_for_thread` for Discord

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Override `_build_metadata_for_thread()` to return `MessageMetadata()` without MarkdownV2 parse mode
- [ ] Discord uses standard markdown, not Telegram MarkdownV2

### Task 3.2: Fix `close_channel` to delete thread

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Change `close_channel` from `archived=True, locked=True` to `thread.delete()`
- [ ] Align with `delete_channel` behavior — both delete the thread
- [ ] When 72h sweep fires close event, the Discord thread is removed

### Task 3.3: Discord adapter `ensure_channel` for threaded output

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Verify `ensure_channel` works correctly for Discord sessions when called from `_run_ui_lane`
- [ ] The thread must exist before threaded output messages are sent
- [ ] For non-Discord-origin sessions observed via broadcast: `ensure_channel` should create a control room thread if applicable

---

## Phase 4: Cross-Platform Broadcast

### Task 4.1: Enable threaded output broadcast to observers

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] In `send_threaded_output`, change `broadcast=False` to `broadcast=True`
- [ ] This allows Telegram-origin sessions to have their threaded output mirrored to Discord observer threads (and vice versa)
- [ ] Observer broadcast is best-effort (existing pattern in `_broadcast_to_observers`)

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Unit test: `is_threaded_output_enabled` works for Claude (not just Gemini)
- [ ] Unit test: `is_threaded_output_enabled_for_session` returns True for any Discord-origin session
- [ ] Unit test: `char_offset` read/write in `send_threaded_output` works without Telegram metadata
- [ ] Unit test: Discord `close_channel` deletes thread (not archives)
- [ ] Unit test: existing Gemini threaded output still works (regression)
- [ ] Unit test: standard poller output still works for Telegram non-threaded sessions
- [ ] Run `make test`

### Task 5.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
