# Implementation Plan: discord-session-routing

## Overview

Four coordinated changes to Discord session routing, executed in dependency order: (1) move title construction into adapters, (2) enable per-project forums with project-aware routing, (3) replace channel gating with role-based acceptance, (4) enrich thread headers. The changes are scoped to the adapter layer and `adapter_client`, with no domain model changes.

## Phase 1: Adapter-Owned Title Construction

### Task 1.1: Change `ensure_channel` signature to drop `title` parameter

**File(s):** `teleclaude/adapters/ui_adapter.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`

- [ ] Update `UiAdapter.ensure_channel(self, session, title)` base class signature to `ensure_channel(self, session)`.
- [ ] Update `TelegramAdapter.ensure_channel()` to accept only `session` and call `get_display_title_for_session(session)` internally to build its metadata-rich title.
- [ ] Update `DiscordAdapter.ensure_channel()` to accept only `session` and build its own title (see Task 1.3).

### Task 1.2: Remove central title construction from `adapter_client`

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] In `_route_to_ui()` (line ~257): remove the `get_display_title_for_session()` call. Pass only `session` to `ensure_ui_channels()`.
- [ ] Change `ensure_ui_channels(self, session, title)` signature to `ensure_ui_channels(self, session)`. Update the loop at line ~987 to call `adapter.ensure_channel(session)` without `title`.
- [ ] Remove or relocate the second `get_display_title_for_session()` call at line ~592 if it exists for the same purpose.
- [ ] Remove the `get_display_title_for_session` import if no longer used in this file.
- [ ] Search for all other call sites of `ensure_ui_channels` and update them to drop the `title` argument.

### Task 1.3: Discord adapter title strategy

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `ensure_channel()`, determine the title strategy based on routing target:
  - **Per-project forum:** Title is just the session description (e.g., "Fix auth flow"). Project context is implicit from the forum.
  - **Catch-all fallback:** Title is `{project}: {description}` to preserve discoverability.
- [ ] Use `session.title` (the description) directly for per-project forums.
- [ ] For catch-all, use `get_short_project_name()` + description.
- [ ] Pass the constructed title to `create_channel()` internally.

---

## Phase 2: Per-Project Forum Routing

### Task 2.1: Enable per-project forums by default

**File(s):** `teleclaude/core/feature_flags.py`, `teleclaude/adapters/discord_adapter.py`

- [ ] Remove the `discord_project_forum_mirroring` feature flag check (or default it to `True`). The `_ensure_project_forums()` call in `_ensure_discord_infrastructure()` should always execute when Discord is configured.
- [ ] Clean up the feature flag constant if fully removed.

### Task 2.2: Project-aware session routing in `_resolve_target_forum`

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Extend `_resolve_target_forum(session)` to check the session's `project_path` against trusted dirs' `discord_forum` IDs.
- [ ] Logic: (1) customer sessions -> help desk forum, (2) match `session.project_path` to a trusted dir with a `discord_forum` -> that forum, (3) fallback -> `_all_sessions_channel_id`.
- [ ] Cache the project-path-to-forum mapping at startup (after `_ensure_project_forums()`) to avoid repeated config lookups.

---

## Phase 3: Role-Based Message Acceptance

### Task 3.1: Replace `_is_help_desk_message` with role-aware gating

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Rename or replace `_is_help_desk_message()` with `_is_managed_message()` (or similar).
- [ ] New logic: build the set of managed forum IDs from: help desk channel, all-sessions channel, and all project forum IDs. Accept messages from any managed forum or thread within one.
- [ ] This ensures project forum threads are accepted, not just help desk and all-sessions threads.
- [ ] Keep the dev/test mode fallback (`_help_desk_channel_id is None` -> accept all).

### Task 3.2: Role-based authorization for message handling

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] After message acceptance (channel check), add role-based authorization:
  - Admins/members: accepted from any managed channel.
  - Customers: only accepted from help desk threads.
- [ ] Use `session.human_role` (already exists) to determine the sender's role. Reference existing `_is_customer_session()` pattern at line 168.
- [ ] This is a refinement on top of the channel check, not a replacement.

---

## Phase 4: Enriched Thread Header (Topper)

### Task 4.1: Build session metadata topper content

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Create a method `_build_thread_topper(session)` that produces formatted metadata:
  ```
  project: {project_name} | agent: {agent}/{speed}
  tc: {session_id}
  ai: {native_session_id}
  ```
- [ ] Handle missing fields gracefully (e.g., no native session ID yet at creation time).

### Task 4.2: Replace placeholder first message

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `_create_forum_thread()` (line ~1286): change the default `content` parameter from `"Initializing Help Desk session..."` to use `_build_thread_topper()`.
- [ ] The topper is passed as `content` to `create_thread_fn(name=title, content=topper)`.
- [ ] Update all call sites of `_create_forum_thread()` to pass the session so the topper can be built.

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Add or update tests for `_resolve_target_forum()` covering: customer routing, project-match routing, fallback routing.
- [ ] Add or update tests for the renamed/replaced message acceptance method covering: managed forum acceptance, project forum acceptance, non-managed forum rejection.
- [ ] Add or update tests for Discord title strategy (description-only for project forums, prefixed for catch-all).
- [ ] Verify Telegram title construction is unchanged.
- [ ] Run `make test`.

### Task 5.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.
- [ ] Verify `ensure_channel` signature is consistent across all adapter implementations.
- [ ] Verify no remaining references to the old `ensure_ui_channels(session, title)` signature.

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
