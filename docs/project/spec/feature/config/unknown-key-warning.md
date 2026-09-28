---
description: Unknown keys in user-facing overlays and machine config are rejected at their owning load boundary, while parser-declared dynamic mappings remain valid.
visibility: public
---

# Unknown Key Rejection — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every file-backed configuration surface rejects undeclared keys at the boundary
that owns its schema. User-facing `teleclaude.yml` overlays are validated by
closed Pydantic models, so an unknown key prevents that overlay from loading.
<!-- planned-change:unify-config-models-on-pydantic -->
The machine `config.yml` is validated against the accepted input shape declared
by each section parser before the runtime aggregate is built.

The machine-config contract is parser-shaped rather than dataclass-field-shaped.
A parser may intentionally accept aliases, compact mappings, or other input keys
that do not mirror the resulting runtime object. Those declared inputs remain
valid; only keys outside the parser's accepted vocabulary are rejected.
<!-- change:unify-config-models-on-pydantic -->
The machine `config.yml` is validated by the closed Pydantic models of the
typed runtime configuration aggregate, so the accepted vocabulary of every
configuration file is declared by its closed models.

A machine-config section model may deliberately accept input that does not
mirror its runtime object — an alias folded into another field, a mapping form
of a list, a key it accepts and supplies itself. It does not accept a runtime
field the platform derives. Only keys outside a section's declared vocabulary
are rejected.
<!-- /planned-change:unify-config-models-on-pydantic -->

Rejection is immediate and actionable. The validation failure identifies the
configuration file and the dotted path of every offending key so an operator can
repair the source instead of discovering later that a typo was ignored.

Recognized older shapes in stored local configuration are brought to the
current shape by the configuration migration list before validation
(`project/spec/feature/config/document-migration`). A read applies them in
memory and never writes; a migration run or a writer persists them, preserving
the represented value, unrelated content, comments, and identity claims.

Newly submitted configuration candidates are validated against the current
accepted vocabulary without migration. Neither path accepts arbitrary unknown
fields.

## Canonical fields

### Use cases

#### UC-CFG-UNKNOWN-1: An unknown top-level overlay key blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains an undeclared top-level key
When the owning overlay is loaded
Then validation fails before the overlay becomes available to consumers
And the failure identifies the configuration file and the offending key path
```

#### UC-CFG-UNKNOWN-2: An unknown nested overlay key blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains an undeclared key inside a declared nested section
When the owning overlay is loaded
Then validation fails at that nested section
And the failure identifies the configuration file and the dotted offending key path
```

#### UC-CFG-UNKNOWN-3: An unknown key in a named overlay mapping blocks loading

```gherkin
Given an operator-authored teleclaude.yml contains a mapping of named schema-backed entries
And one named entry contains an undeclared key
When the owning overlay is loaded
Then validation fails for that named entry
And the failure identifies the entry and offending key path
```

#### UC-CFG-UNKNOWN-4: An unknown key in an overlay list item blocks loading

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

#### UC-CFG-UNKNOWN-6: An unknown machine-config key blocks loading

```gherkin
Given an operator-authored config.yml contains a key outside the accepted input shape of its owning section
When the machine configuration is loaded
Then validation fails before the runtime configuration becomes available
And the failure identifies the configuration file and dotted offending key path
```

<!-- planned-change:unify-config-models-on-pydantic -->
#### UC-CFG-UNKNOWN-7: Parser-declared machine-config inputs remain valid

```gherkin
Given an operator-authored config.yml uses an input key explicitly accepted by its owning section parser
And that key does not mirror a field name on the resulting runtime object
When the machine configuration is loaded
Then the input is accepted
And the parser maps it into the typed runtime configuration aggregate
```
<!-- change:unify-config-models-on-pydantic -->
#### UC-CFG-UNKNOWN-7: Section-declared machine-config inputs remain valid

```gherkin
Given an operator-authored config.yml uses an input key explicitly accepted by its owning section
And that key does not mirror a field name on the resulting runtime object
When the machine configuration is loaded
Then the input is accepted
And it is mapped into the typed runtime configuration aggregate
```
<!-- /planned-change:unify-config-models-on-pydantic -->

#### UC-CFG-UNKNOWN-8: Recognized stored configuration migrates before consumption

#### UC-CFG-UNKNOWN-9: Conflicting migration preserves the source and fails explicitly

#### UC-CFG-UNKNOWN-10: An interrupted move remains safely retryable

#### UC-CFG-UNKNOWN-11: Concurrent migrations preserve each other's updates


#### UC-CFG-UNKNOWN-12: A key placed in the wrong checkpoint registry names the registry it belongs to

```gherkin
Given an operator-authored project configuration declares a checkpoint entry
And that entry carries a key the opposite checkpoint registry owns
When the project configuration is loaded
Then validation fails identifying that entry and naming the registry the key belongs to
And the operator reads that guidance rather than the generic undeclared-key failure
```


### Cross-context references

- The config bounded context owns the accepted vocabulary and the resulting
  validation failure for every configuration surface.
- Runtime and adapter consumers receive only configuration that has passed its
  owning load boundary; they do not implement secondary unknown-key handling.
<!-- planned-change:unify-config-models-on-pydantic -->
- Parser-declared machine-config input shapes are part of the machine-load
  contract in `project/spec/feature/config/machine-config-load`.
<!-- change:unify-config-models-on-pydantic -->
- Section-declared machine-config inputs are part of the machine-load contract
  in `project/spec/feature/config/machine-config-load`.
<!-- /planned-change:unify-config-models-on-pydantic -->

## Allowed values

- Overlay keys declared by the owning Pydantic schema are accepted.
<!-- planned-change:unify-config-models-on-pydantic -->
- Machine-config keys declared by the owning section parser are accepted,
  including deliberate aliases and dynamic mapping members.
<!-- change:unify-config-models-on-pydantic -->
- Machine-config keys declared by the owning section model are accepted,
  including deliberate aliases and dynamic mapping members.
<!-- /planned-change:unify-config-models-on-pydantic -->
- Any other key is rejected; there is no warn-and-continue or silent-drop path.

## Known caveats

- Configuration migration and strict validation apply to each installation's
  own files. Loading on one installation does not depend on the version,
  reachability, or migration state of another installation.
<!-- planned-change:unify-config-models-on-pydantic -->
- Dynamic mappings remain open only where their parser explicitly declares that
  input shape. An open mapping is not a general escape from unknown-key
  validation.
<!-- change:unify-config-models-on-pydantic -->
- Dynamic mappings remain open only where their section model explicitly
  declares that input shape. An open mapping is not a general escape from
  unknown-key validation.
<!-- /planned-change:unify-config-models-on-pydantic -->
- A key whose value is an unresolved environment reference is still subject to
  the section vocabulary: an undeclared key is rejected whether or not its
  reference resolves.
