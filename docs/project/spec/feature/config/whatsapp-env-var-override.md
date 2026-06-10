---
description: 'WhatsApp credential fields are resolved with environment variables taking precedence over YAML values, and the adapter auto-enables when both `phone_number_id` and `access_token` resolve to truthy values.'
visibility: 'public'
---

# WhatsApp Env Var Override — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The WhatsApp adapter block in `teleclaude.yml` accepts six credential fields:
`phone_number_id`, `access_token`, `webhook_secret`, `verify_token`,
`template_name`, and `template_language`. v1 applies a fixed precedence rule
to each of them at config load time: if a corresponding `WHATSAPP_*`
environment variable is set to a truthy value, that env-var value WINS over
whatever appears in the YAML. The YAML value is the fallback, used only when
the env var is unset or empty.

The same load step then computes the adapter's effective `enabled` flag from
TWO sources: the explicit `enabled` boolean from YAML, OR the implicit signal
that both `phone_number_id` AND `access_token` resolved to truthy values
(after env-var override). Either path enables the adapter; the operator does
not have to set `enabled: true` in YAML when credentials are supplied via
environment variables.

The implication for testing and operator workflow: an operator can keep
secrets out of YAML entirely by setting `WHATSAPP_PHONE_NUMBER_ID` and
`WHATSAPP_ACCESS_TOKEN` in the environment; the adapter will still auto-enable.
Conversely, a test harness that overrides credentials via env var will see
those values regardless of whatever is committed in YAML — env always wins.

## Canonical fields

### Use cases

#### UC-CFG-WA-1: Env var overrides YAML value when both are set

```
Given whatsapp.phone_number_id = "from-yaml" in YAML
And WHATSAPP_PHONE_NUMBER_ID is set to "from-env" in the environment
When the config loader runs
Then the YAML parse first sets whatsapp_phone_number_id = "from-yaml"
And the env-var override takes "from-env" (truthy) and assigns it
And the resolved WhatsApp config's phone_number_id is "from-env"
```

#### UC-CFG-WA-2: YAML value is used when env var is unset

```
Given whatsapp.access_token = "yaml-token" in YAML
And WHATSAPP_ACCESS_TOKEN is not set in the environment
When the config loader runs
Then the environment lookup for WHATSAPP_ACCESS_TOKEN returns None
And `None or "yaml-token"` evaluates to "yaml-token"
And the resolved WhatsApp config's access_token is "yaml-token"
```

#### UC-CFG-WA-3: Env var with empty string falls through to YAML

```
Given whatsapp.webhook_secret = "yaml-secret" in YAML
And WHATSAPP_WEBHOOK_SECRET is set to "" (empty string, falsy) in the environment
When the config loader runs
Then the environment lookup returns "" which is falsy
And `"" or "yaml-secret"` evaluates to "yaml-secret"
And the resolved WhatsApp config's webhook_secret is "yaml-secret"
```

#### UC-CFG-WA-4: Adapter auto-enables when both credentials resolve, regardless of YAML enabled flag

```
Given whatsapp.enabled = false in YAML
And whatsapp.phone_number_id = "pid" in YAML
And whatsapp.access_token = "tok" in YAML
When the config loader runs
Then whatsapp_enabled_flag = False (from the explicit YAML "enabled")
And whatsapp_phone_number_id and whatsapp_access_token are both truthy
And the WhatsApp adapter resolves to enabled because both credentials are truthy
And the resolved WhatsApp config's enabled is True
```

#### UC-CFG-WA-5: Adapter auto-enables when both credentials come from env vars only

```
Given the whatsapp YAML block is absent (no whatsapp block present)
And WHATSAPP_PHONE_NUMBER_ID is set to "env-pid" in the environment
And WHATSAPP_ACCESS_TOKEN is set to "env-tok" in the environment
When the config loader runs
Then the whatsapp-is-a-mapping branch is skipped
And whatsapp_enabled_flag remains False (its initial value)
And whatsapp_phone_number_id resolves to "env-pid" from the environment
And whatsapp_access_token = "env-tok"
And the WhatsApp adapter resolves to enabled because both env-var credentials are truthy
And the resolved WhatsApp config's enabled is True, with credentials from the environment
```

