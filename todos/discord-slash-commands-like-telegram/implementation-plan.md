# Implementation Plan: discord-slash-commands-like-telegram

## Overview

Add a button-based session launcher to Discord project forums and a single `/cancel` slash command for agent interruption. The launcher posts a persistent message with agent buttons in each forum. Clicking a button creates a session with the selected agent in slow mode. The approach uses `discord.ui.View`/`Button` for the launcher and `app_commands.CommandTree` for `/cancel`.

## Phase 1: Infrastructure

### Task 1.1: Create `teleclaude/adapters/discord/` package

**File(s):** `teleclaude/adapters/discord/__init__.py`

- [ ] Create package with empty `__init__.py`.

### Task 1.2: Determine available agents at startup

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Add helper `_get_enabled_agents() -> list[str]` that returns agent names where `config.agents[name].enabled` is True.
- [ ] Add property `_multi_agent` that returns `len(self._get_enabled_agents()) > 1`.
- [ ] Add property `_default_agent` that returns the first enabled agent name (fallback for single-agent mode).

### Task 1.3: Build reverse forum-to-project map

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] After `_build_project_forum_map()`, build `_forum_project_map: dict[int, str]` (forum_id → project_path) by inverting `_project_forum_map`.
- [ ] Add `_resolve_project_from_forum(forum_id: int) -> str | None` that looks up the project path.

## Phase 2: Button Launcher

### Task 2.1: Create persistent View and Button classes

**File(s):** `teleclaude/adapters/discord/session_launcher.py`

- [ ] Create `SessionLauncherView(discord.ui.View)` with `timeout=None`.
- [ ] Constructor takes list of enabled agent names and a callback coroutine.
- [ ] For each agent, create `discord.ui.Button(label=agent_name.capitalize(), custom_id=f"launch:{agent_name}", style=ButtonStyle.primary)`.
- [ ] Button callback: call the provided coroutine with `(interaction, agent_name)`.

### Task 2.2: Implement launcher message lifecycle

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Add `_post_or_update_launcher(forum_id: int)` method:
  1. Check `system_settings` for existing launcher message ID (`discord_launcher:{forum_id}`).
  2. If exists, try to edit it (update buttons in case agent list changed). If edit fails (deleted), create new.
  3. If not exists, post new message with `SessionLauncherView` to the forum channel.
  4. Store message ID in `system_settings`.
- [ ] Message text: "Start a session" (plain, no emoji).
- [ ] Only post launcher when `_multi_agent` is True.

### Task 2.3: Post launchers on startup

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `_handle_on_ready()`, after `_ensure_discord_infrastructure()`, iterate `_project_forum_map` and call `_post_or_update_launcher(forum_id)` for each forum.
- [ ] Skip forums where `_multi_agent` is False.
- [ ] Add error handling per forum (log warning, continue to next).
- [ ] Re-register the persistent view with the client so button callbacks work after restart: `self._client.add_view(view)` with matching `custom_id`s.

### Task 2.4: Handle button click → create session

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Implement button callback `_handle_launcher_click(interaction, agent_name)`:
  1. Defer the interaction (ephemeral): `await interaction.response.defer(ephemeral=True)`.
  2. Resolve project: `_resolve_project_from_forum(interaction.channel_id)` (the forum ID from the channel where the launcher message lives).
  3. Create session: `CreateSessionCommand(project_path=project_path, auto_command=f"agent {agent_name}", origin=InputOrigin.DISCORD.value)`.
  4. Dispatch via `get_command_service().create_session(cmd)`.
  5. Follow up: `await interaction.followup.send(f"Starting {agent_name}...", ephemeral=True)`.

## Phase 3: Fix Single-Agent Auto-Start

### Task 3.1: Fix `_create_session_for_message` for operator sessions

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] When message is NOT from help desk forum: derive `project_path` from `_resolve_project_from_forum(channel_id)` instead of hardcoding `help_desk_dir`.
- [ ] When message is NOT from help desk forum: set `auto_command=f"agent {self._default_agent}"` and omit `human_role=customer`.
- [ ] When message IS from help desk forum: preserve existing behavior (help_desk_dir, customer role, agent claude).
- [ ] Always use thinking_mode `slow` for auto-started agents.

## Phase 4: `/cancel` Slash Command

### Task 4.1: Attach CommandTree and register `/cancel`

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `start()`, after creating `self._client`, create `self._tree = self._discord.app_commands.CommandTree(self._client)`.
- [ ] Store `self._tree` as instance attribute (initialized to `None` in `__init__`).
- [ ] Register single command: `app_commands.Command(name="cancel", description="Send CTRL+C to interrupt the current agent", callback=self._handle_cancel_slash)`.
- [ ] Add command to tree guild-scoped: `self._tree.add_command(cmd, guild=discord.Object(id=self._guild_id))`.

### Task 4.2: Sync tree on ready

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `_handle_on_ready()`, sync command tree: `await self._tree.sync(guild=discord.Object(id=self._guild_id))`.
- [ ] Wrap in try/except (log warning on failure, don't block startup).

### Task 4.3: Implement `/cancel` handler

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Implement `_handle_cancel_slash(interaction)`:
  1. Resolve session from thread via existing `_find_session(channel_id, thread_id, user_id)` (extract IDs from `interaction.channel`).
  2. If no session: `await interaction.response.send_message("No active session in this thread.", ephemeral=True)` and return.
  3. Create `KeysCommand(session_id=session.session_id, key="cancel", args=[])`.
  4. Send ephemeral acknowledgment: `await interaction.response.send_message("Sent CTRL+C", ephemeral=True)`.
  5. Dispatch: `await get_command_service().keys(cmd)`.

### Task 4.4: Clean up tree on stop

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `stop()`, clear tree reference.

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Unit test: `_get_enabled_agents()` with different config states.
- [ ] Unit test: `SessionLauncherView` creates correct buttons for given agent list.
- [ ] Unit test: `_resolve_project_from_forum()` returns correct project path.
- [ ] Unit test: `/cancel` handler with mock interaction (session found / not found).
- [ ] Unit test: `_create_session_for_message` uses forum-derived project for non-help-desk threads.
- [ ] Run `make test`.

### Task 5.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
