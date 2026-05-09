---
id: 'project/spec/teleclaude-config'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for TeleClaude config files, daemon runtime config, and related environment variables.'
---

# Teleclaude Config — Spec

## What it is

The Teleclaude Config surface defines how TeleClaude configuration is initialized and validated across two distinct surfaces:

1. User-facing `teleclaude.yml` files (`GlobalConfig`, `ProjectConfig`, `PersonConfig`)
2. Daemon runtime `config.yml` loaded by `teleclaude.config`

These surfaces are related but not interchangeable. The config wizard, `_ADAPTER_ENV_VARS`, and `GuidanceRegistry` cover the user-facing `teleclaude.yml` / environment-variable surface. Daemon-only `config.yml` keys are documented here for runtime correctness, but they do not automatically imply new wizard steps or env-var registry entries.

### Two config files, three levels

Configuration lives in two files. `GlobalConfig` and `ProjectConfig` are
separate Pydantic models: global config owns the machine-wide keys, while the
project config owns repository-local metadata and explicitly rejects
global-only keys (`people`, `ops`, `creds`, `notifications`, `timezone`). See
`teleclaude/config/schema.py` for the authoritative model definitions.

| File                  | Location                                     | Model           | Owns                                                                                                                                                              |
| --------------------- | -------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Global config**     | `~/.teleclaude/teleclaude.yml`               | `GlobalConfig`  | All project keys + `people`, `subscriptions`, `interests`, `event_domains`                                                                                        |
| **Project config**    | `<project-root>/teleclaude.yml`              | `ProjectConfig` | `project_slug`, `project_name`, `language`, `languages`, `frontend_root`, `business`, `jobs`, `hooks`, `git`, `integrator`, `deployment`, `channel_subscriptions` |
| **Per-person config** | `~/.teleclaude/people/{name}/teleclaude.yml` | `PersonConfig`  | `creds`, `subscriptions`, `interests`, `invite_token`                                                                                                             |

**The project config is a regular file committed to the repository.** It is never a
symlink. Replacing it with a symlink to the global config breaks validation because
`ProjectConfig.reject_disallowed_keys` rejects `people`.

## Canonical fields

### Project config keys (`ProjectConfig`)

Valid in both project and global configs.

```yaml
project_slug: string # canonical machine identity; required in project configs
project_name: string # human-readable display name
language: string # deprecated; use languages list
languages: list[string] # project languages for quality tooling and init skeletons (e.g. [python, typescript])
frontend_root: string # directory containing TypeScript/frontend project, relative to project root (e.g. frontend)
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

### Daemon runtime config keys (`config.yml`)

These keys are loaded by the daemon runtime config parser in `teleclaude/config/__init__.py`.

```yaml
computer:
  name: string
  user: string
  role: string
  default_working_dir: string
  timezone: string
  host: string | null
  bot_username: string | null
  trusted_dirs: list[TrustedDir]
remote_computers:
  <name>:
    user: string | null
    host: string | null
    ip: string | null
    teleclaude_path: string | null
    bot_username: string | null
telegram:
  trusted_bots: list[string] # explicit entries merged with non-null fleet bot_username values
agents:
  default: string
  claude|gemini|codex:
    enabled: boolean
event_reliability:
  idle_threshold_ms: integer # minimum idle time before stale pending entries can be reclaimed
  max_attempts: integer # cumulative retry ceiling before dead-letter transition
  sweep_interval_ms: integer # periodic stale-pending sweep cadence
  dlq_destination: string # dead-letter destination identity
```

### Maintenance

This spec must be updated whenever a documented config key or env var is added, renamed, or removed.

The config wizard, `_ADAPTER_ENV_VARS` registry, and `GuidanceRegistry` must stay in sync with the user-facing `teleclaude.yml` / environment-variable surfaces documented here.

Daemon-only structural keys in `config.yml` must also be documented here, but they only require wizard or env-var changes when those keys become part of the interactive `teleclaude.yml` setup flow.

### Project registry

Registered project roots live in `~/.teleclaude/projects.yaml`, a root-only
registry — it stores only absolute project paths:

```yaml
projects:
  - /abs/path/to/project-a
  - /abs/path/to/project-b
```

All per-project metadata (`project_slug`, `project_name`, `jobs`, docs index
location, etc.) lives in each project's own `teleclaude.yml` and is loaded
through `ProjectCatalogService`. `telec init` is the sole writer of the
registry; `telec sync` no longer registers projects. `project_slug` is the
canonical machine identity used for the log namespace
(`instrukt-ai-logs {project_slug}`), the cross-project docs namespace, and
service-level project lookup. `project_name` remains display-only.

## Known caveats

- `config.yml:agents` is required; startup fails if it is missing.
- `config.yml:agents` must only contain known agent keys (`claude`, `gemini`, `codex`).
- At least one configured agent must have `enabled: true`; all-disabled configs fail startup.
- Validation errors must reference concrete `config.yml` paths to fix (for example `config.yml:agents.codex.enabled`).
- Changing a configuration key from optional to required is a breaking change (Minor bump).
- Removing or renaming a configuration key is a breaking change.
- Adding a new optional key or environment variable is a patch.
- **The project `teleclaude.yml` must be a regular file, never a symlink.** `ProjectConfig` validation rejects global-only keys like `people` and `agents`. Symlinking to the global config causes runtime errors.
