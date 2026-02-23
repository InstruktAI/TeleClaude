# Implementation Plan: discord-slash-commands-like-telegram

## Overview

Add Discord Application Commands by attaching an `app_commands.CommandTree` to the existing `discord.Client`, creating a `CommandHandlersMixin` in a new `teleclaude/adapters/discord/` package, and dynamically registering all `UiCommands` as guild-scoped slash commands. The approach mirrors Telegram's mixin-based architecture while adapting to Discord's interaction model (acknowledge → dispatch → ephemeral response).

## Phase 1: Package Structure & CommandTree

### Task 1.1: Create `teleclaude/adapters/discord/` package

**File(s):** `teleclaude/adapters/discord/__init__.py`

- [ ] Create `teleclaude/adapters/discord/__init__.py` with an empty init (or minimal docstring).
- [ ] This package holds the Discord command handlers mixin. The main `discord_adapter.py` stays at its current path.

### Task 1.2: Attach `CommandTree` to Discord client

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `start()`, after creating `self._client`, create `self._tree = self._discord.app_commands.CommandTree(self._client)`.
- [ ] Store `self._tree` as an instance attribute (initialized to `None` in `__init__`).
- [ ] Call `self._register_slash_commands()` after creating the tree (before starting the gateway).
- [ ] In `_handle_on_ready()`, sync the command tree to the guild: `await self._tree.sync(guild=discord.Object(id=self._guild_id))`.
- [ ] Add error handling for tree sync failures (log warning, don't block startup).
- [ ] In `stop()`, clear the tree reference.

### Task 1.3: Register slash commands dynamically

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Add `_register_slash_commands()` method that iterates `UiCommands` and creates `app_commands.Command` objects.
- [ ] For each command, use the UiCommands description as the slash command description.
- [ ] Parameter definitions per command category:
  - **Key commands with no args** (`cancel`, `cancel2x`, `kill`, `enter`, `escape`, `escape2x`, `tab`): no parameters.
  - **Key commands with optional count** (`shift_tab`, `backspace`, `key_up`, `key_down`, `key_left`, `key_right`): optional `count` integer parameter.
  - **`ctrl`**: required `key` string parameter (e.g., "d" for CTRL+D).
  - **Agent commands** (`claude`, `gemini`, `codex`): optional `args` string parameter.
  - **`new_session`**: optional `title` string parameter.
  - **`agent_resume`, `agent_restart`, `claude_plan`, `help`**: no parameters.
- [ ] Add each command to `self._tree` via `self._tree.add_command(cmd, guild=discord.Object(id=self._guild_id))`.
- [ ] Each command callback delegates to the appropriate `_handle_*` method from the mixin.

## Phase 2: Command Handler Mixin

### Task 2.1: Create `CommandHandlersMixin` with session resolution

**File(s):** `teleclaude/adapters/discord/command_handlers.py`

- [ ] Create `CommandHandlersMixin` class following the Telegram pattern.
- [ ] Document required host class interface: `client`, `_discord`, `_guild_id`, `_dispatch_command`, `_metadata`, `ADAPTER_KEY`.
- [ ] Implement `_get_session_from_thread(interaction)`: extract `(channel_id, thread_id)` from `interaction.channel` (same extraction logic as `_extract_channel_ids`), then call existing `_find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)` which looks up via `db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id)`.
- [ ] Implement `_require_session_from_thread(interaction)`: like above but sends ephemeral error if not found.
- [ ] Authorization: reuse existing managed-forum gating pattern (`_is_managed_message` / `_get_managed_forum_ids`). Discord does not use a user whitelist — if the user can type in the managed forum thread, they can use commands.

### Task 2.2: Implement simple command handlers (key commands)

**File(s):** `teleclaude/adapters/discord/command_handlers.py`

- [ ] Implement `_handle_discord_simple_command(interaction, event, args)` template method:
  1. Resolve session from thread via `_require_session_from_thread()`.
  2. Create `KeysCommand(session_id=session.session_id, key=event, args=args)`.
  3. Send ephemeral acknowledgment: `await interaction.response.send_message(f"Sent {event}", ephemeral=True)`.
  4. Dispatch via `_dispatch_command()` with `get_command_service().keys(cmd)`.
- [ ] Register dynamic handlers for all key commands that delegate to this template.

### Task 2.3: Implement agent command handlers

**File(s):** `teleclaude/adapters/discord/command_handlers.py`

- [ ] Implement `_handle_discord_agent_command(interaction, agent_name, args)`:
  1. Resolve session from thread.
  2. Create `StartAgentCommand(session_id, agent_name, args)`.
  3. Defer the interaction (agent start may take time): `await interaction.response.defer(ephemeral=True)`.
  4. Dispatch via `_dispatch_command()`.
  5. Follow up: `await interaction.followup.send(f"Starting {agent_name}...", ephemeral=True)`.
- [ ] Implement `_handle_discord_agent_resume(interaction)`:
  1. Resolve session.
  2. Create `ResumeAgentCommand(session_id)`.
  3. Dispatch and respond.
- [ ] Implement `_handle_discord_agent_restart(interaction)`:
  1. Resolve session.
  2. Create `RestartAgentCommand(session_id)`.
  3. Dispatch and respond.
- [ ] Implement `_handle_discord_claude_plan(interaction)`:
  1. Delegate to simple command handler with event="shift_tab", args=["3"].

### Task 2.4: Implement special handlers (new_session, help)

**File(s):** `teleclaude/adapters/discord/command_handlers.py`

- [ ] Implement `_handle_discord_new_session(interaction, title)`:
  1. Verify interaction is in a forum channel (not a thread).
  2. Defer the interaction.
  3. Create `CreateSessionCommand(project_path, title, origin=InputOrigin.DISCORD.value)`.
  4. Dispatch via `get_command_service().create_session(cmd)`.
  5. Follow up with session creation confirmation.
- [ ] Implement `_handle_discord_help(interaction)`:
  1. Build help text from `UiCommands` dictionary (like Telegram's `_handle_help`).
  2. Send ephemeral response with formatted command list.

## Phase 3: Integration

### Task 3.1: Wire mixin into DiscordAdapter

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Add `CommandHandlersMixin` to `DiscordAdapter` inheritance chain.
- [ ] Import mixin from `teleclaude.adapters.discord.command_handlers`.
- [ ] Verify `_get_command_handlers()` from `UiAdapter` discovers the new `_handle_*` methods.

### Task 3.2: Verify interaction routing

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Verify that `CommandTree(client)` auto-dispatches interactions without explicit `on_interaction` registration. In discord.py 2.x, `CommandTree.__init__` hooks into the client's internal `_command_tree` attribute for automatic dispatch.
- [ ] If auto-dispatch does NOT work: add `on_interaction` event in `_register_gateway_handlers()` that calls `await self._tree.interaction_check(interaction)` followed by `await self._tree._call(interaction)` (or the documented dispatch method).
- [ ] Test by invoking a registered slash command and confirming the handler fires.

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Add unit tests for `CommandHandlersMixin` methods (session resolution, command creation).
- [ ] Add unit tests for slash command registration (verify all UiCommands are registered).
- [ ] Add integration test: mock Discord interaction → verify command dispatch.
- [ ] Run `make test`.

### Task 4.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
