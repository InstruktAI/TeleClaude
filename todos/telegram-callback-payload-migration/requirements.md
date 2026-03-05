# Requirements: telegram-callback-payload-migration

## Goal

Migrate Telegram callback payloads from hardcoded per-agent abbreviations to a generic,
`AgentName`-derived pattern. Make the heartbeat keyboard data-driven so new agents are
automatically included without code changes.

## Scope

### In scope

- Replace per-agent `CallbackAction` enum values (`csel`, `gsel`, `cxsel`, `c`, `g`, `cx`,
  and resume variants) with generic action types parameterized by agent name.
- Replace hardcoded `event_map` and `mode_map` dicts in `_handle_agent_start` and
  `_handle_agent_select` with `AgentName`-derived lookups.
- Build heartbeat keyboard dynamically from enabled agents (`get_enabled_agents()`).
- Parse legacy callback payloads (old format) so existing buttons in Telegram chats
  remain functional during deprecation.
- Add tests for both legacy and new payload formats.

### Out of scope

- Default agent resolution behavior (delivered in `default-agent-resolution`).
- Changes to `CommandMapper`, `command_registry`, or session creation internals.
- Non-Telegram adapters (Discord, WhatsApp, web, TUI).
- Changes to `auto_command` format beyond what's needed for canonical agent names.

## Success Criteria

- [ ] `CallbackAction` enum uses generic action types (`AGENT_SELECT`, `AGENT_RESUME_SELECT`,
      `AGENT_START`, `AGENT_RESUME_START`) instead of per-agent values.
- [ ] Heartbeat keyboard is built dynamically from `get_enabled_agents()` with consistent
      button layout per agent (New + Resume row).
- [ ] Old callback payloads (`csel:bot`, `gsel:bot`, `cxsel:bot`, `c:0`, `g:0`, `cx:0`,
      `crsel:bot`, `grsel:bot`, `cxrsel:bot`, `cr:0`, `gr:0`, `cxr:0`) are parsed correctly
      and routed to the same handlers as the new format.
- [ ] New canonical payload format: `asel:{agent}:{arg}`, `arsel:{agent}:{arg}`,
      `as:{agent}:{arg}`, `ars:{agent}:{arg}` — stays under Telegram's 64-byte limit.
- [ ] `event_map` and `mode_map` are eliminated in favor of `AgentName`-derived values.
- [ ] Tests cover: new format parsing, legacy format parsing, dynamic keyboard generation,
      agent start with new payloads, unknown agent in payload (rejected gracefully).
- [ ] No regression in existing heartbeat menu, project selection, or session creation flow.

## Constraints

- Telegram `callback_data` is limited to 64 bytes. New format must stay within this limit.
- Legacy buttons already exist in user chats. They cannot be recalled — the system must
  parse them for a reasonable deprecation period.
- `AgentName` enum is the canonical source of truth for agent identifiers.
- `get_enabled_agents()` determines which agents appear in the keyboard.

## Risks

- Existing Telegram messages with old-format buttons may break if legacy parsing is missed.
  Mitigated by explicit legacy-to-canonical mapping with tests.
- Dynamic keyboard may show/hide agents based on config, which changes UX if agents are
  toggled. This is acceptable and desired behavior.
