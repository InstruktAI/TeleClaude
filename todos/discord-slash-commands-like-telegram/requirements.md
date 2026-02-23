# Requirements: discord-slash-commands-like-telegram

## Goal

Add Discord Application Commands (slash commands) to the Discord adapter, mirroring the full set of Telegram slash commands. Users in Discord forum threads should have the same command capabilities as Telegram users: session management, agent control, terminal key emulation, and help.

## Scope

### In scope:

- Register all `UiCommands` as Discord slash commands with autocomplete and descriptions.
- Guild-scoped command registration (instant availability, single-guild deployment).
- Session-context resolution from Discord forum threads (matching Telegram's topic-based resolution).
- Ephemeral responses for terminal control commands (no chat pollution).
- Command parameter support: `/ctrl` requires a key argument, `/shift_tab`/`/backspace`/arrow keys accept optional count.
- `/new_session` works from forum channels (creates a new thread).
- `/help` works anywhere (no session required).
- Agent commands (`/claude`, `/gemini`, `/codex`, `/agent_resume`, `/agent_restart`, `/claude_plan`) require session context.
- Integration with existing `UiAdapter._dispatch_command()` and `CommandService` infrastructure.
- Discord `CommandHandlersMixin` in a new `teleclaude/adapters/discord/` package, following the Telegram mixin pattern.

### Out of scope:

- Custom Discord UI components (buttons, selects, modals) for commands — text-based interaction only.
- Prefix commands (e.g., `!cancel`) — Discord Application Commands are the standard.
- DM slash commands — commands only work in guild channels/threads.
- Refactoring `CommandMapper.map_telegram_input()` to a generic method — Discord handlers create command objects directly, consistent with existing Discord adapter patterns.
- Moving `discord_adapter.py` into the package — it stays at its current path; the new package holds only the mixin.

## Success Criteria

- [ ] All 22 `UiCommands` registered as Discord slash commands with correct descriptions.
- [ ] Slash commands appear with autocomplete when typing `/` in Discord.
- [ ] Key commands (`/cancel`, `/enter`, `/escape`, etc.) work in session threads and send ephemeral confirmation.
- [ ] Agent commands (`/claude`, `/gemini`, `/codex`) start agents in session threads.
- [ ] `/agent_resume` and `/agent_restart` work in session threads.
- [ ] `/new_session` creates a new session from a forum channel.
- [ ] `/help` displays command list anywhere.
- [ ] `/ctrl d` sends CTRL+D to the session.
- [ ] `/shift_tab 3` sends 3x SHIFT+TAB.
- [ ] Commands outside a session thread return a clear error (except `/new_session` and `/help`).
- [ ] Existing Discord text message handling is unaffected.
- [ ] `make test` passes.
- [ ] `make lint` passes.

## Constraints

- Must use `discord.py >= 2.4.0` `app_commands.CommandTree` (already a dependency).
- Must not change existing `discord_adapter.py` import paths.
- Must use `UiAdapter._dispatch_command()` for commands that need pre/post hooks and broadcast.
- Guild-scoped registration only (no global command sync which takes up to an hour).
- Interaction acknowledgment must happen within Discord's 3-second window.

## Risks

- Discord API rate limits on command tree sync during development (mitigated by guild-scoped registration).
- Thread context may not always resolve to a session (mitigated by clear error messages).
- `discord.Client` does not have a built-in `CommandTree` — must be manually attached (known pattern in discord.py).
