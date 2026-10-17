---
description: YAML environment references resolve from the environment source owned by their configuration surface, without cross-tier fallback; a reference with no value on a computer leaves its field absent there.
visibility: 'public'
---

# YAML Env Var Expansion — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

Environment-backed YAML values are resolved at the configuration boundary before typed validation. Each user-facing `teleclaude.yml` overlay resolves `${NAME}` and `${NAME:-default}` references exclusively from the `.env` file beside that overlay: global, project, company, and person configuration therefore retain independent namespaces even when they use the same variable name.

Overlay resolution never consults the process environment or another configuration tier. A reference that carries a default resolves to that default when the owning environment holds no value for its name, so it is never absent. A value that is one whole `${NAME}` reference with no value in the owning `.env` is absent on that computer: its field takes the schema's declared default or stays unset, and a consumer that needs the value refuses, naming what it lacks. A field that a computer role needs declares so against the machine configuration (`local/projects/teleclaude/spec/teleclaude-config`, Tier declaration and editor schemas), and that computer's readiness judgment reports the declaration when the reference has no value there; the document itself still loads. A reference without a default embedded in a longer value has no absent form, so it resolves or fails that overlay's load. Literal YAML values remain valid, and `.env` entries enter typed configuration only when a YAML value references them.

The machine `config.yml` and its optional `experiments.yml` remain a separate runtime surface. They resolve references from the machine runtime environment: the process environment with the TeleClaude checkout's `.env` applied at every resolution, shell-provided variables taking precedence. Every reader of the machine configuration resolves from that one environment, whether it loads, validates or writes, by the same absent-value rule.

### Business value

Operators can use conventional environment references without one person's, company's, or project's credentials being silently supplied by another scope. Serialized configuration retains references rather than resolved secrets. Configuration files travel to every computer while `.env` files stay per computer, so a value only some computers hold never makes the file unreadable on the others.

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
- A reference is `${NAME}` or `${NAME:-default}`. Any other `${...}` token fails that configuration's load, naming the value's path. Substituted values are strings; the typed schema owns any later coercion.
- The destination field's declared type determines scalar meaning after resolution. Boolean fields parse recognized boolean spellings by value, numeric fields use their declared numeric conversion, and text fields retain text. A value rejected by the destination type fails at the configuration boundary (`sdlc/policy/code-quality`).
- A missing sibling `.env` is equivalent to an empty local environment: every whole-value reference without a default is then absent.
- Loading and resolving an overlay does not mutate the process environment.
- A configuration file read from a committed snapshot rather than the working tree resolves from no environment file: a snapshot never carries a `.env` and receives none, so every whole-value reference without a default in it is absent, and commit-time and publication checks judge the document alone.
- An unresolved reference embedded in a longer value fails with the variable name and owning configuration path, without exposing any resolved value.
- Saving an effective configuration preserves existing `${NAME}` references for values that were not explicitly replaced, including references whose value is absent on the saving computer. An environment-backed edit writes the value to the owning `.env` and retains the reference in YAML; an edit to the value the reference already resolves to, its default included, writes nothing.
- Arbitrary `.env` entries are not injected as model fields. Consumers that need an unreferenced credential use the config context's scope-owned credential-store interface.

### Use cases

#### UC-CFG-EXPAND-1: An operator uses a scoped environment value in configuration

```gherkin
Given an operator keeps a configuration value in the environment source owned by that configuration
When they reference it from YAML and use the configuration
Then the typed setting uses that value without copying the secret into the configuration file
```

#### UC-CFG-EXPAND-2

#### UC-CFG-EXPAND-3

#### UC-CFG-EXPAND-4

#### UC-CFG-EXPAND-5

#### UC-CFG-EXPAND-6

#### UC-CFG-EXPAND-7

#### UC-CFG-EXPAND-8: An operator saves changes without serializing secrets

```gherkin
Given an operator edits an unrelated setting in a configuration that contains an environment reference
When the configuration is saved
Then the reference remains in YAML and its resolved secret is not serialized there
```

#### UC-CFG-EXPAND-9

#### UC-CFG-EXPAND-10

## Allowed values

- Reference syntax: `${NAME}` or `${NAME:-default}`, where NAME is a letter or underscore followed by letters, digits, or underscores, and the default is the literal text up to the closing brace, possibly empty.
- Overlay resolution source: the sibling `.env` only.
- Machine resolution source: the machine runtime environment only.
- Literal YAML strings remain literal and require no environment entry.

## Known caveats

- Resolved string values may be coerced by the destination schema; resolution itself performs no coercion.
- Environment files may contain keys not referenced by their adjacent YAML. Those keys remain credential-store material and do not expand the typed model's shape.
- Machine configuration remains intentionally distinct from the overlay system; this contract does not merge either configuration model or environment namespace.
