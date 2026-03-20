---
id: 'project/spec/teleclaude-config'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for TeleClaude YAML configuration and environment variables.'
---

# Teleclaude Config — Spec

## What it is

The Teleclaude Config surface defines how the daemon and CLI are initialized and validated.

## Two config files, three levels

Configuration lives in two files. `GlobalConfig` extends `ProjectConfig`, so all
project keys are valid at global level — but not the reverse. `ProjectConfig`
explicitly rejects global-only keys (`people`, `ops`, `creds`, `notifications`,
`timezone`). See `teleclaude/config/schema.py` for the Pydantic models.

| File                  | Location                                     | Model           | Owns                                                                                                    |
| --------------------- | -------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------- |
| **Global config**     | `~/.teleclaude/teleclaude.yml`               | `GlobalConfig`  | All project keys + `people`, `subscriptions`, `interests`, `event_domains`                              |
| **Project config**    | `<project-root>/teleclaude.yml`              | `ProjectConfig` | `project_name`, `business`, `jobs`, `hooks`, `git`, `integrator`, `deployment`, `channel_subscriptions` |
| **Per-person config** | `~/.teleclaude/people/{name}/teleclaude.yml` | `PersonConfig`  | `creds`, `subscriptions`, `interests`, `invite_token`                                                   |

**The project config is a regular file committed to the repository.** It is never a
symlink. Replacing it with a symlink to the global config breaks validation because
`ProjectConfig.reject_disallowed_keys` rejects `people`.

## Canonical fields

### Project config keys (`ProjectConfig`)

Valid in both project and global configs.

```yaml
project_name: string
description: string
business:
  domains: mapping[string, string] # domain-name → "docs" (enables doc scope filtering)
jobs: mapping[string, JobScheduleConfig]
hooks:
  inbound: mapping[string, InboundSourceConfig]
  subscriptions: list[SubscriptionConfig]
git:
  checkout_root: string
integrator:
  cutover:
    enabled: boolean
    parity_evidence_accepted: boolean
    rollback_on_incomplete_parity: boolean
deployment:
  channel: string # alpha | beta | stable (default: alpha)
  pinned_minor: string # required when channel=stable
channel_subscriptions: list[ChannelSubscription]
```

### Global-only keys (`GlobalConfig` adds these)

Valid **only** in `~/.teleclaude/teleclaude.yml`. Rejected by `ProjectConfig`.

```yaml
people: list[PersonEntry] # REJECTED at project level
subscriptions: list[SubscriptionEntry]
interests: list[string]
event_domains:
  domains: mapping[string, DomainConfig]
```

### Per-person keys (`PersonConfig`)

Valid **only** in `~/.teleclaude/people/{name}/teleclaude.yml`.

```yaml
creds:
  telegram: { user_name, user_id, chat_id }
  discord: { user_id }
  whatsapp: { phone_number }
subscriptions: list[SubscriptionEntry]
interests: list[string]
invite_token: string
```

### Environment variables

```yaml
environment_variables:
  - TELEGRAM_BOT_TOKEN
  - WHATSAPP_PHONE_NUMBER_ID
  - WHATSAPP_ACCESS_TOKEN
  - WHATSAPP_WEBHOOK_SECRET
  - WHATSAPP_VERIFY_TOKEN
  - WHATSAPP_TEMPLATE_NAME
  - WHATSAPP_TEMPLATE_LANGUAGE
  - WHATSAPP_BUSINESS_NUMBER
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY
  - GOOGLE_API_KEY
  - TELECLAUDE_LOG_LEVEL
  - REDIS_URL
  - SMTP_HOST
  - SMTP_PORT
  - SMTP_USER
  - SMTP_PASS
  - EMAIL_FROM
```

### Maintenance

This spec must be updated whenever config keys or env vars are added, renamed, or removed. The config wizard, `_ADAPTER_ENV_VARS` registry, and `GuidanceRegistry` must stay in sync with this spec.

## Known caveats

- `config.yml:agents` is required; startup fails if it is missing.
- `config.yml:agents` must only contain known agent keys (`claude`, `gemini`, `codex`).
- At least one configured agent must have `enabled: true`; all-disabled configs fail startup.
- Validation errors must reference concrete `config.yml` paths to fix (for example `config.yml:agents.codex.enabled`).
- Changing a configuration key from optional to required is a breaking change (Minor bump).
- Removing or renaming a configuration key is a breaking change.
- Adding a new optional key or environment variable is a patch.
- **The project `teleclaude.yml` must be a regular file, never a symlink.** `ProjectConfig` validation rejects global-only keys like `people` and `agents`. Symlinking to the global config causes runtime errors.
