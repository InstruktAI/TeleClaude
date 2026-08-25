---
description: Each user-facing config level rejects misplaced and undeclared keys at its owning load boundary instead of accepting ineffective configuration.
---

# Per-Level Key Restriction — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Each layer of the user-facing configuration surface owns a fixed set of keys.
The config bounded context rejects a key that belongs to another layer, and its
closed schema also rejects any other undeclared key. A misplaced or mistyped
setting therefore fails at load time instead of being retained as ineffective
extra data.

The overlay schemas keep their level-specific before-validation checks where a
more precise ownership error is useful. Those checks cover declared concepts
known to belong elsewhere; the closed Pydantic schema is the complete fallback
for every other unknown key. The machine `config.yml` follows the same outcome
through parser-declared accepted input shapes rather than overlay models.

## Canonical fields

### Use cases

#### UC-CFG-KEYREJECT-1 (r2): Project file rejects a global-only key

```gherkin
Given a project teleclaude.yml contains a top-level people list
When the project overlay loader parses the file
Then validation fails before the project overlay becomes available
And the failure identifies people as not allowed at project level
```

#### UC-CFG-KEYREJECT-2 (r2): Project file rejects multiple misplaced keys

```gherkin
Given a project teleclaude.yml contains both creds and timezone
When the project overlay loader parses the file
Then validation fails before the project overlay becomes available
And the failure identifies both misplaced keys
```

#### UC-CFG-KEYREJECT-3 (r2): Global file rejects a person-owned key

```gherkin
Given the global teleclaude.yml contains a top-level creds block
When the global overlay loader parses the file
Then validation fails before the global overlay becomes available
And the failure identifies creds as not allowed at global level
```

#### UC-CFG-KEYREJECT-4 (r2): Global file accepts its declared keys

```gherkin
Given the global teleclaude.yml contains only people, subscriptions, and interests
When the global overlay loader parses the file
Then the level restriction passes
And the closed global schema accepts the declared keys
And the global overlay loads normally
```

#### UC-CFG-KEYREJECT-5 (r2): Person file rejects a project-owned key

```gherkin
Given a person teleclaude.yml contains a business block
When the person overlay loader parses the file
Then validation fails before the person overlay becomes available
And the failure identifies business as not allowed at person level
```

#### UC-CFG-KEYREJECT-6 (r2): Any other undeclared overlay key is rejected

```gherkin
Given a teleclaude.yml overlay contains a key absent from both its level-specific restriction set and its declared schema
When the owning overlay loader parses the file
Then the closed schema rejects the key
And the failure identifies the configuration file and dotted offending key path
```

#### UC-CFG-KEYREJECT-7 (r2): Machine keys follow parser ownership

```gherkin
Given a machine config.yml contains a key not accepted by the parser that owns its section
When the machine configuration is loaded
Then validation fails before the runtime aggregate becomes available
And the failure identifies the dotted offending key path
```

#### UC-CFG-KEYREJECT-8 (r2): Non-mapping input never becomes configuration

```gherkin
Given a configuration file has a scalar or list where a mapping is expected
When the owning load boundary processes the parsed YAML
Then an overlay fails its Pydantic mapping validation
And a machine file follows its existing empty-user-config path to the required-agents failure
And neither surface makes a configuration object available to consumers
```

### Cross-context references

- The config bounded context owns every level's accepted vocabulary and load
  failure. Consumers never repeat these restrictions.
- General unknown-key handling and parser-declared machine shapes are specified
  by `project/spec/feature/config/unknown-key-warning`.
- Overlay loading remains part of layered configuration resolution; machine
  loading remains a separate file-backed surface.

## Allowed values

The level-specific checks reject these known misplaced top-level keys before
normal schema parsing:

| Layer           | Explicitly misplaced keys                        |
| --------------- | ------------------------------------------------ |
| Project overlay | `people`, `ops`, `creds`, `timezone`, `workflow` |
| Global overlay  | `creds`, `timezone`                              |
| Person overlay  | `people`, `ops`, `business`, `timezone`          |

Every key not declared by the owning overlay schema or machine parser is also
rejected. There is no extra-field store and no warn-and-continue path.

## Known caveats

- The explicit level checks exist for actionable ownership errors; they are not
  the completeness mechanism. Closed schema validation prevents a newly added
  concept from becoming silently effective at the wrong level when a hand-kept
  restriction set has not yet named it.
- Machine mappings whose member names are intentionally dynamic remain valid
  only where the owning parser declares that dynamic input shape.
