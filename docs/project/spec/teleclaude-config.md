---
description: 'Authoritative surface for TeleClaude config files, daemon runtime config, and related environment variables.'
id: 'project/spec/teleclaude-config'
scope: 'project'
type: 'spec'
visibility: 'public'
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
env_allow_list: list[string] # ambient env vars explicitly allowed into agent tmux sessions for this project
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

`env_allow_list` is an explicit pass-through list for agent sessions. It is the
authorization/filter surface: a name not listed in the effective allow list must
not enter agent tmux sessions, even if it exists in `.env` or in the daemon
environment. At tmux session creation, TeleClaude combines the global allow list
from `~/.teleclaude/teleclaude.yml` with project additions from
`<project>/teleclaude.yml`, reads those names from the daemon process
environment, and exports only the names that are configured and present. The
values are loaded into the pane through the session's private TMPDIR env file,
not through tmux command-line `-e` arguments; that private file is a delivery
mechanism, not an authorization mechanism. The regular project `.env` remains
the source for application/runtime secrets. Those values enter agent sessions
only when their names are also listed in the effective `env_allow_list` and are
present in the daemon environment.

### Global-only keys (`GlobalConfig` adds these)

Valid **only** in `~/.teleclaude/teleclaude.yml`. Rejected by `ProjectConfig`.

```yaml
people: list[PersonEntry] # REJECTED at project level
env_allow_list: list[string] # ambient env vars explicitly allowed into all local agent tmux sessions
subscriptions: list[SubscriptionEntry]
interests: list[string]
event_domains:
  domains: mapping[string, DomainConfig]
```

Global `env_allow_list` is the normal place to authorize env vars needed by
global agent skills or CLI integrations. Project `env_allow_list` is additive
for repository-specific names.

### Per-person keys (`PersonConfig`)

Valid **only** in `~/.teleclaude/people/{name}/teleclaude.yml`.

```yaml
creds:
  telegram: { user_name, user_id, chat_id }
  discord: { user_id, nick }
  whatsapp: { phone_number }
subscriptions: list[SubscriptionEntry]
interests: list[string]
invite_token: string
```

`creds.discord.nick` is optional. When present, it is the Discord-facing display name for
reflected human input; canonical identity, authorization, and personal workspace resolution still
use `people[].name`.

### Environment variables

```yaml
environment_variables:
  # Telegram adapter — wizard-managed via _ADAPTER_ENV_VARS["telegram"]
  - TELEGRAM_BOT_TOKEN
  # Discord adapter — wizard-managed via _ADAPTER_ENV_VARS["discord"]
  - DISCORD_BOT_TOKEN
  - DISCORD_GUILD_ID
  # WhatsApp adapter — wizard-managed via _ADAPTER_ENV_VARS["whatsapp"]
  - WHATSAPP_PHONE_NUMBER_ID
  - WHATSAPP_ACCESS_TOKEN
  - WHATSAPP_WEBHOOK_SECRET
  - WHATSAPP_VERIFY_TOKEN
  - WHATSAPP_TEMPLATE_NAME
  - WHATSAPP_TEMPLATE_LANGUAGE
  - WHATSAPP_BUSINESS_NUMBER
  # AI keys — wizard-managed via _ADAPTER_ENV_VARS["ai"]
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY
  - GOOGLE_API_KEY
  - SUMMARIZER_LOCAL_BASE_URL # OpenAI-compatible local summarizer endpoint (e.g. LM Studio)
  # Voice / TTS — wizard-managed via _ADAPTER_ENV_VARS["voice"]
  - ELEVENLABS_API_KEY
  # Redis transport — wizard-managed via _ADAPTER_ENV_VARS["redis"]
  - REDIS_URL
  - REDIS_PASSWORD
  # Runtime state root + log control
  - TELECLAUDE_HOME # runtime state root override; defaults to ~/.teleclaude
  - TELECLAUDE_LOG_LEVEL
  # Email delivery (SMTP)
  - SMTP_HOST
  - SMTP_PORT
  - SMTP_USER
  - SMTP_PASS
  - EMAIL_FROM
```

`TELECLAUDE_HOME` is consumed by `teleclaude.paths` before path constants are
created. It changes the root for runtime state files such as databases, logs,
global docs, commands, people configs, and session temp directories. Tests set it
before importing TeleClaude so runtime state cannot fall through to the real
`~/.teleclaude` tree.

### Daemon runtime config keys (`config.yml`)

The daemon runtime config lives at `~/.teleclaude/config.yml` (under `TELECLAUDE_HOME`).
The bundled `templates/config.yml` is the read-only blueprint: `make install` seeds the
runtime file from it on first run, and the daemon bootstrap (`teleclaude.config._bootstrap`)
merges any blueprint keys missing from the runtime file (runtime values win, `${VAR}`
placeholders preserved). The TUI, daemon, and installer read and write only the runtime
file; the blueprint is never mutated. `make install` writes opted-in agents' `enabled`
state into the runtime file. `TELECLAUDE_CONFIG_PATH` overrides the path verbatim (tests).

The `agents` config key for the Antigravity agent is `gemini`; its binary resolves to
`agy` via `resolve_agent_binary`. The installer heals any legacy `agy:` key back to
`gemini:` so the parser (which accepts only `claude`/`gemini`/`codex`) does not reject it.

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
  enabled: boolean
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
summarizer:
  local: # OpenAI-compatible local provider (e.g. LM Studio); tried first when enabled
    enabled: boolean
    base_url: string # ${SUMMARIZER_LOCAL_BASE_URL}
    model: string
  provider_priority: list[string] # cloud fallback order: openai|anthropic|google
  openai: { model: string } # dateless alias, e.g. gpt-5-nano
  anthropic: { model: string } # e.g. claude-haiku-4-5
  google: { model: string } # e.g. gemini-2.5-flash; uses Gemini's OpenAI-compatible endpoint
```

Summary/title generation tries `local` (when `enabled` + `base_url`) first, then the
cloud providers in `provider_priority`, each skipped silently when its API key
(`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`) is absent. `local`/`openai`/
`google` share the OpenAI SDK; `anthropic` uses its own. Empty summaries (e.g. all
providers out of credit) suppress agent-stop TTS and leave generic session titles.

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
through `ProjectCatalogService`. `telec projects init` is the sole writer of the
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
