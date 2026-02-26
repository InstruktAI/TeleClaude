# Input: config-wizard-whatsapp-wiring

## Problem

The WhatsApp adapter is fully implemented at the daemon level (`WhatsAppConfig` dataclass in `config/__init__.py:172-182`, adapter code, webhook handling), but the config wizard shows **nothing** when the user navigates to the WhatsApp tab. The component exists as a placeholder with an empty env var list.

This was missed during the `help-desk-whatsapp` delivery. The demo.md documents manual YAML editing and `telec config env set` as the setup path, but the wizard should be the primary configuration interface.

## Current State

### What exists (functional)

- `WhatsAppConfig` dataclass with all fields: `enabled`, `phone_number_id`, `access_token`, `webhook_secret`, `verify_token`, `api_version`, `template_name`, `template_language`
- `WhatsAppConfigComponent` class registered in both TUI views (curses and Textual)
- WhatsApp tab visible in adapter sub-tabs in both views
- `WhatsAppCreds` in person config schema (`phone_number` field)

### What's broken (placeholder/missing)

- `config_handlers.py:83-148` — `_ADAPTER_ENV_VARS` has no `"whatsapp"` entry. All other adapters (telegram, discord, ai, voice, redis) are registered.
- `adapters.py:146-148` — `WhatsAppConfigComponent.__init__` passes `[]` (empty list) instead of `["whatsapp"]`
- `guidance.py:31-62` — `GuidanceRegistry._populate_defaults()` has entries for telegram and discord but **no WhatsApp guidance**
- `config.sample.yml` — has no `whatsapp:` section (telegram, discord, redis all present)
- `project/spec/teleclaude-config` snippet — machine-readable surface doesn't list WhatsApp env vars

### Runtime env vars used by WhatsApp adapter

| Env Var                      | Purpose                                        |
| ---------------------------- | ---------------------------------------------- |
| `WHATSAPP_PHONE_NUMBER_ID`   | Business phone number ID from Meta             |
| `WHATSAPP_ACCESS_TOKEN`      | System user token (long-lived)                 |
| `WHATSAPP_WEBHOOK_SECRET`    | App secret for webhook signature verification  |
| `WHATSAPP_VERIFY_TOKEN`      | Random string for webhook challenge-response   |
| `WHATSAPP_TEMPLATE_NAME`     | Template name for 24h window boundary messages |
| `WHATSAPP_TEMPLATE_LANGUAGE` | Template language code (default: en_US)        |
| `WHATSAPP_BUSINESS_NUMBER`   | Business phone number for invite deep links    |

## Success Criteria

1. Navigating to Config > Adapters > WhatsApp in the TUI shows all WhatsApp env vars with set/not-set status
2. Each env var has descriptive guidance (what it is, how to get it, format example)
3. `config.sample.yml` includes a `whatsapp:` section with all config keys
4. `project/spec/teleclaude-config` snippet lists WhatsApp env vars
5. `telec config validate` checks WhatsApp env var presence when `whatsapp.enabled: true`

## Key Files

- `teleclaude/cli/config_handlers.py` — env var registry
- `teleclaude/cli/tui/config_components/adapters.py` — component wiring
- `teleclaude/cli/tui/config_components/guidance.py` — setup guidance
- `config.sample.yml` — sample config
- `docs/project/spec/teleclaude-config.md` — config spec snippet
