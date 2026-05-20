---
id: 'project/spec/feature/config/whatsapp-env-var-override'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'WhatsApp credential fields are resolved with environment variables taking precedence over YAML values, and the adapter auto-enables when both phone_number_id and access_token resolve to truthy values.'
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
And os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "from-env"
When the config loader runs
Then the YAML parse first sets whatsapp_phone_number_id = "from-yaml"
And the line `whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or whatsapp_phone_number_id` evaluates "from-env" (truthy) and assigns it
And WhatsAppConfig.phone_number_id == "from-env"
```

#### UC-CFG-WA-2: YAML value is used when env var is unset

```
Given whatsapp.access_token = "yaml-token" in YAML
And WHATSAPP_ACCESS_TOKEN is not set in the environment
When the config loader runs
Then os.getenv("WHATSAPP_ACCESS_TOKEN") returns None
And `None or "yaml-token"` evaluates to "yaml-token"
And WhatsAppConfig.access_token == "yaml-token"
```

#### UC-CFG-WA-3: Env var with empty string falls through to YAML

```
Given whatsapp.webhook_secret = "yaml-secret" in YAML
And os.environ["WHATSAPP_WEBHOOK_SECRET"] = "" (empty string, falsy)
When the config loader runs
Then os.getenv returns "" which is falsy
And `"" or "yaml-secret"` evaluates to "yaml-secret"
And WhatsAppConfig.webhook_secret == "yaml-secret"
```

#### UC-CFG-WA-4: Adapter auto-enables when both credentials resolve, regardless of YAML enabled flag

```
Given whatsapp.enabled = false in YAML
And whatsapp.phone_number_id = "pid" in YAML
And whatsapp.access_token = "tok" in YAML
When the config loader runs
Then whatsapp_enabled_flag = False (from the explicit YAML "enabled")
And whatsapp_phone_number_id and whatsapp_access_token are both truthy
And whatsapp_enabled = False or bool("pid" and "tok") = True
And WhatsAppConfig.enabled == True
```

#### UC-CFG-WA-5: Adapter auto-enables when both credentials come from env vars only

```
Given the whatsapp YAML block is absent (whatsapp_raw is None)
And os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "env-pid"
And os.environ["WHATSAPP_ACCESS_TOKEN"] = "env-tok"
When the config loader runs
Then the `isinstance(whatsapp_raw, dict)` branch is skipped
And whatsapp_enabled_flag remains False (its initial value)
And whatsapp_phone_number_id = os.getenv(...) or None = "env-pid"
And whatsapp_access_token = "env-tok"
And whatsapp_enabled = False or bool("env-pid" and "env-tok") = True
And WhatsAppConfig.enabled == True with credentials from the environment
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
And whatsapp_enabled = False or bool("pid" and None) = False or False = False
And WhatsAppConfig.enabled == False
```

#### UC-CFG-WA-7: template_language defaults to "en_US" through every absence path

```
Given the whatsapp YAML block is absent
And WHATSAPP_TEMPLATE_LANGUAGE is unset
When the config loader runs
Then whatsapp_template_language stays at its initial value "en_US"
And the env-var override `os.getenv(...) or whatsapp_template_language` evaluates to "en_US"
And WhatsAppConfig.template_language == "en_US"
```

#### UC-CFG-WA-8: enabled flag in YAML can enable adapter even without credentials

```
Given whatsapp.enabled = true in YAML
And whatsapp.phone_number_id is absent (None)
And whatsapp.access_token is absent (None)
When the config loader runs
Then whatsapp_enabled_flag = True
And whatsapp_enabled = True or bool(None and None) = True
And WhatsAppConfig.enabled == True even though credentials are missing
```

### Implementation pointers (v1)

- `teleclaude/config/__init__.py:806-812` — initial values for the WhatsApp locals (`None` for credentials, `"en_US"` for template_language, `False` for `whatsapp_enabled_flag`).
- `teleclaude/config/__init__.py:814-825` — YAML parsing: `if isinstance(whatsapp_raw, dict)` reads each field with truthy guards, and `whatsapp_enabled_flag = bool(whatsapp_raw.get("enabled", False))`.
- `teleclaude/config/__init__.py:827-832` — env-var override block: each credential field is reassigned via `os.getenv("WHATSAPP_<FIELD>") or <yaml_value>`. Env wins on truthy, falls through on None/empty.
- `teleclaude/config/__init__.py:834` — `whatsapp_enabled = whatsapp_enabled_flag or bool(whatsapp_phone_number_id and whatsapp_access_token)` — combined enable check.
- `teleclaude/config/__init__.py:929-939` — `WhatsAppConfig(...)` construction inside the returned `Config`. `api_version` is set from the module-level `WHATSAPP_API_VERSION` constant, NOT from YAML or env.
- `teleclaude/config/__init__.py:202-214` — `WhatsAppConfig` dataclass with `enabled: bool = False` as the dataclass default. The loader always passes an explicit `enabled` value, so the dataclass default only applies to ad-hoc constructions outside the loader.

### Cross-context references

- Consumed by the WhatsApp adapter in `integration` for outbound messaging and webhook verification. The adapter relies on the loader-computed `enabled` flag to decide whether to start.
- v2 inheritance: per `docs/project/spec/domain/config.md`, the v2 `config` bounded context standardises env-var precedence across all integration credentials via the effective-configuration model. v1's per-field manual `os.getenv(...) or <yaml>` pattern is the de facto convention until that generalization lands.

## Allowed values

- All six credential fields: any string (env or YAML) or null/missing. Empty strings are treated as falsy.
- `whatsapp.enabled`: boolean. Default: `False`. The loader's combined enable check can still flip the effective value to `True` based on resolved credentials.
- `template_language`: defaults to `"en_US"` when neither YAML nor env supplies it.
- `api_version`: NOT configurable via YAML or env in v1; sourced from the `WHATSAPP_API_VERSION` module constant.

## Known caveats

- **Empty string in env is treated as "unset".** Because the override uses Python's `or` operator, `WHATSAPP_ACCESS_TOKEN=""` does NOT clear a YAML-supplied token; it falls back to the YAML value. To force "no value", remove the YAML key (or set it to a falsy value) AND leave the env var unset.
- **`api_version` cannot be overridden.** Unlike the six credential fields, `api_version` is hard-wired to `WHATSAPP_API_VERSION`. Pointing the adapter at a different Graph API version requires a code change.
- **Auto-enable cannot be disabled when both credentials are present.** Setting `enabled: false` in YAML does NOT suppress auto-enable if both `phone_number_id` and `access_token` resolve to truthy values. The OR in the enable check makes the explicit false subordinate to the implicit credential signal. An operator who wants the adapter genuinely OFF must also clear at least one credential (in both YAML and env).
- **Env vars are read at load time, not on demand.** Mutating `os.environ` after `load_config` has run does not change `WhatsAppConfig`; the daemon must reload to see new env values.
- **`whatsapp.template_language` empty in YAML becomes "en_US".** The YAML parse uses `str(whatsapp_raw.get("template_language") or "en_US")` — an empty string or `null` in YAML is replaced with `"en_US"` before the env-var override even runs.
- **Tests must isolate env state.** Because env wins on truthy, any test asserting YAML-driven WhatsApp config behavior must ensure `WHATSAPP_*` are unset (or explicitly empty) in the test environment, or the assertion will read the leaked env value instead.
- **`whatsapp_enabled_flag` default is `False` outside the YAML branch.** When the whatsapp YAML block is missing entirely, the explicit-enabled signal is permanently `False`; the only path to enabling is the credential auto-enable. An operator who omits the whatsapp YAML block while setting only one env-var credential gets a disabled adapter (see UC-CFG-WA-6 logic).
