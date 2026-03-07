# Implementation Plan: adapter-reflection-cleanup

## Overview

Three phases: (1) make core a dumb broadcast pipe, (2) give adapters their local
reflection logic, (3) parallelize delivery. Phase 1 and 2 must ship together —
removing core suppression without adapter-local suppression would echo own-user input.

---

## Phase 1: Core becomes a dumb broadcast pipe

### Task 1.1: Add `reflection_origin` to MessageMetadata

**File(s):** `teleclaude/core/models.py`

- [x] Add `reflection_origin: Optional[str] = None` field to `MessageMetadata`

### Task 1.2: Strip presentation logic from `broadcast_user_input`

**File(s):** `teleclaude/core/adapter_client.py`

- [x] Remove `default_actor`, `display_origin_label`, `reflection_header`,
      `is_terminal_actor_reflection` construction (lines 624-640)
- [x] Remove `render_reflection_text()` closure entirely (lines 648-657)
- [x] Set `reflection_origin=source` on `reflection_metadata` (the MessageMetadata
      instance constructed at line 641)
- [x] Pass raw `text` directly to `adapter.send_message()` — no per-adapter formatting

### Task 1.3: Replace `_fanout_excluding` with broadcast-to-all for reflections

**File(s):** `teleclaude/core/adapter_client.py`

- [x] In `broadcast_user_input`: replace `_fanout_excluding(..., exclude=source_adapter)`
      with `_broadcast_to_ui_adapters(...)` — sends to ALL adapters
- [x] Verify `_broadcast_action` call site (line 914) — determine if it also needs
      the same treatment or if exclusion is correct for that path
      (confirmed: `_broadcast_action` is for command echo prevention, exclusion stays)
- [x] If `_fanout_excluding` has no remaining callers, remove the method entirely
      (not removed — still used by `_broadcast_action` for command echo prevention)

### Task 1.4: Expose public adapter interface methods

**File(s):** `teleclaude/adapters/ui_adapter.py`, `teleclaude/core/adapter_client.py`

- [x] Add `drop_pending_output(session_id: str) -> int` to `UiAdapter` base class
      (returns 0 by default)
- [x] Rename `_move_badge_to_bottom` to `move_badge_to_bottom` on `UiAdapter` base class
- [x] Add `clear_turn_state(session: Session) -> None` to `UiAdapter` base class
      that calls `_clear_output_message_id` and `_set_char_offset(0)`
- [x] Update `break_threaded_turn` in adapter_client.py to call
      `adapter.drop_pending_output()` instead of `getattr(adapter, "_qos_scheduler")`
- [x] Update `break_threaded_turn` to call `adapter.clear_turn_state()` instead of
      private methods directly
- [x] Update `move_badge_to_bottom` in adapter_client.py to call the now-public method

---

## Phase 2: Adapter-local reflection handling

### Task 2.1: Telegram reflection handling

**File(s):** `teleclaude/adapters/telegram/message_ops.py`, `teleclaude/adapters/telegram_adapter.py`

- [x] In the send_message path (or a dedicated reflection helper): inspect
      `metadata.reflection_origin`
- [x] If `reflection_origin == self.ADAPTER_KEY`: suppress (return early, no send)
- [x] If reflection from another source: construct attribution header
      (`{actor_name} @ {ORIGIN}:\n\n`) and append separator (`\n\n---\n`)
- [x] Override `drop_pending_output()` to delegate to `self._qos_scheduler.drop_pending()`

### Task 2.2: Discord reflection handling

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] In the reflection rendering path: inspect `metadata.reflection_origin`
- [x] If `reflection_origin == self.ADAPTER_KEY`: suppress (return early, no send)
- [x] Cross-source reflections: continue using existing webhook rendering with
      actor name + avatar (already working)
- [x] Override `drop_pending_output()` to delegate to `self._qos_scheduler.drop_pending()`

---

## Phase 3: Parallelize delivery

### Task 3.1: Parallelize `deliver_inbound`

**File(s):** `teleclaude/core/command_handlers.py`

- [x] Keep DB update (`db.update_session`) sequential and BEFORE parallel block
      (echo guard reads persisted `last_message_sent`)
- [x] After DB update, run in parallel via `asyncio.gather`:
      - `tmux_io.process_text` (critical path)
      - `client.broadcast_user_input` (reflection broadcast)
      - `client.break_threaded_turn` (turn seal)
- [x] Preserve error handling: tmux failure is fatal (raise), broadcast/break failures
      are logged and non-fatal

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Move reflection formatting tests from core to adapter-level tests
- [x] Add test: `broadcast_user_input` sends to ALL adapters (no exclusion)
- [x] Add test: Telegram suppresses own-origin reflections
- [x] Add test: Discord suppresses own-origin reflections
- [x] Add test: `deliver_inbound` parallel execution (tmux, broadcast, break concurrent)
- [x] Run `make test`

### Task 4.2: Quality checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain
- [x] Grep for any remaining `_fanout_excluding` references in reflection paths
      (confirmed: only used in _broadcast_action for command echo prevention, not reflections)

---

## Phase 5: Review readiness

- [x] Confirm all requirements success criteria are met
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
      (no deferrals — all scope completed)
