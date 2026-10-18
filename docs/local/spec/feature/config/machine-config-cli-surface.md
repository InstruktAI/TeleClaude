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
the effective machine view (`local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`),
its resolved source, and an opaque revision. `patch`
submits semantic changes with that revision to the config owner. The owner
holds its lock across reading, stale-revision comparison, mutation, complete
candidate validation, and atomic replacement. A rejected candidate leaves the
committed file unchanged.

Candidate-validation failures are handled refusals: the config resource reports
an invalid candidate, and the CLI prints a safe description naming the source
file and failing field or dotted key path. The description contains no submitted
values or exception traceback, consistent with safe external diagnostics
(`sdlc/policy/security-awareness`).

`telec config validate` remains an explicit diagnostic across configured
subjects. It does not mutate configuration and is not part of a successful
patch flow. The configuration wizard remains an explicit interactive setup
surface, not an implicit target of a resource command.

## Canonical fields

### Use cases

#### UC-CFG-CLI-1: An operator can inspect effective machine settings

```gherkin
Given an operator wants to inspect a machine setting
When they read the computer configuration
Then they see the effective value and the source that supplies it
```

#### UC-CFG-CLI-2: `get` names the source and revision it resolved

#### UC-CFG-CLI-3: An operator gets a safe refusal for an invalid settings change

```gherkin
Given an operator needs to change a machine setting
And the proposed value violates the machine configuration schema
When they submit it through the computer configuration command
Then the change is rejected with a handled schema-error description naming the source file and failing field or key path
And the description exposes no submitted values or exception traceback
And the command exits non-zero
And the committed machine configuration is unchanged
```

#### UC-CFG-CLI-4: A valid patch commits through one transaction

```gherkin
Given an operator wants to change a machine setting
When they submit a valid change through the computer configuration command
Then the new setting is saved and the command reports the committed result
```

#### UC-CFG-CLI-5: The working directory never selects the mutation target

#### UC-CFG-CLI-6: `validate` diagnoses existing state independently

```gherkin
Given an operator wants to check configured subjects for invalid settings
When they invoke explicit configuration validation
Then each invalid subject is identified
And configuration remains unchanged
```

#### UC-CFG-CLI-7: Repair commands remain reachable when current configuration is invalid

```gherkin
Given an operator's saved machine configuration is invalid
When they use the configuration command to remove or correct the offending setting
Then the corrected configuration is validated before it is saved
```

#### UC-CFG-CLI-8: Ordinary configuration edits use daemon-owned operations

## Known caveats

- Configuration commands require the addressed daemon. When it is unavailable,
  an agent may repair configuration files directly as recovery under
  `general/policy/machine-config-mutation-authority`; ordinary client execution
  remains daemon-owned.

- A candidate may depend on environment-backed values available during
  mutation but absent in a later runtime environment. Validation uses the
  environment in which the operation runs.
- `validate` diagnoses committed state; it does not certify external services
  referenced by that state.
- `computer` is a CLI kind and file declaration, not an overlay context root.

## See Also

- docs/local/spec/feature/config/kind-addressed-configuration.md
- docs/local/adr/0099-address-configuration-by-kind.md
