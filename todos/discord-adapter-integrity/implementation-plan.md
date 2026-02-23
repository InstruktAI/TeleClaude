# Implementation Plan: discord-adapter-integrity

## Overview

Three changes to the Discord adapter: infrastructure hardening, per-computer categories, and forum input routing. All changes in `discord_adapter.py`.

---

## Phase 1: Infrastructure Validation (hardening)

### Task 1.1: Validate stored channel IDs before trusting them

**File(s):** `teleclaude/adapters/discord_adapter.py`

The `_ensure_category` method already validates cached IDs (lines 331-334): fetches the channel, proceeds to find-or-create if it returns None. Extend this pattern to all channel ID guards in `_ensure_discord_infrastructure`.

- [x] For each `if self._xxx_channel_id is None:` guard, add a validation step: if the ID is non-null, call `_get_channel(id)`. If it returns None, log a warning and clear the stale ID so provisioning proceeds.
- [x] Extract a helper: `_validate_channel_id(channel_id) -> int | None` that returns the ID if it resolves, None if stale.
- [x] Apply to: `_announcements_channel_id`, `_general_channel_id`, `_help_desk_channel_id`, `_escalation_channel_id`, `_operator_chat_channel_id`, `_all_sessions_channel_id`.
- [x] In `_ensure_project_forums`, change the guard `if td.discord_forum is not None: continue` to also validate the stored ID: call `_validate_channel_id(td.discord_forum)` and if it returns None, clear `td.discord_forum` so the loop body re-creates the forum.

---

## Phase 2: Per-Computer Project Categories

### Task 2.1: Category naming with computer name

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Change `_ensure_category(guild, "Projects", ...)` to `_ensure_category(guild, f"Projects - {config.computer.name}", ...)`.
- [x] Ensure the category key slug is clean: `projects_mozbook` not `projects_-_mozbook`. Either update `_ensure_category`'s key derivation or pass an explicit key.
- [x] The "Unknown" catch-all forum moves under the computer-specific category (it already follows the category reference).

### Task 2.2: Config persistence for per-computer categories

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Verify `_persist_discord_channel_ids` correctly stores the new category key (e.g. `categories.projects_mozbook`).
- [x] Old `categories.projects` key in existing config files won't conflict — new key is different, old category remains in Discord but is no longer managed.

### Task 2.3: Forum routing unchanged

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Verify `_build_project_forum_map` and `_resolve_target_forum` don't depend on category structure — they map `project_path -> forum_id` from trusted_dirs, which is per-computer by nature. No changes expected here, just verification.

---

## Phase 3: Forum Input Routing Fix

### Task 3.1: Determine forum type for incoming messages

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] In `_handle_on_message`, before calling `_resolve_or_create_session`, determine which managed forum the message belongs to (project forum vs help desk vs all-sessions).
- [x] The forum context is already available: `parent_id` is extracted at line 1003. Compare against `_project_forum_map.values()`, `_help_desk_channel_id`, `_all_sessions_channel_id`.
- [x] Pass the forum context to `_resolve_or_create_session` → `_create_session_for_message` so it can set the correct project path and role.

### Task 3.2: Resolve identity for forum messages

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] In `_create_session_for_message` (or a new project-forum-specific variant), resolve the Discord user's identity using the same mechanism as the DM handler (line 896): `identity.person_role or "member"`.
- [x] For help desk forum: retain `human_role: "customer"` (existing behavior).
- [x] For project forums / all-sessions: set `human_role` from identity resolution, defaulting to `"member"`.

### Task 3.3: Resolve project path from forum mapping

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] For project forum messages, resolve the project path from the forum's mapping (reverse lookup in `_project_forum_map`: forum_id → project_path).
- [x] For help desk messages, keep `config.computer.help_desk_dir`.
- [x] For all-sessions messages, use a sensible default (e.g. the first trusted_dir or a general workspace).

### Task 3.4: Add entry-level logging to `_handle_on_message`

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Add a DEBUG log at the entry of `_handle_on_message` with channel type, channel ID, and author info. Currently, silently dropped messages leave zero trace in the logs.

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Test stale channel ID validation clears and re-provisions.
- [x] Test project forum messages create sessions with correct role and project path.
- [x] Test help desk forum messages still create customer sessions.
- [x] Run `make test`.

### Task 4.2: Quality Checks

- [x] Run `make lint`.
- [x] Verify no unchecked implementation tasks remain.

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes.
- [x] Confirm implementation tasks are all marked `[x]`.
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable).
