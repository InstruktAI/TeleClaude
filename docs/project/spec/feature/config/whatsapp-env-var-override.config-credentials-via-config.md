---
id: teleclaude/spec/feature/config/whatsapp-env-var-override
type: spec
domain: project
scope: project
description: WhatsApp credentials and service identifiers resolve through the generic machine-config placeholder boundary, with the explicit enabled flag remaining authoritative.
---

# WhatsApp Config Credential Resolution — Spec

## What it is

The WhatsApp adapter receives credentials and externally supplied service
identifiers only through the typed machine-config aggregate. Operators keep
secret values out of `config.yml` by authoring `${WHATSAPP_*}` placeholders;
the generic YAML expansion pass resolves those placeholders before the typed
`WhatsAppConfig` is built.

WhatsApp has no second per-field environment override. A plain YAML value stays
authoritative, and mutating the process environment after config load cannot
bypass the effective config. The explicit `whatsapp.enabled` value alone
controls whether the adapter is enabled; credential presence never enables it
implicitly. Availability validation separately rejects an enabled adapter whose
required credential fields are absent.

## Canonical fields

### Use cases

#### UC-CFG-WA-1: Placeholder-backed credentials reach the typed aggregate

```gherkin
Given config.yml declares whatsapp.phone_number_id as "${WHATSAPP_PHONE_NUMBER_ID}"
And config.yml declares whatsapp.access_token as "${WHATSAPP_ACCESS_TOKEN}"
And both referenced variables exist in the runtime secret environment
When the machine-config loader runs
Then the generic YAML expansion pass resolves both placeholders
And the typed WhatsApp config contains both resolved values
And the WhatsApp consumer reads both values from that typed config
```

#### UC-CFG-WA-2: The environment does not override a plain YAML value

```gherkin
Given config.yml declares whatsapp.phone_number_id as "from-yaml"
And WHATSAPP_PHONE_NUMBER_ID is set to "from-environment"
When the machine-config loader runs
Then the typed WhatsApp config contains "from-yaml"
And no WhatsApp-specific environment fallback replaces it
```

#### UC-CFG-WA-3: The explicit enabled flag remains authoritative

```gherkin
Given whatsapp.enabled is false in config.yml
And all required WhatsApp credentials resolve successfully
When the typed machine config is built
Then whatsapp.enabled remains false
And credential presence does not auto-enable the adapter
```

#### UC-CFG-WA-4: Enabled WhatsApp requires its typed credentials

```gherkin
Given whatsapp.enabled is true in config.yml
And a required WhatsApp credential is absent after placeholder expansion
When configuration availability is validated
Then WhatsApp is reported as enabled but not configured
And the adapter does not start with a hidden process-environment fallback
```

#### UC-CFG-WA-5: Process-environment mutation cannot bypass loaded config

```gherkin
Given the typed WhatsApp config has already been built
When a WhatsApp environment variable changes in the running process
Then the effective WhatsApp config does not change
And consumers continue to use the value captured through machine-config loading
```

### Cross-context references

- `teleclaude/spec/feature/config/yaml-env-var-expansion` owns the generic
  placeholder-substitution behavior.
- The `integration` bounded context consumes the typed WhatsApp fields for
  outbound messaging, webhook verification, and invite-link construction.

## Allowed values

- Credential and service-identifier fields accept a resolved string or an
  absent value according to their typed field.
- `whatsapp.enabled` is a boolean and defaults to `false`.
- `template_language` defaults to `en_US` when absent.
- `api_version` remains an internal runtime constant rather than a public
  machine-config field.

## Known caveats

- Missing placeholder values are governed by the generic machine-config load
  and required-field validation paths; WhatsApp does not invent a local
  fallback.
- Changing a placeholder's environment value requires config reload before the
  typed aggregate can observe it.
