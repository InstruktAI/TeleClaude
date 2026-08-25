---
description: Unknown keys in user-facing overlays and machine config are rejected at their owning load boundary, while parser-declared dynamic mappings remain valid.
visibility: public
---

# Unknown Key Rejection — Spec

## Required reads

@docs/project/spec/domain/config.md

## What it is

Every file-backed configuration surface rejects undeclared keys at the boundary
that owns its schema. User-facing `teleclaude.yml` overlays are validated by
closed Pydantic models, so an unknown key prevents that overlay from loading.
The machine `config.yml` is validated against the accepted input shape declared
by each section parser before the runtime aggregate is built.

The machine-config contract is parser-shaped rather than dataclass-field-shaped.
A parser may intentionally accept aliases, compact mappings, or other input keys
that do not mirror the resulting runtime object. Those declared inputs remain
valid; only keys outside the parser's accepted vocabulary are rejected.

Rejection is immediate and actionable. The validation failure identifies the
configuration file and the dotted path of every offending key so an operator can
repair the source instead of discovering later that a typo was ignored.

## Canonical fields

### Use cases

#### UC-CFG-UNKNOWN-1 (r2): An unknown top-level overlay key blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains an undeclared top-level key
When the owning overlay is loaded
Then validation fails before the overlay becomes available to consumers
And the failure identifies the configuration file and the offending key path
```

#### UC-CFG-UNKNOWN-2 (r2): An unknown nested overlay key blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains an undeclared key inside a declared nested section
When the owning overlay is loaded
Then validation fails at that nested section
And the failure identifies the configuration file and the dotted offending key path
```

#### UC-CFG-UNKNOWN-3 (r2): An unknown key in a named overlay mapping blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains a mapping of named schema-backed entries
And one named entry contains an undeclared key
When the owning overlay is loaded
Then validation fails for that named entry
And the failure identifies the entry and offending key path
```

#### UC-CFG-UNKNOWN-4 (r2): An unknown key in an overlay list item blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains a list of schema-backed entries
And one entry contains an undeclared key
When the owning overlay is loaded
Then validation fails for that list item
And the failure identifies the item and offending key path
```

#### UC-CFG-UNKNOWN-5: An unknown machine agent key is rejected

```gherkin
Given an operator-authored config.yml declares an agent outside the supported agent vocabulary
When the machine configuration is loaded
Then validation fails before the runtime configuration becomes available
And the failure identifies the unsupported agent key
```

#### UC-CFG-UNKNOWN-6 (r2): An unknown machine-config key blocks loading

```gherkin
Given an operator-authored config.yml contains a key outside the accepted input shape of its owning section
When the machine configuration is loaded
Then validation fails before the runtime configuration becomes available
And the failure identifies the configuration file and dotted offending key path
```

#### UC-CFG-UNKNOWN-7: Parser-declared machine-config inputs remain valid

```gherkin
Given an operator-authored config.yml uses an input key explicitly accepted by its owning section parser
And that key does not mirror a field name on the resulting runtime object
When the machine configuration is loaded
Then the input is accepted
And the parser maps it into the typed runtime configuration aggregate
```

### Cross-context references

- The config bounded context owns the accepted vocabulary and the resulting
  validation failure for every configuration surface.
- Runtime and adapter consumers receive only configuration that has passed its
  owning load boundary; they do not implement secondary unknown-key handling.
- Parser-declared machine-config input shapes are part of the machine-load
  contract in `project/spec/feature/config/machine-config-load`.

## Allowed values

- Overlay keys declared by the owning Pydantic schema are accepted.
- Machine-config keys declared by the owning section parser are accepted,
  including deliberate aliases and dynamic mapping members.
- Any other key is rejected; there is no warn-and-continue or silent-drop path.

## Known caveats

- Fleet configuration must conform to the closed overlay schemas before strict
  validation is deployed everywhere. Compatibility is established against the
  complete registered fleet, not a sample.
- Dynamic mappings remain open only where their parser explicitly declares that
  input shape. An open mapping is not a general escape from unknown-key
  validation.
