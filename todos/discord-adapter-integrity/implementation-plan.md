# Implementation Plan: discord-adapter-integrity

## Overview

Three changes that together bring Discord (and threaded Telegram) to full output integrity and clean multi-computer infrastructure. Ordered so each phase builds on the previous: infrastructure hardening first, per-computer categories second, delivery fix last.

---

## Phase 1: Infrastructure Validation (hardening)

### Task 1.1: Validate stored channel IDs before trusting them

**File(s):** `teleclaude/adapters/discord_adapter.py`

The `_ensure_category` method already validates cached IDs (lines 331-334): fetches the channel, proceeds to find-or-create if it returns None. Extend this pattern to all channel ID guards in `_ensure_discord_infrastructure`.

- [ ] For each `if self._xxx_channel_id is None:` guard, add a validation step: if the ID is non-null, call `_get_channel(id)`. If it returns None, log a warning and clear the stale ID so provisioning proceeds.
- [ ] Extract a helper: `_validate_channel_id(channel_id) -> int | None` that returns the ID if it resolves, None if stale.
- [ ] Apply to: `_announcements_channel_id`, `_general_channel_id`, `_help_desk_channel_id`, `_escalation_channel_id`, `_operator_chat_channel_id`, `_all_sessions_channel_id`.
- [ ] In `_ensure_project_forums`, change the guard `if td.discord_forum is not None: continue` to also validate the stored ID: call `_validate_channel_id(td.discord_forum)` and if it returns None, clear `td.discord_forum` so the loop body re-creates the forum.

---

## Phase 2: Per-Computer Project Categories

### Task 2.1: Category naming with computer name

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Change `_ensure_category(guild, "Projects", ...)` to `_ensure_category(guild, f"Projects - {config.computer.name}", ...)`.
- [ ] Ensure the category key slug is clean: `projects_mozbook` not `projects_-_mozbook`. Either update `_ensure_category`'s key derivation or pass an explicit key.
- [ ] The "Unknown" catch-all forum moves under the computer-specific category (it already follows the category reference).

### Task 2.2: Config persistence for per-computer categories

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Verify `_persist_discord_channel_ids` correctly stores the new category key (e.g. `categories.projects_mozbook`).
- [ ] Old `categories.projects` key in existing config files won't conflict — new key is different, old category remains in Discord but is no longer managed.

### Task 2.3: Forum routing unchanged

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Verify `_build_project_forum_map` and `_resolve_target_forum` don't depend on category structure — they map `project_path -> forum_id` from trusted_dirs, which is per-computer by nature. No changes expected here, just verification.

---

## Phase 3: Text Delivery Fix

### Task 3.1: Add `trigger_incremental_output` to AgentCoordinator

**File(s):** `teleclaude/core/agent_coordinator.py`

- [ ] Add public method `trigger_incremental_output(session_id: str) -> bool` after `_maybe_send_incremental_output`.
- [ ] Fast-path: fetch session, check `is_threaded_output_enabled(session.active_agent)`, return False if not enabled.
- [ ] Construct minimal `AgentOutputPayload()` with defaults (the existing method falls back to `session.active_agent` and `session.native_log_file`).
- [ ] Delegate to `self._maybe_send_incremental_output(session_id, payload)`.

### Task 3.2: Expose AgentCoordinator to the poller

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/daemon.py`

- [ ] Add `self.agent_coordinator: "AgentCoordinator | None" = None` to `AdapterClient.__init__`.
- [ ] Add `TYPE_CHECKING` import for `AgentCoordinator`.
- [ ] In `daemon.py`, after `self.client.agent_event_handler = self.agent_coordinator.handle_event` (line 251), add `self.client.agent_coordinator = self.agent_coordinator`.

### Task 3.3: Trigger incremental output from the poller

**File(s):** `teleclaude/core/polling_coordinator.py`

- [ ] In the `OutputChanged` handler, after the `send_output_update` call (after line 764), add:
  ```python
  coordinator = adapter_client.agent_coordinator
  if coordinator:
      try:
          await coordinator.trigger_incremental_output(event.session_id)
      except Exception:
          logger.warning("Poller-triggered incremental output failed for %s", session_id[:8], exc_info=True)
  ```
- [ ] This fires for ALL sessions but `trigger_incremental_output` fast-rejects non-threaded sessions before any I/O.

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Test `trigger_incremental_output` sends output for threaded sessions.
- [ ] Test `trigger_incremental_output` is a no-op for non-threaded sessions.
- [ ] Test stale channel ID validation clears and re-provisions.
- [ ] Run `make test`.

### Task 4.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
