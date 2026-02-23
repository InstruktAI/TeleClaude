# Requirements: adapter-output-delivery

## Goal

Guarantee complete, continuous output delivery from agent sessions to all UI adapters, and ensure user input from any adapter is reflected to all others.

## Scope

### In scope

1. **Text delivery between tool calls** — threaded adapters (Claude/Discord, Gemini/Telegram, Gemini/Discord) receive all assistant text, not just tool-call boundaries.
2. **User input reflection across adapters** — when a user sends input from any adapter (terminal, Telegram, Discord), that input is broadcast to all OTHER UI adapters as a formatted message (`"{SOURCE} @ {computer_name}:\n\n{text}"`). Currently broken for terminal input.

### Out of scope

- Discord infrastructure provisioning (separate todo: `discord-adapter-integrity`).
- Per-computer project categories (separate todo: `discord-adapter-integrity`).
- Discord forum input routing (separate todo: `discord-adapter-integrity`).

## Success Criteria

- [ ] A Claude session on Discord shows text output between tool calls within ~2s of it appearing in the transcript.
- [ ] A Gemini session on Telegram shows the same continuous delivery.
- [ ] User input from the terminal appears in Discord/Telegram threads as "TUI @ {computer_name}:\n\n{text}" within seconds.
- [ ] User input from Telegram appears in Discord threads (and vice versa) with correct source attribution.
- [ ] MCP-origin input is still NOT broadcast (intentional filter).

## Constraints

- Daemon availability policy: restarts must be brief and verified via `make restart` / `make status`.
- No changes to the experiment config format or evaluation logic.
- Existing hook-triggered incremental rendering path must remain untouched.

## Risks

- Poller-triggered incremental rendering adds ~1 transcript parse per second per threaded session. Acceptable given cursor-based reads and digest dedup, but worth monitoring.
