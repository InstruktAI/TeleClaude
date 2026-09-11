---
description: YAML environment references resolve from the environment source owned by their configuration surface, without cross-tier fallback.
---

# YAML Env Var Expansion — Spec

## What it is

Environment-backed YAML values are resolved at the configuration boundary before typed validation. Each user-facing `teleclaude.yml` overlay resolves `${NAME}` references exclusively from the `.env` file beside that overlay: global, project, company, and person configuration therefore retain independent namespaces even when they use the same variable name.

Overlay resolution never consults the process environment or another configuration tier. A referenced name missing from the owning `.env` fails that overlay's load. Literal YAML values remain valid, and `.env` entries enter typed configuration only when a YAML value references them.

The machine `config.yml` and its optional `experiments.yml` remain a separate runtime surface. They resolve references from the machine runtime environment established at process startup under the machine-config contract.

### Business value

Operators can use conventional environment references without one person's, company's, or project's credentials being silently supplied by another scope. Serialized configuration retains references rather than resolved secrets.

## Canonical fields

### Overlay source ownership

| Configuration | YAML source                                            | Sole environment source  |
| ------------- | ------------------------------------------------------ | ------------------------ |
| Global        | `<teleclaude-home>/teleclaude.yml`                     | `<teleclaude-home>/.env` |
| Project       | `<project-root>/teleclaude.yml`                        | `<project-root>/.env`    |
| Company       | `<teleclaude-home>/companies/<company>/teleclaude.yml` | the sibling `.env`       |
| Person        | `<teleclaude-home>/people/<person>/teleclaude.yml`     | the sibling `.env`       |

No row inherits, shadows, or falls back to another row. The selected YAML path determines the environment path; environment variables do not redirect either source.

### Resolution and persistence

- Resolution walks mappings, lists, and string leaves recursively before schema validation.
- Only `${NAME}` tokens participate. Substituted values are strings; the typed schema owns any later coercion.
- A missing sibling `.env` is equivalent to an empty local environment. It is valid when the YAML contains no references and fails when a reference cannot resolve.
- Loading and resolving an overlay does not mutate the process environment.
- An unresolved reference fails with the variable name and owning configuration path, without exposing any resolved value.
- Saving an effective configuration preserves existing `${NAME}` references for values that were not explicitly replaced. An environment-backed edit writes the value to the owning `.env` and retains the reference in YAML.
- Arbitrary `.env` entries are not injected as model fields. Consumers that need an unreferenced credential use the config context's scope-owned credential-store interface.

### Use cases

#### UC-CFG-EXPAND-1

```gherkin
Given a user-facing configuration contains a `${NAME}` reference
And its sibling environment file contains NAME
When that configuration is loaded
Then the typed configuration contains the sibling file's value
And validation occurs after resolution
```

#### UC-CFG-EXPAND-2

```gherkin
Given a user-facing configuration contains a `${NAME}` reference
And its sibling environment file does not contain NAME
And NAME exists in the process environment or another configuration tier
When that configuration is loaded
Then loading fails for the unresolved local reference
And no value is taken from the process environment or another tier
```

#### UC-CFG-EXPAND-3

```gherkin
Given a configuration contains references inside mappings, lists, and nested combinations
When its environment references are resolved
Then every string leaf is resolved against the same owning environment source
And non-string values retain their types
```

#### UC-CFG-EXPAND-4

```gherkin
Given machine configuration contains an environment reference
And the machine runtime environment was established at process startup
When machine configuration is loaded
Then the reference resolves from that runtime environment
And user-facing overlay environment files do not participate
```

#### UC-CFG-EXPAND-5

```gherkin
Given an experiments side-file sits beside machine configuration
And it contains an environment reference
When machine configuration is loaded
Then the side-file uses the same machine runtime environment
And its resolved experiments are composed with the machine configuration
```

#### UC-CFG-EXPAND-6

```gherkin
Given a YAML value contains `${NAME:-fallback}`
When environment references are resolved
Then the token has no default-value semantics
And it is treated as an unresolved reference unless that exact supported name exists
```

#### UC-CFG-EXPAND-7

```gherkin
Given global, project, company, and person environment files each declare the same name with different values
And each corresponding configuration references that name
When the four configurations are loaded
Then each typed configuration contains only its sibling file's value
```

#### UC-CFG-EXPAND-8

```gherkin
Given an effective configuration contains a value resolved from `${NAME}`
When an unrelated field is edited and the configuration is saved
Then the YAML retains `${NAME}` rather than the resolved value
And the resolved value is not serialized into the YAML
```

## Allowed values

- Reference syntax: `${NAME}` where NAME is a non-empty environment-key identifier accepted by the environment-file parser.
- Overlay resolution source: the sibling `.env` only.
- Machine resolution source: the machine runtime environment only.
- Literal YAML strings remain literal and require no environment entry.

## Known caveats

- Resolved string values may be coerced by the destination schema; resolution itself performs no coercion.
- Environment files may contain keys not referenced by their adjacent YAML. Those keys remain credential-store material and do not expand the typed model's shape.
- Machine configuration remains intentionally distinct from the overlay system; this contract does not merge either configuration model or environment namespace.
