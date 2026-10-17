---
description: The machine configuration owns WhatsApp's explicit enablement and typed provider values, including any environment references.
---

# WhatsApp Configuration — Spec

## What it is

The WhatsApp adapter consumes the machine configuration's typed `whatsapp`
section.

The explicit `enabled` value is authoritative: supplying credentials does not
enable the adapter. Consumers read the typed configuration and own the checks
their operations require.

Values enter typed configuration through machine YAML, as literals or as YAML
environment references. A `WHATSAPP_*` variable does not override or populate
a typed field merely by being present; the field must reference it in YAML.

## Canonical fields

### Use cases

#### UC-CFG-WA-1

#### UC-CFG-WA-2

#### UC-CFG-WA-3

#### UC-CFG-WA-4

#### UC-CFG-WA-5

#### UC-CFG-WA-6

#### UC-CFG-WA-7

#### UC-CFG-WA-8

### Cross-context references

- Machine configuration owns these declarations and their resolved typed
  values (`local/projects/teleclaude/spec/teleclaude-config`,
  `local/projects/teleclaude/spec/domain/config`).
- Environment-reference syntax and resolution belong to
  `local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`.
- WhatsApp outbound sends and inbound conversations consume this configuration
  under their integration-owned contracts:
  `local/projects/teleclaude/spec/feature/integration/outbound-messaging-providers`
  and
  `local/projects/teleclaude/spec/feature/integration/whatsapp-inbound-conversation-routing`.
