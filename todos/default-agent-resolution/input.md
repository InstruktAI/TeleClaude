# Input: default-agent-resolution

## Problem

Three interrelated failures discovered during Discord → agent launch trace:

### 1. Agent resolution is scattered and inconsistent (DRY violation)

15 call sites resolve "which agent to use when none specified" using 4 different strategies:
- **Hardcoded `"agent claude"`** — telegram_adapter (2), whatsapp_handler (1), discord help_desk (1), discord DMs (2)
- **`enabled_agents[0]`** — discord `_default_agent`, command_mapper, api_server
- **`AgentName.CLAUDE` enum default** — checkpoint_dispatch, agent_coordinator
- **User selection** — TUI modal, launcher button (these are fine)

This violates DRY (same business rule in 6+ places), fail-fast (silent wrong agent instead of error), and adapter boundaries (adapters hardcode core domain knowledge).

### 2. Discord launcher buttons missing from channels

- `_post_or_update_launcher` only posts to project forums (`self._project_forum_map.values()`), excluding help_desk and all_sessions forums
- Launcher threads are not pinned to the forum — `_pin_launcher_message` pins the message inside the thread, not the thread in the forum. Discord forums support `await thread.edit(pinned=True)` to stick threads to the top. Without this, launcher threads sink to the bottom and become invisible.

### 3. Tmux starts but agent doesn't launch (investigation trail)

Bootstrap is a background task (`_bootstrap_session_resources`). Multiple silent failure points exist where exceptions are caught and swallowed, allowing the session to transition to `"active"` with a bare shell. The agent resolution refactor touches the same code paths and will improve observability.

## User requirements

- No hardcoded agent names anywhere outside enum definition and config schema
- No `enabled_agents[0]` index-based selection
- No fallbacks — fail fast with errors
- Single resolver function in core, all call sites funnel through it
- `default_agent` declared explicitly in config.yml — not derived from dict ordering
- Launcher threads pinned (sticky) to the top of their forum
- Launchers posted to ALL managed forums (help_desk, all_sessions, project forums)

## Call site inventory

| Location | File | Lines | Current behavior |
|---|---|---|---|
| Discord `_default_agent` | discord_adapter.py | 165-170 | `enabled_agents[0]`, fallback `"claude"` |
| Discord help_desk | discord_adapter.py | 2459 | Hardcoded `"agent claude"` |
| Discord DM (existing) | discord_adapter.py | 1857 | Hardcoded `"agent claude"` |
| Discord DM (invite) | discord_adapter.py | 1932 | Hardcoded `"agent claude"` |
| Telegram private chat | telegram_adapter.py | 434 | Hardcoded `"agent claude"` |
| Telegram reconnect | telegram_adapter.py | 503 | Hardcoded `"agent claude"` |
| WhatsApp handler | whatsapp_handler.py | 46 | Hardcoded `"agent claude"` |
| Command mapper | command_mapper.py | 41-45 | `enabled_agents[0]` |
| API server | api_server.py | 560-566 | `enabled_agents[0]` |
| Checkpoint dispatch | checkpoint_dispatch.py | 36 | `AgentName.CLAUDE` enum default |
| Agent coordinator | agent_coordinator.py | 1612 | `AgentName.CLAUDE` |
| Discord launcher loop | discord_adapter.py | 1789 | Only project forums |
| Launcher pin | discord_adapter.py | 701-716 | Pins message, not thread |
