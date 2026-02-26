# Requirements: config-wizard-whatsapp-wiring

## Goal

Wire WhatsApp environment variables, setup guidance, and sample configuration into the config wizard so the WhatsApp tab is functional — matching the pattern already established by Telegram, Discord, AI Keys, and Redis adapters.

## Context

The WhatsApp adapter is fully implemented at the daemon level (`WhatsAppConfig` dataclass, adapter code, webhook handling). The config wizard already has a WhatsApp tab registered in both TUI views (curses and Textual), but the tab renders empty because the env var registry, guidance entries, and sample config are all missing.

## In Scope

1. **Env var registry** — Add a `"whatsapp"` entry to `_ADAPTER_ENV_VARS` in `config_handlers.py` with all WhatsApp env vars.
2. **Component wiring** — Change `WhatsAppConfigComponent.__init__` to pass `["whatsapp"]` instead of `[]`.
3. **Setup guidance** — Add WhatsApp field guidance entries to `GuidanceRegistry._populate_defaults()` in `guidance.py`.
4. **Sample config** — Add a `whatsapp:` section to `config.sample.yml`.
5. **Config spec** — Add WhatsApp env vars to the `environment_variables` list in `docs/project/spec/teleclaude-config.md`.

## Out of Scope

- Conditional validation (only check WhatsApp env vars when `whatsapp.enabled: true`). The current `validate_all()` unconditionally checks all registered env vars. Changing this would be an architectural change affecting all adapters — defer to `config-wizard-governance` or a separate todo.
- WhatsApp adapter logic changes. The adapter already works.
- Config wizard visual redesign. That's `config-wizard-redesign`.
- New test infrastructure. The changes are wiring/registration only — follow existing patterns.

## Success Criteria

- [ ] Navigating to Config > Adapters > WhatsApp in the TUI (both curses and Textual views) shows all 7 WhatsApp env vars with set/not-set status
- [ ] Each env var has a description and format example visible in the guidance panel
- [ ] `config.sample.yml` includes a `whatsapp:` section with all config keys and env var interpolation
- [ ] `project/spec/teleclaude-config` snippet lists WhatsApp env vars under `environment_variables`
- [ ] `telec config validate` reports missing WhatsApp env vars (same behavior as other adapters)
- [ ] No regressions in other adapter tabs

## Constraints

- Follow the exact patterns used by existing adapters (Telegram, Discord, Redis) — no novel abstractions.
- All env var names must match those already consumed by the WhatsApp adapter (`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, etc.).
- The `config.sample.yml` WhatsApp section must use `${VAR}` interpolation for secrets, matching the Discord/Redis pattern.

## Risks

- Low risk. All changes are additive registration/wiring following established patterns. No behavioral changes to existing code.
