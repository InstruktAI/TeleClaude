---
description: The computer-kind CLI addresses the runtime machine configuration through the config-owned transaction.
---

# Machine Config CLI Surface — Spec

## What it is

The machine configuration is addressed through `telec config computer` by its
fixed location in the machine home. It is a singleton with a distinct filename
and runtime loader, not an overlay tier. The command uses the same `init`, `list`, `get`, and
`patch` vocabulary as other configuration kinds while keeping machine-specific
validation and persistence in the config context. The working directory never
selects another machine file.

`init` creates a missing machine configuration or adds missing required
structure to an existing file without changing operator values. `get` reports
the declared machine view, its resolved source, and an opaque revision. `patch`
submits semantic changes with that revision to the config owner. The owner
holds its lock across reading, stale-revision comparison, mutation, complete
candidate validation, and atomic replacement. A rejected candidate leaves the
committed file unchanged.

`telec config validate` remains an explicit diagnostic across configured
subjects. It does not mutate configuration and is not part of a successful
patch flow. The configuration wizard remains an explicit interactive setup
surface, not an implicit target of a resource command.

## Canonical fields

### Use cases

#### UC-CFG-CLI-1: `get` reads the machine config the runtime loads

```gherkin
Given machine configuration contains a declared value
And an unrelated configuration file exists in the current working directory
When an agent reads the computer kind
Then the reported value comes from the machine configuration the runtime loads
And the working-directory file is not read
```

#### UC-CFG-CLI-2: `get` names the source and revision it resolved

```gherkin
Given an agent reads the computer kind
When the command reports the requested configuration
Then it names the resolved machine-configuration source
And it supplies a revision that identifies the committed state read
```

#### UC-CFG-CLI-3: A schema-invalid patch is refused before replacement

```gherkin
Given the committed machine configuration is valid
And an agent submits a patch that violates its typed schema
When the config owner evaluates the candidate
Then the candidate is rejected with the schema error
And the command exits non-zero
And the committed machine configuration is unchanged
```

#### UC-CFG-CLI-4: A valid patch commits through one transaction

```gherkin
Given an agent read the current machine configuration and obtained its revision
And the agent submits a schema-valid patch with that revision
When the config owner applies the mutation
Then it reads the latest committed document under its lock
And it refuses the patch if the revision is stale
And otherwise applies and validates the complete candidate before replacement
And atomically replaces the machine configuration and reports the committed result
```

#### UC-CFG-CLI-5: The working directory never selects the mutation target

```gherkin
Given an unrelated configuration file exists in the current working directory
When an authorized agent patches the computer kind
Then the resolved machine configuration is the only file mutated
And the working-directory file is unchanged
```

#### UC-CFG-CLI-6: `validate` diagnoses existing state independently

```gherkin
Given an agent needs to diagnose existing configuration
When the agent invokes explicit configuration validation
Then the configured subjects are evaluated through their typed schemas
And each invalid subject is identified
And no configuration mutation occurs
```

#### UC-CFG-CLI-7: Repair commands remain reachable when current configuration is invalid

```gherkin
Given the committed machine configuration violates its typed schema
When an agent invokes machine-config validation
Then the command surface starts without requiring a valid runtime aggregate
And reports the invalid state through the config context
When an authorized agent removes the offending field through a computer patch
Then the config context validates the corrected candidate before persisting it
And direct file editing is not required
```

#### UC-CFG-CLI-8: Agents never mutate the backing file directly

```gherkin
Given an agent needs to change machine configuration
When the agent follows the supported configuration workflow
Then the mutation is expressed through `telec config computer`
And no shell editor, ad hoc script, or direct filesystem write targets the backing file
```

## Known caveats

- A candidate may depend on environment-backed values available during
  mutation but absent in a later runtime environment. Validation uses the
  environment in which the operation runs.
- `validate` diagnoses committed state; it does not certify external services
  referenced by that state.
- `computer` is a CLI kind and file declaration, not an overlay context root.

## See Also

- docs/local/spec/feature/config/kind-addressed-configuration.md
- docs/local/adr/0099-address-configuration-by-kind.md
