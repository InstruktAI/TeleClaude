---
description: 'Every YAML config payload (layered `teleclaude.yml` overlays and the machine `config.yml`) is passed through env-var expansion that substitutes `${VAR}` references against the process environment before validation.'
visibility: 'public'
---

# YAML Env Var Expansion — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every YAML configuration source loaded by the config bounded context — the three
`teleclaude.yml` overlays (global, project, per-person), the legacy machine
`config.yml`, and the optional sibling `experiments.yml` — is passed through
env-var expansion AFTER the YAML parser parses the file and BEFORE the parsed
payload reaches schema validation (for the overlay path) or config construction
(for the legacy path). The expansion helper
walks the parsed structure recursively and substitutes every `${VAR}` token
inside string values with the corresponding value from the process environment.

The substitution shape is narrow on purpose. The recognised token is
`${VAR}` only — there is no `$VAR` form and no `${VAR:-default}` default
syntax. A reference whose environment variable is unset is left in place as
the literal `${VAR}` string; expansion does not raise, does not warn, and
does not drop the field. The helper is type-preserving for non-string inputs:
dicts and lists are walked recursively, primitives other than strings pass
through unchanged.

The substitution point is the same across every entry path, so any YAML
operator can be authored with env-var references and the same rules apply.
Test fixtures rely on this contract to inject values via the environment
without rewriting fixture files; secrets stay out of YAML by being authored
as `${SECRET_NAME}` placeholders and resolved from the process environment.

## Canonical fields

### Use cases

#### UC-CFG-EXPAND-1: Overlay load expands env vars before schema validation

```
Given path /repos/my-project/teleclaude.yml contains `business: { domains: { primary: "${MY_DOMAIN}" } }`
And MY_DOMAIN is set to "instrukt.ai" in the environment
When the config overlay loader runs
Then the YAML parser returns the raw dict with the literal "${MY_DOMAIN}" string
And env-var expansion walks the dict and substitutes "${MY_DOMAIN}" -> "instrukt.ai"
And the overlay schema validator receives "instrukt.ai" as the field value
And the returned project overlay holds business.domains["primary"] == "instrukt.ai"
```

#### UC-CFG-EXPAND-2: Missing env var leaves literal `${VAR}` token unchanged

```
Given a teleclaude.yml field contains the literal string "${UNSET_VAR}"
And UNSET_VAR is not set in the environment
When env-var expansion walks the parsed dict
Then the unresolved token is looked up against the process environment and returned unchanged
And the literal "${UNSET_VAR}" string is preserved in the output
And no warning, error, or log entry is emitted by the helper
And the schema validator receives "${UNSET_VAR}" as the field value (validation succeeds for plain str fields)
```

#### UC-CFG-EXPAND-3: Recursion descends into dicts, lists, and nested mixes

```
Given a parsed YAML payload of shape:
  { creds: { telegram: { user_name: "${TG_USER}" } },
    items: [ "${ITEM_A}", { nested: "${ITEM_B}" } ],
    count: 7 }
And the environment contains TG_USER, ITEM_A, ITEM_B
When env-var expansion is invoked on the payload
Then the helper dispatches dict -> per-key recursion
And dispatches list -> per-element recursion
And substitutes each string leaf using the same `\$\{([^}]+)\}` regex
And returns a new structure of the same shape with all three references replaced
And the integer 7 passes through unchanged (non-string primitives are returned as-is)
```

#### UC-CFG-EXPAND-4: Legacy config.yml expands env vars after the YAML parser runs

```
Given the resolved machine-config path points to a `config.yml` on disk
And the file contains a string with "${REDIS_URL}"
When the machine-config load runs
Then the YAML parser produces the raw mapping
And the env-var expansion pass runs on the raw mapping BEFORE the disallowed-runtime-keys check
And the built-in defaults merge and the typed runtime-config aggregate construction see the substituted values
```

#### UC-CFG-EXPAND-5: Sibling experiments.yml runs through the same helper

```
Given config.yml sits next to an optional experiments.yml file
And experiments.yml contains experiment entries with "${EXPERIMENT_FLAG}" references
When the machine-config load reaches the experiments side-file merge step
Then experiments.yml is read and parsed as YAML
And the env-var expansion pass substitutes the references on the raw experiments mapping
And the substituted experiments are merged into the user-config experiments list
```

#### UC-CFG-EXPAND-6: Default syntax is NOT supported

```
Given a YAML field contains "${VAR:-fallback}"
And the environment does NOT contain a literal entry named "VAR:-fallback"
When expand_env_vars walks the string
Then the regex matches "${VAR:-fallback}" as a single token
And the environment lookup for "VAR:-fallback" returns the original literal
And the substituted value is the unchanged literal "${VAR:-fallback}"
And no fallback semantics are applied (the colon-dash form has no meaning to this helper)
```

### Cross-context references

- The WhatsApp adapter applies a SECOND, stricter precedence rule on top
  of env-var expansion (see `whatsapp-env-var-override.md`): for its six
  credential fields, the process environment takes precedence over the
  YAML value even when the YAML value is a plain literal — not a
  `${VAR}` placeholder. That override is a per-field rule layered on top
  of the generic expansion documented here; it does not change how the
  generic expansion itself behaves.
- Consumed implicitly by every config consumer — the substitution is
  invisible past the loader. Once a value has been expanded, downstream
  code cannot distinguish a literal YAML value from a substituted
  env-var value.

## Allowed values

- Recognised token shape: `${NAME}` where `NAME` matches `[^}]+` (any
  characters other than `}`).
- Source of values: the process environment only. No fallback chain, no project-level
  env files, no `.env` loading by this helper.

## Known caveats

- **Missing env vars are silent.** A typo in a `${VAR}` reference produces a
  literal `${VAR}` string in the loaded config and no diagnostic. The field
  validator (or the consumer) will only notice if the literal happens to
  violate a downstream constraint.
- **No default-value syntax.** Patterns like `${VAR:-default}` or
  `${VAR:default}` are NOT recognised. The entire `VAR:-default` text is
  treated as the env-var name and almost always evaluates to "unset", at
  which point the literal token is preserved.
- **String-only substitution.** Tokens are only replaced inside string leaves.
  A YAML integer, boolean, or null is never expanded — it would have to be a
  quoted string in the source file to participate.
- **No type coercion.** Substituted env-var values are always strings; if a
  downstream schema field expects `int` or `bool`, the schema layer's own coercion
  rules apply after expansion. A `${PORT}` token expanded to `"8080"` will
  parse as `int` because the schema accepts numeric strings, but a value like
  `"not-a-number"` will fail validation downstream.
- **Two different load paths, same helper, different downstream models.**
  Overlay loads feed schema validation; the legacy machine load feeds
  the config construction pipeline (legacy path). The expansion contract is identical, but
  validation behavior diverges after expansion.
