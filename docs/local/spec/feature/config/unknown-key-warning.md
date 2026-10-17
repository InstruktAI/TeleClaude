---
description: Unknown keys in user-facing overlays and machine config are rejected at their owning load boundary, while parser-declared dynamic mappings remain valid.
visibility: public
---

# Unknown Key Rejection — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

Every file-backed configuration surface rejects undeclared keys at the boundary
that owns its schema. User-facing `teleclaude.yml` overlays are validated by
closed Pydantic models, so an unknown key prevents that overlay from loading.
The machine `config.yml` is validated by the closed Pydantic models of the
typed runtime configuration aggregate, so the accepted vocabulary of every
configuration file is declared by its closed models.

A machine-config section model may deliberately accept input that does not
mirror its runtime object — an alias folded into another field, a mapping form
of a list, a key it accepts and supplies itself. It does not accept a runtime
field the platform derives. Only keys outside a section's declared vocabulary
are rejected.

Rejection is immediate and actionable. The validation failure identifies the
configuration file and the dotted path of every offending key so an operator can
repair the source instead of discovering later that a typo was ignored.

Recognized older shapes in stored local configuration are brought to the
current shape by the configuration migration list before validation
(`local/projects/teleclaude/spec/feature/config/document-migration`). A read applies them in
memory and never writes; a migration run or a writer persists them, preserving
the represented value, unrelated content, comments, and identity claims.

Newly submitted configuration candidates are validated against the current
accepted vocabulary without migration. Neither path accepts arbitrary unknown
fields.

## Canonical fields

### Use cases

#### UC-CFG-UNKNOWN-1: An operator can diagnose an unsupported configuration key

```gherkin
Given an operator has placed a key outside the accepted vocabulary in a configuration file
When that configuration is loaded
Then validation rejects it before consumers can use the configuration
And the failure identifies the file and offending key path
And when the key belongs in another declared section, the failure names that section
```

#### UC-CFG-UNKNOWN-2: An unknown nested overlay key blocks loading

#### UC-CFG-UNKNOWN-3: An unknown key in a named overlay mapping blocks loading

#### UC-CFG-UNKNOWN-4: An unknown key in an overlay list item blocks loading

#### UC-CFG-UNKNOWN-5: An unknown machine agent key is rejected

#### UC-CFG-UNKNOWN-6: An unknown machine-config key blocks loading

#### UC-CFG-UNKNOWN-7: Section-declared machine-config inputs remain valid

#### UC-CFG-UNKNOWN-8: Recognized stored configuration migrates before consumption

#### UC-CFG-UNKNOWN-9: Conflicting migration preserves the source and fails explicitly

#### UC-CFG-UNKNOWN-10: An interrupted move remains safely retryable

#### UC-CFG-UNKNOWN-11: Concurrent migrations preserve each other's updates

#### UC-CFG-UNKNOWN-12: A key placed in the wrong checkpoint registry names the registry it belongs to

### Cross-context references

- The config bounded context owns the accepted vocabulary and the resulting
  validation failure for every configuration surface.
- Runtime and adapter consumers receive only configuration that has passed its
  owning load boundary; they do not implement secondary unknown-key handling.
- Section-declared machine-config inputs are part of the machine-load contract
  in `local/projects/teleclaude/spec/feature/config/machine-config-load`.

## Allowed values

- Overlay keys declared by the owning Pydantic schema are accepted.
- Machine-config keys declared by the owning section model are accepted,
  including deliberate aliases and dynamic mapping members.
- Any other key is rejected; there is no warn-and-continue or silent-drop path.

## Known caveats

- Configuration migration and strict validation apply to each installation's
  own files. Loading on one installation does not depend on the version,
  reachability, or migration state of another installation.
- Dynamic mappings remain open only where their section model explicitly
  declares that input shape. An open mapping is not a general escape from
  unknown-key validation.
- A key whose value is an unresolved environment reference is still subject to
  the section vocabulary: an undeclared key is rejected whether or not its
  reference resolves.
