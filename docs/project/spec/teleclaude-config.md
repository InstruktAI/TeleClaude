---
id: 'project/spec/teleclaude-config'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for TeleClaude YAML configuration and environment variables.'
---

# Teleclaude Config — Spec

## Definition

The Teleclaude Config surface defines how the daemon and CLI are initialized and validated.

## Machine-Readable Surface

```yaml
config_keys:
  computer:
    name: string
    role: string
    timezone: string
  agents:
    claude:
      enabled: boolean
      strengths: string
      avoid: string
    gemini:
      enabled: boolean
      strengths: string
      avoid: string
    codex:
      enabled: boolean
      strengths: string
      avoid: string
  redis:
    enabled: boolean
    host: string
    port: int
  people: list[PersonEntry]
  jobs: mapping[string, JobScheduleConfig]

environment_variables:
  - TELEGRAM_BOT_TOKEN
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

## Constraints

- `config.yml:agents` is required; startup fails if it is missing.
- `config.yml:agents` must only contain known agent keys (`claude`, `gemini`, `codex`).
- At least one configured agent must have `enabled: true`; all-disabled configs fail startup.
- Validation errors must reference concrete `config.yml` paths to fix (for example `config.yml:agents.codex.enabled`).
- Changing a configuration key from optional to required is a breaking change (Minor bump).
- Removing or renaming a configuration key is a breaking change.
- Adding a new optional key or environment variable is a patch.
