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
    claude: object
    gemini: object
    codex: object
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
```

## Constraints

- Changing a configuration key from optional to required is a breaking change (Minor bump).
- Removing or renaming a configuration key is a breaking change.
- Adding a new optional key or environment variable is a patch.
