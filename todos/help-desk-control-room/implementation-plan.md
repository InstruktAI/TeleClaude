# Implementation Plan: help-desk-control-room

## Overview

Extend the Discord adapter with a "control room" forum channel where all sessions are mirrored as threads. Leverage the existing `_broadcast_to_observers` fan-out in `AdapterClient` to deliver output to control room threads. Add admin intervention by handling messages in control room threads — same pattern as the Telegram adapter's supergroup topic message handling.

The approach builds on three proven patterns:

1. **Telegram supergroup topics** — Per-session forum topics with admin message routing (`channel_ops.py`, `input_handlers.py`)
2. **Discord help desk forum** — Thread creation in a specific forum channel (`discord_adapter.py:create_channel`)
3. **AdapterClient observer broadcast** — Fan-out output delivery to all registered UI adapters (`adapter_client.py:_broadcast_to_observers`)

## Phase 1: Configuration & Metadata

### Task 1.1: Add `control_room_channel_id` to Discord config

**File(s):** `teleclaude/config/__init__.py`

- [ ] Add `control_room_channel_id: int | None` to `DiscordConfig` dataclass (after `escalation_channel_id`)
- [ ] Add default `None` in `DEFAULT_CONFIG["discord"]`
- [ ] Add parsing in the Discord config loading section (same `_parse_optional_int` pattern as `help_desk_channel_id`)

### Task 1.2: Add `control_room_thread_id` to Discord adapter metadata

**File(s):** `teleclaude/core/models.py` (or wherever `DiscordAdapterMetadata` is defined)

- [ ] Add `control_room_thread_id: Optional[int] = None` to `DiscordAdapterMetadata`
- [ ] Ensure serialization/deserialization handles the new field

---

## Phase 2: Thread Creation & Lifecycle

### Task 2.1: Create control room thread on session start

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `create_channel` (or a new method called from `create_channel`), check if `control_room_channel_id` is configured
- [ ] If configured, create a thread in the control room forum using the session's display title
- [ ] Store the resulting thread ID in `adapter_metadata.ui.discord.control_room_thread_id`
- [ ] Persist the updated metadata to the database
- [ ] This runs alongside (not instead of) existing help desk thread creation — a customer session gets both threads

### Task 2.2: Thread title sync

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `update_channel_title`, also update the control room thread title if `control_room_thread_id` exists
- [ ] Best-effort: if the title update fails for the control room thread, log warning and continue

### Task 2.3: Thread close on session end

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `close_channel`, also close/archive the control room thread if it exists
- [ ] In `delete_channel`, also delete the control room thread if it exists

---

## Phase 3: Output Mirroring

### Task 3.1: Route output to control room thread

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `send_output_update` and `send_message`, ensure output is delivered to the control room thread
- [ ] For Discord-origin sessions: output already goes to the origin thread; additionally send to control room thread
- [ ] For non-Discord-origin sessions: the `_broadcast_to_observers` fan-out delivers output to the Discord adapter, which should route to the control room thread
- [ ] The Discord adapter's `_run_ui_lane` / `ensure_channel` mechanism creates the control room thread lazily if it doesn't exist yet

### Task 3.2: Handle dual-thread output routing

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] When a session has both a help desk thread and a control room thread, output must go to both
- [ ] The help desk thread gets the customer-facing formatted output
- [ ] The control room thread gets the same output (admins see exactly what the customer sees)
- [ ] Ensure `send_output_update` sends to both threads without blocking on either

---

## Phase 4: Admin Intervention

### Task 4.1: Detect and route admin messages in control room threads

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `_handle_on_message`, add detection for messages in control room threads
- [ ] Detection: check if the message's channel/thread parent is `control_room_channel_id`
- [ ] Resolve session from the thread ID via reverse lookup (Task 4.2)
- [ ] Route admin message to session via `ProcessMessageCommand` (same pattern as Telegram topic message handling)
- [ ] If session has `relay_status == "active"`, send a notice in the thread informing the admin to use the relay/escalation thread instead

### Task 4.2: Reverse lookup — control room thread to session

**File(s):** `teleclaude/core/db.py`

- [ ] Add query method to find session by `control_room_thread_id` in Discord adapter metadata
- [ ] Use the same `get_sessions_by_adapter_metadata` pattern as existing `topic_id` lookups
- [ ] Return the active session (not stopped/deleted)

---

## Phase 5: Forum Tags

### Task 5.1: Ensure forum tags on adapter startup

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] On Discord adapter startup (in `start` or initialization), check the control room forum for existing tags
- [ ] Create missing tags from the set: `help-desk`, `internal`, `maintenance`
- [ ] Cache tag IDs for use during thread creation
- [ ] Skip gracefully if control room channel is not configured

### Task 5.2: Apply tags on thread creation

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] When creating a control room thread (Task 2.1), determine the appropriate tag
- [ ] Tag logic: help desk project → `help-desk`; admin/member sessions → `internal`; jobs → `maintenance`
- [ ] Apply the tag to the thread using Discord's `applied_tags` parameter

---

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Unit test: control room thread created when session starts with `control_room_channel_id` configured
- [ ] Unit test: no control room thread when config is not set (graceful degradation)
- [ ] Unit test: output delivered to both help desk thread and control room thread for customer sessions
- [ ] Unit test: admin message in control room thread routes to session
- [ ] Unit test: relay conflict — admin warned when intervening in relayed session
- [ ] Unit test: thread closed when session ends
- [ ] Unit test: thread title updates when session title changes
- [ ] Run `make test`

### Task 6.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
