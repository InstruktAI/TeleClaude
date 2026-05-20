---
id: 'project/spec/feature/config/yaml-env-var-expansion'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Every YAML config payload (layered teleclaude.yml overlays and the legacy machine config.yml) flows through expand_env_vars to substitute `${VAR}` references against os.environ before validation.'
---

# YAML Env Var Expansion — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every YAML configuration source loaded by v1 — the three `teleclaude.yml`
overlays (global, project, per-person), the legacy machine `config.yml`, and
the optional sibling `experiments.yml` — is passed through a single helper,
`expand_env_vars` from `teleclaude.utils`, AFTER `yaml.safe_load` parses the
file and BEFORE the parsed payload reaches Pydantic validation (for the
overlay path) or dataclass construction (for the legacy path). The helper
walks the parsed structure recursively and substitutes every `${VAR}` token
inside string values with the corresponding value from `os.environ`.

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

#### UC-CFG-EXPAND-1: Overlay load expands env vars before Pydantic validation

```
Given path /repos/my-project/teleclaude.yml contains `business: { domains: { primary: "${MY_DOMAIN}" } }`
And os.environ["MY_DOMAIN"] = "instrukt.ai"
When load_config(path, ProjectConfig) runs
Then yaml.safe_load returns the raw dict with the literal "${MY_DOMAIN}" string
And expand_env_vars walks the dict and substitutes "${MY_DOMAIN}" -> "instrukt.ai"
And ProjectConfig.model_validate receives "instrukt.ai" as the field value
And the returned ProjectConfig holds business.domains["primary"] == "instrukt.ai"
```

#### UC-CFG-EXPAND-2: Missing env var leaves literal `${VAR}` token unchanged

```
Given a teleclaude.yml field contains the literal string "${UNSET_VAR}"
And os.environ does NOT contain UNSET_VAR
When expand_env_vars walks the parsed dict
Then re.sub's replace_env_var calls os.getenv("UNSET_VAR", "${UNSET_VAR}")
And the literal "${UNSET_VAR}" string is preserved in the output
And no warning, error, or log entry is emitted by the helper
And Pydantic receives "${UNSET_VAR}" as the field value (validation succeeds for plain str fields)
```

#### UC-CFG-EXPAND-3: Recursion descends into dicts, lists, and nested mixes

```
Given a parsed YAML payload of shape:
  { creds: { telegram: { user_name: "${TG_USER}" } },
    items: [ "${ITEM_A}", { nested: "${ITEM_B}" } ],
    count: 7 }
And os.environ contains TG_USER, ITEM_A, ITEM_B
When expand_env_vars is invoked on the payload
Then the helper dispatches dict -> per-key recursion
And dispatches list -> per-element recursion
And substitutes each string leaf using the same `\$\{([^}]+)\}` regex
And returns a new structure of the same shape with all three references replaced
And the integer 7 passes through unchanged (non-string primitives are returned as-is)
```

#### UC-CFG-EXPAND-4: Legacy config.yml expands env vars after yaml.safe_load

```
Given _config_path resolves to a config.yml on disk
And the file contains a string with "${REDIS_URL}"
When teleclaude/config/__init__.py executes module load
Then `yaml.safe_load(f)` produces the raw dict at line 962
And `expand_env_vars(_raw_user_config)` is applied at line 965 BEFORE `_validate_disallowed_runtime_keys`
And the legacy DEFAULT_CONFIG merge and `_build_config` (dataclass construction) see the substituted values
```

#### UC-CFG-EXPAND-5: Sibling experiments.yml runs through the same helper

```
Given config.yml sits next to an optional experiments.yml file
And experiments.yml contains experiment entries with "${EXPERIMENT_FLAG}" references
When the module load reaches teleclaude/config/__init__.py:970-976
Then experiments.yml is read via yaml.safe_load
And expand_env_vars(_raw_experiments_config) substitutes the references at line 976
And the substituted experiments are merged into _user_config["experiments"]
```

#### UC-CFG-EXPAND-6: Default syntax is NOT supported

```
Given a YAML field contains "${VAR:-fallback}"
And os.environ does NOT contain a literal entry named "VAR:-fallback"
When expand_env_vars walks the string
Then the regex matches "${VAR:-fallback}" as a single token
And os.getenv("VAR:-fallback", "${VAR:-fallback}") returns the original literal
And the substituted value is the unchanged literal "${VAR:-fallback}"
And no fallback semantics are applied (the colon-dash form has no meaning to this helper)
```

### Implementation pointers (v1)

- `teleclaude/utils/__init__.py:122-144` — `expand_env_vars` definition (dict/list/str dispatch; regex `\$\{([^}]+)\}`; `os.getenv(env_var, match.group(0))` preserves missing tokens).
- `teleclaude/config/loader.py:58` — overlay path: `expand_env_vars(raw)` runs between `yaml.safe_load` and `model_class.model_validate`.
- `teleclaude/config/__init__.py:962-965` — legacy machine config: `yaml.safe_load` followed by `expand_env_vars` on `_raw_user_config`.
- `teleclaude/config/__init__.py:970-976` — sibling `experiments.yml`: same `yaml.safe_load` + `expand_env_vars` pattern.

### Cross-context references

- The WhatsApp adapter applies a SECOND, stricter precedence rule on top of
  env-var expansion (see `whatsapp-env-var-override`): for the six
  `WHATSAPP_*` credential fields, `os.environ` takes precedence over the
  YAML value even when the YAML value is a plain literal — not a `${VAR}`
  placeholder. That override is a per-field rule layered on top of the
  generic expansion documented here; it does not change how `expand_env_vars`
  itself behaves.
- Consumed implicitly by every config consumer — the substitution is
  invisible past the loader. Once a value has been expanded, downstream code
  cannot distinguish a literal YAML value from a substituted env-var value.

## Allowed values

- Recognised token shape: `${NAME}` where `NAME` matches `[^}]+` (any
  characters other than `}`).
- Source of values: `os.environ` only. No fallback chain, no project-level
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
  downstream Pydantic field expects `int` or `bool`, Pydantic's own coercion
  rules apply after expansion. A `${PORT}` token expanded to `"8080"` will
  parse as `int` because Pydantic accepts numeric strings, but a value like
  `"not-a-number"` will fail validation downstream.
- **Two different load paths, same helper, different downstream models.**
  Overlay loads feed Pydantic (`load_config`); the legacy machine load feeds
  dataclasses (`_build_config`). The expansion contract is identical, but
  validation behavior diverges after expansion.
