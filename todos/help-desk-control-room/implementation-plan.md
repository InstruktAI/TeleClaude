# Implementation Plan: help-desk-control-room

## Overview

Establish Discord as the structured admin observation layer. All daemon sessions are reflected as forum threads in project-specific Discord channels. Every non-customer person gets a personal workspace and Discord channel for direct assistant interaction. Telegram filters help-desk sessions from the internal supergroup. Discord uses threaded output exclusively (no in-message editing).

The work builds on the delivered `help-desk-discord` foundation: identity resolution, customer help-desk threads, escalation flow. This todo extends that to the full admin + member experience.

## Phase 1: Data Model & Config Foundation (R1, R2, R9)

### Task 1.1: Discord project channel mapping in config

**File(s):** `teleclaude/config/__init__.py`, `config.sample.yml`

- [ ] Add `channels` sub-config to `DiscordConfig`:
  - `all_sessions: int | None` — forum channel ID for ALL sessions
  - `projects: dict[str, int]` — map of project name → forum channel ID
- [ ] Initial values (from user):
  - `all_sessions: 1472884129241628735`
  - `projects.teleclaude: 1472884200066519160`
  - `projects.help-desk: 1472884271654899846`
- [ ] `help_desk_channel_id` and `escalation_channel_id` remain separate (customer jail)
- [ ] Update config loading to parse `discord.channels` section

### Task 1.2: Per-adapter output state in DiscordAdapterMetadata

**File(s):** `teleclaude/core/models.py`

- [ ] Add `channel_threads: dict[str, ChannelThreadState]` to `DiscordAdapterMetadata`
  - `ChannelThreadState`: `thread_id: int`, `output_message_id: str | None`
  - Keys: channel key strings like `"all_sessions"`, `"project:teleclaude"`, `"help_desk"`
- [ ] Add `output_message_id: str | None` to `DiscordAdapterMetadata` (adapter-level, separate from shared session column)
- [ ] Add `char_offset: int = 0` to `DiscordAdapterMetadata`
- [ ] Update deserialization in `_deserialize_discord_metadata` to handle new fields

### Task 1.3: Discord adapter per-adapter output_message_id overrides

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Override `_get_output_message_id(session)` → read from `discord_meta.output_message_id`
- [ ] Override `_store_output_message_id(session, message_id)` → write to `discord_meta.output_message_id`
- [ ] Override `_clear_output_message_id(session)` → clear `discord_meta.output_message_id`
- [ ] Telegram continues using the shared `output_message_id` column — no change to Telegram

### Task 1.4: Decouple char_offset from Telegram metadata

**File(s):** `teleclaude/adapters/ui_adapter.py`, `teleclaude/core/agent_coordinator.py`

- [ ] `send_threaded_output`: replace `telegram_meta.char_offset` access with adapter-specific method
- [ ] Add `_get_char_offset(session) -> int` and `_set_char_offset(session, offset) -> Session` to `UiAdapter` base
- [ ] Telegram adapter: reads/writes `telegram_meta.char_offset` (existing behavior)
- [ ] Discord adapter: reads/writes `discord_meta.char_offset`
- [ ] `AgentCoordinator.handle_agent_stop`: reset char_offset via adapter-agnostic path (not hardcoded `telegram_meta`)

---

## Phase 2: Discord ensure_channel & Thread Lifecycle (R3, R11)

### Task 2.1: Discord channel resolution and thread creation

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Override `ensure_channel(session, title)` in Discord adapter
- [ ] Implement `_resolve_target_channels(session) -> list[ChannelTarget]`:
  1. Read role from `session` metadata (`channel_metadata.human_role`)
  2. Map `session.project_path` to project key via config `discord.channels.projects`
  3. Role-based resolution:
     - `role == customer` → `[help_desk_channel_id]` (or `escalation_channel_id` if escalated)
     - `role != customer` → `[all_sessions]` + `[projects[project_key]]` (if mapped)
  4. An admin working on the help-desk project → `all_sessions` + `projects.help-desk` — NEVER `help_desk_channel_id`
- [ ] For each target channel: if no thread_id in `channel_threads[key]`, create forum thread and store
- [ ] On subsequent calls: return session with existing thread_ids — no re-creation
- [ ] Set primary `discord_meta.thread_id` to the first target channel's thread (for message routing)
- [ ] Return `Session` (updated with thread metadata) or `None` if session should be skipped by this adapter

### Task 2.2: close_channel deletes threads from ALL channels

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] `close_channel`: iterate `channel_threads` and delete each thread (not archive+lock)
- [ ] Must handle partial failures gracefully (some threads may already be deleted)
- [ ] Clear `channel_threads` after deletion

---

## Phase 3: Session Reflection & Output Routing (R4, R10, R12)

### Task 3.1: ALL non-customer sessions reflected in Discord

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] `send_threaded_output`: change `broadcast=False` to `broadcast=True` — all sessions mirror threaded output to Discord observer
- [ ] Discord adapter's `ensure_channel` (from Task 2.1) auto-creates threads for non-Discord-origin sessions on first delivery
- [ ] Channel resolution (Task 2.1) enforces role-based routing: non-customer → admin channels, customer → customer jail
- [ ] Response routing unchanged: responses go back to origin adapter via existing `_route_to_ui` — observation is passive mirroring
- [ ] Admin sessions on help-desk project → reflected in `projects.help-desk` (not `help_desk_channel_id`)

### Task 3.2: Threaded output ONLY for Discord (feature flag)

**File(s):** `teleclaude/core/feature_flags.py`, `teleclaude/adapters/discord_adapter.py`

