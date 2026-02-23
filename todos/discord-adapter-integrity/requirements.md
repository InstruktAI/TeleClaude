# Requirements: discord-adapter-integrity

## Goal

Guarantee complete, reliable output delivery from agent sessions to Discord (and Gemini/Telegram threaded mode). Harden Discord infrastructure provisioning against stale state. Introduce per-computer project categories so multi-computer setups have clean separation in Discord.

## Scope

### In scope

1. **Text delivery between tool calls** — threaded adapters (Claude/Discord, Gemini/Telegram, Gemini/Discord) receive all assistant text, not just tool-call boundaries.
2. **Infrastructure validation** — `_ensure_discord_infrastructure` validates that stored channel/forum IDs resolve to live Discord channels before trusting them. Stale IDs are cleared and re-provisioned.
3. **Per-computer project categories** — each computer provisions its own "Projects - {computer_name}" category in Discord. Each computer's trusted_dirs forums live under its own category. Sessions from different computers are visually separated.
4. **User input reflection across adapters** — when a user sends input from any adapter (terminal, Telegram, Discord), that input is broadcast to all OTHER UI adapters as a formatted message (`"{SOURCE} @ {computer_name}:\n\n{text}"`). Currently broken for terminal input: non-headless sessions skip the broadcast entirely, and headless sessions are blocked by the `_NON_INTERACTIVE` filter.

### Out of scope

- Agent status sync to Discord threads (separate todo).
- Telegram-specific UI polish.
- Discord message editing/pagination improvements.

## Success Criteria

- [ ] A Claude session on Discord shows text output between tool calls within ~2s of it appearing in the transcript, not only at tool_use/tool_done/agent_stop.
- [ ] A Gemini session on Telegram shows the same continuous delivery.
- [ ] Deleting a Discord forum and restarting the daemon causes automatic re-provisioning (no silent 404s).
- [ ] Two computers (e.g. MozBook and mozmini) each have their own "Projects - MozBook" and "Projects - mozmini" categories with their respective project forums.
- [ ] Sessions route to the correct computer-specific project forum.
- [ ] User input from the terminal appears in Discord/Telegram threads as "TUI @ {computer_name}:\n\n{text}" within seconds.
- [ ] User input from Telegram appears in Discord threads (and vice versa) with correct source attribution.

## Constraints

- Daemon availability policy: restarts must be brief and verified via `make restart` / `make status`.
- No changes to the experiment config format or evaluation logic.
- Existing hook-triggered incremental rendering path must remain untouched.

## Risks

- Per-computer categories change the Discord guild layout. Existing forum threads under the old single "Projects" category will need manual migration or will remain orphaned under the old category.
- Poller-triggered incremental rendering adds ~1 transcript parse per second per threaded session. Acceptable given cursor-based reads and digest dedup, but worth monitoring.