#### UC-CFG-WA-6: Adapter stays disabled when only one credential resolves

```
Given whatsapp.phone_number_id = "pid" in YAML
And whatsapp.access_token is absent in YAML and WHATSAPP_ACCESS_TOKEN is unset
And whatsapp.enabled is absent in YAML (defaults to False)
When the config loader runs
Then whatsapp_enabled_flag = False
And whatsapp_phone_number_id = "pid"
And whatsapp_access_token = None
And the WhatsApp adapter stays disabled because a credential is missing
And the resolved WhatsApp config's enabled is False
```

#### UC-CFG-WA-7: template_language defaults to "en_US" through every absence path

```
Given the whatsapp YAML block is absent
And WHATSAPP_TEMPLATE_LANGUAGE is unset
When the config loader runs
Then whatsapp_template_language stays at its initial value "en_US"
And the env-var override evaluates to "en_US" (env unset, falls back to default)
And the resolved WhatsApp config's template_language is "en_US"
```

#### UC-CFG-WA-8: enabled flag in YAML can enable adapter even without credentials

```
Given whatsapp.enabled = true in YAML
And whatsapp.phone_number_id is absent (None)
And whatsapp.access_token is absent (None)
When the config loader runs
Then whatsapp_enabled_flag = True
And the WhatsApp adapter stays enabled because the YAML-configured enabled flag was already True
And the resolved WhatsApp config's enabled is True even though credentials are missing
```

### Cross-context references

- Consumed by the WhatsApp adapter in the `integration` bounded context
  for outbound messaging and webhook verification. The adapter relies on
  the loader-computed `enabled` flag to decide whether to start.
- The `config` bounded context (`project/spec/domain/config.md`)
  standardises env-var precedence across all integration credentials via
  the effective-configuration model. The per-field manual env-overrides-yaml
  pattern is the convention until that generalization lands.

## Allowed values

- All six credential fields: any string (env or YAML) or null/missing. Empty strings are treated as falsy.
- `whatsapp.enabled`: boolean. Default: `False`. The loader's combined enable check can still flip the effective value to `True` based on resolved credentials.
- `template_language`: defaults to `"en_US"` when neither YAML nor env supplies it.
- `api_version`: NOT configurable via YAML or env in v1; sourced from the `WHATSAPP_API_VERSION` module constant.

## Known caveats

- **Empty string in env is treated as "unset".** Because the override uses Python's `or` operator, `WHATSAPP_ACCESS_TOKEN=""` does NOT clear a YAML-supplied token; it falls back to the YAML value. To force "no value", remove the YAML key (or set it to a falsy value) AND leave the env var unset.
- **`api_version` cannot be overridden.** Unlike the six credential fields, `api_version` is hard-wired to `WHATSAPP_API_VERSION`. Pointing the adapter at a different Graph API version requires a code change.
- **Auto-enable cannot be disabled when both credentials are present.** Setting `enabled: false` in YAML does NOT suppress auto-enable if both `phone_number_id` and `access_token` resolve to truthy values. The OR in the enable check makes the explicit false subordinate to the implicit credential signal. An operator who wants the adapter genuinely OFF must also clear at least one credential (in both YAML and env).
- **Env vars are read at load time, not on demand.** Mutating the process environment after the config load has run does not change the WhatsApp configuration; the runtime must reload to see new env values.
- **`whatsapp.template_language` empty in YAML becomes "en_US".** An empty string or `null` in YAML is replaced with `"en_US"` before the env-var override even runs — the YAML parse normalises a falsy `template_language` to the default value before any env lookup.
- **Tests must isolate env state.** Because env wins on truthy, any test asserting YAML-driven WhatsApp config behavior must ensure `WHATSAPP_*` are unset (or explicitly empty) in the test environment, or the assertion will read the leaked env value instead.
- **`whatsapp_enabled_flag` default is `False` outside the YAML branch.** When the whatsapp YAML block is missing entirely, the explicit-enabled signal is permanently `False`; the only path to enabling is the credential auto-enable. An operator who omits the whatsapp YAML block while setting only one env-var credential gets a disabled adapter (see UC-CFG-WA-6 logic).
