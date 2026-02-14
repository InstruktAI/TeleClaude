# Interactive Configuration System

## Context

TeleClaude configuration spans multiple files and concerns:

- **Global config** (`~/.teleclaude/teleclaude.yml`) — adapters, people registry, ops
- **Per-person config** (`~/.teleclaude/people/{name}/teleclaude.yml`) — credentials, notification subscriptions, interests
- **Environment variables** — API tokens for each platform adapter
- **Project configs** — per-project teleclaude.yml in repositories

The `telec config get/patch/validate` CLI already exists for scripting. But there's no
interactive experience for humans who want to browse what's configurable, see current
state, and make changes without memorizing YAML paths.

With the help desk platform adding Discord, WhatsApp, multi-platform credentials, and
notification subscriptions, the configuration surface is growing. Every new adapter adds
config fields, env vars, and per-person credential types. Without a guided interactive
experience, operators must read scattered docs and hand-edit YAML.

## The Feature

Two modes, one config layer:

1. **`telec config`** (no args) — interactive menu. Browse and edit all configuration.
   Permanent, everyday tool for ongoing changes.

2. **`telec onboard`** — guided first-run wizard. Walks through the same config areas
   in order with explanatory text and documentation links. Entry point for new operators.

Both use the same config handlers, write to the same files, apply the same schema
validation. No divergent paths.

### Interactive Menu (`telec config`)

```
TeleClaude Configuration

  ► Adapters
    ► Telegram         ✓ configured
    ► Discord          ✗ not configured
    ► WhatsApp         ✗ not configured
  ► People             (1 configured)
    ► Morriz           admin  ✓ telegram
    ► [Add person...]
  ► Notifications
    ► Channels         (4 defined)
    ► Subscriptions    (1 person subscribed)
  ► Environment
    ► Status check     2 missing vars
  ► [Validate all]
```

Drill into any section, see current values, edit them. Schema validation on every write.
Status indicators show what's configured and what's missing.

### Guided Onboarding (`telec onboard`)

Same config operations, walked through in order:

1. Platform selection (which adapters to enable)
2. Adapter configuration (tokens, IDs, webhook setup)
3. People management (add people, set roles, add credentials)
4. Notification subscriptions (channels per person, preferred platform)
5. Environment variable check (what's set, what's missing)
6. Full validation

Each step includes help text and links to relevant documentation (delivered by the
adapter todos).

### Schema-Driven

The menu is driven by the config schema in `teleclaude/config/schema.py`. When an
adapter todo adds `DiscordAdapterConfig`, it appears in the menu automatically. No
separate menu registration needed. This means:

- `telec-config-interactive` can ship with whatever config areas exist today
- As adapter todos land and add schema models, the menu grows
- The dependency is soft, not hard — can be built in parallel

## Design Decisions

1. **One config layer, multiple interfaces** — interactive menu, guided wizard, and
   existing `get/patch/validate` all use the same read/write/validate operations.
2. **Schema-driven menu** — config areas derive from the schema, not hardcoded menu entries.
3. **Incremental delivery** — ships with existing config areas (people, Telegram).
   New config areas appear as their schema models are added by other todos.
4. **Idempotent** — both modes detect existing config and show current state.
5. **Atomic writes** — no partial config left on interruption (Ctrl+C safe).

## Relationship to Other Work

- **telec-config-cli** (DELIVERED) — `get/patch/validate` scripting API. This todo extends it.
- **role-based-notifications** — adds `NotificationsConfig` expansion, `DiscordCreds`, `WhatsAppCreds`.
- **help-desk-whatsapp** — adds `WhatsAppAdapterConfig`. Delivers WhatsApp setup docs.
- **help-desk-discord** — adds `DiscordAdapterConfig`. Delivers Discord setup docs.
- All adapter todos deliver documentation that the wizard references at each step.
