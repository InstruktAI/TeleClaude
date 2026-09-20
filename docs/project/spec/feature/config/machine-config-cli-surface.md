---
description: The telec config surface is the sole agent front door for inspecting, mutating, and diagnosing machine configuration.
visibility: public
---

# Machine Config CLI Surface — Spec

## Required reads

@docs/project/spec/domain/config.md
@docs/project/spec/feature/config/atomic-project-config-write.md
@docs/project/spec/feature/config/machine-config-load.md
@docs/project/spec/feature/config/machine-config-write.md

## What it is

`telec config` is the sole agent-facing machine-configuration surface. Agents inspect state with `get`, mutate it with `patch` or a narrower semantic subcommand, diagnose existing state with `validate`, and use `wizard` for guided setup. The backing file is an implementation detail and is never an agent editing surface.

The surface shares one config-context owner with the runtime:

1. **One resolution.** Every command targets the same machine configuration the runtime loads; the process working directory never selects another file.
2. **One mutation authority.** A mutation reaches the config context as semantic intent. The config context holds the lock across reading the latest document, applying the operation, validating the complete candidate, and atomically replacing the file.
3. **Pre-write validation.** Invalid candidates are rejected before replacement and leave committed bytes unchanged. Successful return means the committed candidate is valid; no post-write validation step follows.
4. **Independent diagnosis.** `validate` evaluates existing state and reports its result. It is not part of a successful mutation flow.

## Canonical fields

### Use cases

#### UC-CFG-CLI-1: `get` reads the machine config the runtime loads

```gherkin
Given machine configuration contains a declared value
And an unrelated configuration file exists in the current working directory
When an agent runs `telec config get` for that value
Then the reported value comes from the machine configuration the runtime loads
And the working-directory file is not read
```

#### UC-CFG-CLI-2: `get` names the source it resolved

```gherkin
Given an agent runs `telec config get` with or without paths
When the command reports the requested configuration
Then it also reports the resolved machine-configuration path
```

#### UC-CFG-CLI-3: A schema-invalid patch is refused before replacement

```gherkin
Given the committed machine configuration is valid
And an agent submits a patch that violates the typed machine-config schema
When `telec config patch` evaluates the patch
Then the candidate is rejected with the schema error
And the command exits non-zero
And the committed machine configuration is unchanged
```

#### UC-CFG-CLI-4: A valid patch commits through one transaction

```gherkin
Given the committed machine configuration is valid
And an agent submits a schema-valid patch
When `telec config patch` applies the mutation
Then the config context reads the latest committed document under its lock
And applies and validates the complete candidate before replacement
And atomically replaces the machine configuration
And reports the committed result
```

#### UC-CFG-CLI-5: The working directory never selects the mutation target

```gherkin
Given an unrelated configuration file exists in the current working directory
When an agent runs `telec config patch`
Then the resolved machine configuration is the only file mutated
And the working-directory file is unchanged
```

#### UC-CFG-CLI-6: `validate` diagnoses existing state independently

```gherkin
Given an agent needs to diagnose existing machine configuration
When the agent runs `telec config validate`
Then the resolved machine configuration is built through the typed schema
And any schema failure is reported as a failed validation area
And the command exits non-zero when validation fails
And no configuration mutation occurs
```

#### UC-CFG-CLI-7: Repair commands remain reachable when current configuration is invalid

```gherkin
Given the committed machine configuration contains an undeclared key and violates the typed schema
When an agent invokes the machine-config validation or guided-repair surface
Then the command surface starts without requiring a valid effective runtime configuration
And reports the invalid state through the config context
When the agent patches the configuration with an explicit removal of the reported dotted key path
Then the config context removes that key from the latest raw document
And validates the complete candidate before persisting it through the machine-config writer
And subsequent validation succeeds
And direct file editing is not required
```

#### UC-CFG-CLI-8: Agents never mutate the backing file directly

```gherkin
Given an agent needs to change machine configuration
When the agent follows the supported configuration workflow
Then the mutation is expressed through `telec config`
And no shell editor, ad hoc script, or direct filesystem write targets the backing file
```

## Known caveats

- A candidate may depend on environment-backed values that are available during mutation but absent in a later runtime environment. The surface validates the candidate against the environment in which the operation runs.
- `validate` diagnoses committed state; it does not certify external services referenced by that state.

## See Also

- docs/project/spec/feature/config/stable-channel-pinning-rule.md