- [ ] Remove `AgentName.GEMINI` hardcheck in `is_threaded_output_enabled`
- [ ] Add session-aware variant: `is_threaded_output_enabled_for_session(session)` that returns True when:
  - Experiment flag is enabled for the agent (existing mechanism), OR
  - Session's origin adapter is Discord (unconditionally threaded)
- [ ] Update callers in `AgentCoordinator` and `AdapterClient` to use session-aware check
- [ ] `send_output_update` suppression already works — just needs the broadened flag check
- [ ] Override `_build_metadata_for_thread()` in Discord adapter (no MarkdownV2 parse mode)
- [ ] Override `_send_footer()` as no-op in Discord adapter (threaded output has no footer)

### Task 3.3: Multi-channel output fan-out

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Override `send_threaded_output` (or the underlying delivery method) to fan out to ALL threads in `channel_threads`
- [ ] A session with threads in `all_sessions` + `projects.teleclaude` receives identical output in both threads
- [ ] Fan-out is best-effort per thread — failure in one channel must not block delivery to others
- [ ] `update_channel_title` also fans out to all threads in `channel_threads`
- [ ] `send_message` (notices, status) fans out to all threads

---

## Phase 4: Personal Workspaces & Member Channels (R5, R6, R7)

### Task 4.1: Personal workspace bootstrap

**File(s):** `teleclaude/project_setup/personal_workspace_bootstrap.py` (new), `templates/personal-assistant/` (new)

- [ ] Create template directory `templates/personal-assistant/`:
  - `CLAUDE.md` (references AGENTS.md)
  - `AGENTS.master.md` (personal assistant instructions — warm, contextual, identity-aware)
  - `AGENTS.md` (generated)
  - `teleclaude.yml` (project config)
  - `.gitignore`
  - `docs/` structure (same as help-desk: project/ + global/organization/)
- [ ] `bootstrap_personal_workspace(person_name, person_config)`:
  - Directory: `~/.teleclaude/people/{name}/workspace/`
  - copytree from `templates/personal-assistant/`
  - `git init` + `telec init` + initial commit
  - Register workspace path in `trusted_dirs` so daemon recognizes it as a valid project
  - Idempotent: skip if directory already exists
- [ ] Bootstrap all non-customer people at daemon startup (alongside `bootstrap_help_desk`)

### Task 4.2: Member personal Discord channels

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] On Discord adapter startup (after gateway ready): ensure each configured person has a Discord channel
- [ ] Channel name: person's username (from people config)
- [ ] Channel permissions: the person (by Discord user_id) + the bot — private 1:1 channel
- [ ] Store auto-created channel ID in `~/.teleclaude/people/{name}/teleclaude.yml` → `discord.channel_id`
- [ ] Idempotent: skip if channel already exists (check stored channel_id, verify it still exists in guild)

### Task 4.3: Inbound routing for member channels and observation threads

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] **Personal channels**: `_handle_on_message` routes messages from a member's personal channel to their workspace
  - Identity resolution: Discord `user_id` → person → `~/.teleclaude/people/{name}/workspace/` path
  - `_create_session_for_message`: use person's workspace path instead of hardcoded `help_desk_dir`
  - `channel_metadata.human_role`: set from identity resolver (admin/member/contributor), not hardcoded "customer"
  - Session title: `"{PersonName}: {first_message_summary}"` or similar
- [ ] **Observation threads**: when message arrives in an admin observation thread (`all_sessions` or `projects.*`)
  - Reverse lookup: thread_id → session via `channel_threads` stored in adapter metadata
  - Route the message as user input to the existing session (no new session creation)
  - Same paradigm as Telegram supergroup topic interjection

---

## Phase 5: Telegram Filter (R8)

### Task 5.1: Filter help-desk sessions from Telegram supergroup

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Telegram `ensure_channel`: skip sessions whose `project_path` matches the help-desk project directory
- [ ] Return `None` (or equivalent skip signal) for help-desk sessions — no topic created in current supergroup
- [ ] Current Telegram supergroup remains internal-only
- [ ] Future: separate Telegram supergroup for public-facing sessions (out of scope — documented deferral)

---

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Unit: Discord `ensure_channel` creates threads in correct target channels based on project mapping
- [ ] Unit: `channel_threads` stored/retrieved correctly in DiscordAdapterMetadata
- [ ] Unit: Per-adapter `output_message_id` read/write in Discord adapter
- [ ] Unit: `is_threaded_output_enabled_for_session` returns True for Discord-origin sessions
- [ ] Unit: `char_offset` read/write works through adapter-specific methods (not Telegram-hardcoded)
- [ ] Unit: `close_channel` deletes threads from ALL channels in `channel_threads`
- [ ] Unit: Customer sessions only get help_desk_channel thread (not admin channels)
- [ ] Unit: Admin session on help-desk project → `all_sessions` + `projects.help-desk`, NOT `help_desk_channel_id`
- [ ] Unit: Multi-channel fan-out delivers output to all threads in `channel_threads`
- [ ] Unit: Message in observation thread → routed to existing session (reverse thread_id lookup)
- [ ] Unit: Telegram `ensure_channel` skips help-desk project sessions
- [ ] Unit: Existing Gemini threaded output still works (regression)
- [ ] Unit: Standard poller output still works for Telegram non-threaded sessions (regression)
- [ ] Run `make test`

### Task 6.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 7: Review Readiness

- [ ] Confirm all R1-R12 requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly (Telegram public supergroup is known deferral)
