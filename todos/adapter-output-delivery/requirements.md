# Requirements: adapter-output-delivery

## Goal

Make session routing predictable and observable:

- Keep direct reply continuity at the origin UX.
- Keep operational visibility for admins.
- Reflect user/actor input clearly across observer adapters.

## Scope

### In scope

1. **Text delivery between tool calls** - threaded adapters (Claude/Discord, Gemini/Telegram, Gemini/Discord) receive all assistant text, not only tool-call boundaries.
2. **Origin UX-only notices** - feedback notices and user-facing errors stay on the origin endpoint and do not fan out to non-origin admin destinations.
3. **Origin UX-only summary path** - `last_output_summary` is origin UX only, rendered through non-threaded/in-edit paths (for example TUI session field and Telegram edit-message placement), not threaded admin output.
4. **Input reflection fan-out** - text, voice, and MCP input are reflected to every other provisioned UI adapter except the source adapter.
5. **Actor-attributed reflections** - reflected input includes best-effort actor identity (`actor_name`, optional avatar), so admins can see who sent the input without relying on adapter name alone.
6. **Discord reflection rendering** - Discord uses webhook-based reflection presentation when available (actor name/avatar), with fallback to standard bot posting when webhook delivery is unavailable.

### Out of scope

- Discord infrastructure provisioning (separate todo: `discord-adapter-integrity`).
- Per-computer project categories (separate todo: `discord-adapter-integrity`).
- Discord forum input routing (separate todo: `discord-adapter-integrity`).

## Success Criteria

- [ ] A Claude session on Discord shows text output between tool calls within ~2s of it appearing in the transcript.
- [ ] A Gemini session on Telegram shows the same continuous delivery.
- [ ] Feedback notices and user-facing errors stay origin-only and never fan out to non-origin admin destinations.
- [ ] `last_output_summary` is delivered through the origin UX in-edit path only, not threaded admin output.
- [ ] User input from terminal/Telegram/Discord is reflected to all other provisioned adapters (source excluded) with actor attribution.
- [ ] Voice input follows the same reflection contract as text input.
- [ ] MCP input follows the same reflection contract as text/voice input, with actor attribution.
- [ ] On Discord, actor-attributed reflections render via webhook when possible and safely fall back to normal send when not.

## Constraints

- Daemon availability policy: restarts must be brief and verified via `make restart` / `make status`.
- No changes to the experiment config format or evaluation logic.
- Existing hook-triggered incremental rendering path must remain untouched.

## Risks

- Poller-triggered incremental rendering adds ~1 transcript parse per second per threaded session. Acceptable given cursor-based reads and digest dedup, but worth monitoring.
