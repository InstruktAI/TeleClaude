# Requirements: discord-slash-commands-like-telegram

## Goal

Give Discord users the same session-launching experience as Telegram users: pick an agent, start a session — plus a single `/cancel` escape hatch to interrupt running agents. The approach uses persistent button messages in project forums for agent selection and one Discord slash command for interruption.

## Scope

### In scope:

- **Session launcher buttons**: persistent pinned message in each project forum with one button per enabled agent (e.g., "Claude", "Gemini", "Codex"). Clicking a button creates a session in that forum's project with the selected agent in slow (most capable) mode.
- **Conditional display**: only show the launcher when more than one agent is enabled in `config.agents`. When only one agent is enabled, auto-start it on first message — no button menu.
- **`/cancel` slash command**: single Discord Application Command registered guild-scoped. Sends CTRL+C to the session. Ephemeral acknowledgment. Works in session threads only.
- **Forum-to-project resolution**: reverse `_project_forum_map` (forum_id → project_path) to derive project from the forum where the button was clicked.
- **Fix `_create_session_for_message`**: currently hardcodes `help_desk_dir` and `human_role=customer` for all Discord sessions. Must derive project from forum context for operator sessions.
- **Launcher lifecycle**: post or update launcher message on `on_ready`. Store message ID per forum in `system_settings`. Survive daemon restarts.

### Out of scope:

- Terminal key emulation commands (tab, escape, arrow keys, backspace, etc.) — not needed for Discord.
- Agent commands as slash commands (`/claude`, `/gemini`, `/codex`) — covered by button launcher.
- `/help` slash command — buttons are self-explanatory.
- Project picker dropdown in general channel.
- Custom Discord UI components beyond buttons (modals, select menus).
- Telegram changes.

## Success Criteria

- [ ] Project forums with multiple enabled agents show a pinned launcher message with one button per enabled agent.
- [ ] Project forums with a single enabled agent show no launcher; first message auto-starts that agent in slow mode.
- [ ] Clicking an agent button creates a session thread in that forum with the correct project and agent.
- [ ] Agent always starts in slow (most capable) thinking mode.
- [ ] Button labels show only the agent name (e.g., "Claude", not "Claude slow").
- [ ] Launcher message persists across daemon restarts (message ID stored in system_settings).
- [ ] `/cancel` sends CTRL+C to the session and shows ephemeral confirmation.
- [ ] `/cancel` outside a session thread returns a clear ephemeral error.
- [ ] Operator sessions created from project forums use the correct project_path (not help_desk_dir).
- [ ] Help desk sessions (from help_desk forum) continue to work as before.
- [ ] Existing Discord text message handling is unaffected.
- [ ] `make test` passes.
- [ ] `make lint` passes.

## Constraints

- Must use `discord.py >= 2.4.0` `discord.ui.View` and `discord.ui.Button` for persistent buttons.
- Must use `discord.py >= 2.4.0` `app_commands.CommandTree` for `/cancel` registration.
- Button views must use `timeout=None` to survive bot restarts.
- Guild-scoped slash command registration only.
- Interaction acknowledgment within Discord's 3-second window.
- Must not change existing `discord_adapter.py` import paths.

## Risks

- Discord rate limits on message posting during startup with many forums (mitigated: post sequentially, log warnings).
- Persistent views require `custom_id` stability across restarts (mitigated: deterministic IDs from agent name + forum ID).
