---
description: The machine configuration owns WhatsApp's explicit enablement and typed provider values, including any environment references.
---

# WhatsApp Configuration — Spec

## What it is

The machine configuration's `whatsapp` section owns the adapter's explicit
`enabled` flag and its typed values: `phone_number_id`, `access_token`,
`webhook_secret`, `verify_token`, `business_number`, `template_name`, and
`template_language`. `api_version` is internal and fixed by the platform.

`enabled` is authoritative and defaults to `false`. Credentials do not enable
the adapter implicitly; credentials without `enabled: true` leave it disabled.
Consumers read these values from the typed configuration and own the checks
their operations require (`local/projects/teleclaude/spec/feature/integration/outbound-messaging-providers`,
`local/projects/teleclaude/spec/feature/integration/whatsapp-inbound-conversation-routing`).

Values are declared in machine YAML, as literals or as YAML environment
references. The config owner resolves those references under the machine
configuration rules in `local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`.
A `WHATSAPP_*` variable does not override or populate a typed field merely by
being present; the field must reference it in YAML. This spec leaves reference
syntax, environment ownership, resolution, and persistence to the shared
configuration contract.

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

## Allowed values

- `whatsapp.enabled`: boolean, default `false`; this field alone determines whether the adapter is enabled.
- `phone_number_id`, `access_token`, `webhook_secret`, `verify_token`, `business_number`, and `template_name`: nullable strings.
- `template_language`: string, default `"en_US"`; omitted or empty values in YAML resolve to that default.
- `api_version`: internal and fixed to `WHATSAPP_API_VERSION`; it is not configurable through YAML or an environment reference.
- A typed field may hold a literal or an environment reference resolved by the config owner. Environment-reference behavior is defined by `local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`.
