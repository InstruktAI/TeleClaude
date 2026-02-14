# Requirements: Interactive Configuration System

## Architecture Reference

See `docs/project/design/architecture/help-desk-platform.md` for the platform-wide
configuration surface across adapters, people, and notifications.

## Goal

Deliver an interactive configuration system with two modes: a browsable menu
(`telec config` with no args) for everyday use and a guided onboarding wizard
(`telec onboard`) for first-run setup. Both backed by the same config layer.

## Problem Statement

TeleClaude configuration spans global YAML, per-person YAML, and environment variables
across a growing number of platforms. The existing `telec config get/patch/validate`
serves scripting but offers no interactive experience. Operators must know YAML paths,
file locations, and env var names by heart. As the platform grows (Discord, WhatsApp,
notifications), this becomes untenable.

## Scope

### In scope

1. **Interactive config menu** — `telec config` (no args) opens browsable TUI menu.
2. **Guided onboarding wizard** — `telec onboard` walks through all config in order.
3. **Config area handlers** — per-area logic: read current state, prompt for values, write, validate.
4. **Schema-driven discovery** — menu entries derived from config schema models.
5. **Status indicators** — show configured/missing/invalid state per area.
6. **Environment variable management** — list required vars, check presence, show example values.
7. **People management** — add/edit/list people with roles and per-platform credentials.
8. **Notification subscription management** — configure channels and preferred platform per person.
9. **Validation** — schema validation on every write, full-system validation check.
10. **Documentation integration** — help option at each step linking to relevant docs.

### Out of scope

- Web-based configuration UI.
- Automatic API token provisioning (users create bots/apps themselves).
- Platform account creation (Discord bot, WhatsApp Business API signup).
- Config sync across multiple computers (existing rsync/deploy handles this).

## Functional Requirements

### FR1: Interactive menu entry point

- `telec config` with no arguments launches the interactive menu.
- Menu shows a tree of all config areas with status indicators.
- User navigates with number selection (stdin/stdout prompts).
- Each area shows current values and allows editing.
- `q` or Escape exits.

### FR2: Guided onboarding entry point

- `telec onboard` launches the guided wizard.
- `make onboard` as alias.
- Detects current state, starts from first incomplete section.
- Walks through config areas in a logical order with explanatory text.
- Each step includes a help option that shows relevant documentation.
- Can be re-run; skips completed sections (with option to revisit).

### FR3: Adapter configuration

For each adapter platform (Telegram, Discord, WhatsApp):

- Show configuration status (configured / not configured / misconfigured).
- Prompt for all required config values.
- Write to global `teleclaude.yml` under `adapters:` section.
- List required environment variables, check if set, show examples for missing ones.
- Only show adapter if its schema model exists (schema-driven).

### FR4: People management

- List all configured people with role and credential summary.
- Add new person: name, email, role selection.
- Edit existing person: change role, add/remove platform credentials.
- Per-platform credential prompts: only ask for platforms that are enabled.
- Write per-person config to `~/.teleclaude/people/{name}/teleclaude.yml`.
- Add person to global `people:` list in `~/.teleclaude/teleclaude.yml`.
- Schema validation on every write.

### FR5: Notification subscription management

- For each configured person, show current channel subscriptions.
- Add/remove channel subscriptions.
- Set preferred notification platform.
- Show available channels with descriptions.
- Write to per-person config `notifications:` section.

### FR6: Environment variable management

- Aggregate all required env vars across all configured adapters.
- Check which are set in the current environment.
- Show example `.env` entries for missing vars.
- Optionally test connectivity (Discord bot login, WhatsApp API health) where possible.

### FR7: Validation

- `[Validate all]` menu option runs full-system check.
- Schema validation of all config files.
- Cross-reference checks: people referenced in notifications exist, adapter credentials match.
- Environment variable presence check.
- Report pass/fail per component with actionable fix suggestions.

### FR8: Schema-driven menu

- Config areas derived from schema models in `teleclaude/config/schema.py`.
- When `DiscordAdapterConfig` exists in schema, Discord appears in adapter menu.
- When `WhatsAppAdapterConfig` exists, WhatsApp appears.
- No hardcoded menu entries for future platforms.
- Existing config areas (people, Telegram) work from day one.

### FR9: Shared config layer

- Interactive menu and guided wizard use the same config handlers.
- Config handlers use `telec config` get/patch/validate operations internally.
- All writes go through schema validation.
- Atomic writes: interrupted operations don't leave partial config.

## Non-functional Requirements

1. Works in standard terminal (no GUI dependencies). Use `rich` or `questionary`-style prompts.
2. Ctrl+C safe — no partial config written on interruption.
3. Config writes must not clobber existing values not being edited.
4. Response time: menu navigation and reads must be instant; writes may validate.

## Acceptance Criteria

1. `telec config` (no args) opens interactive menu with all config areas.
2. `telec onboard` walks through setup in guided order.
3. Adapter config written correctly to global teleclaude.yml.
4. People added/edited correctly in both global and per-person config.
5. Notification subscriptions written correctly to per-person config.
6. Missing environment variables clearly reported with examples.
7. Schema validation catches invalid values at write time.
8. Full validation check identifies misconfiguration across all areas.
9. Re-running onboard detects existing config and skips completed sections.
10. New config areas appear in menu automatically when schema models are added.
11. Existing `telec config get/patch/validate` continues to work unchanged.

## Cross-References

- **telec-config-cli** (DELIVERED) — scripting API this extends.
- **role-based-notifications** — config schema for notifications and multi-platform creds.
- **help-desk-whatsapp** — WhatsApp adapter config model and setup documentation.
- **help-desk-discord** — Discord adapter config model and setup documentation.
- **Architecture**: `docs/project/design/architecture/help-desk-platform.md`.

## Dependencies

- **telec-config-cli** — get/patch/validate infrastructure (DELIVERED).
- **config-schema-validation** — Pydantic schema (DELIVERED).
- Soft dependency on adapter todos for their schema models. Menu works with whatever exists.
