---
description: Machine installation exposes repository-owned runtime support through safe, idempotent links from the TeleClaude home.
delivered_by:
  - retire-docs-watcher
---

# Shared Runtime Installation — Spec

## What it is

Machine installation exposes repository-owned runtime support from the
canonical TeleClaude checkout at stable paths under the TeleClaude home. The
checkout remains the source of truth; publication does not copy or regenerate
these resources.

The configuration-schema directory is one such resource. Installation links
the home schema path to the canonical checkout and migrates only the legacy
generated directory shape that the former distribution path produced.

## Canonical fields

- **Source.** The canonical checkout's repository-owned runtime-support
  directory.
- **Target.** The corresponding stable path under the TeleClaude home.
- **Idempotence.** An already-correct symlink is unchanged.
- **Legacy migration.** A real directory is replaceable only when every entry
  belongs to the known generated schema set. A conflicting type or unexpected
  entry fails installation and remains untouched.

### Use cases

#### UC-SRI1: Installation preserves an already-correct schema link

```gherkin
Given the TeleClaude home schema path is a symlink to the canonical checkout schema directory
When an agent runs machine installation
Then the schema link is unchanged
And installation completes successfully
```

#### UC-SRI2: Installation replaces the known legacy generated schema directory

```gherkin
Given the TeleClaude home schema path is a real directory containing only the generated schema files produced by the former distribution path
When an agent runs machine installation
Then that legacy directory is removed
And the home schema path becomes a symlink to the canonical checkout schema directory
And installation completes successfully
```

#### UC-SRI3: Installation preserves unexpected schema content and fails

```gherkin
Given the TeleClaude home schema path conflicts with the required symlink
And the target contains an entry outside the known legacy generated schema set
When an agent runs machine installation
Then installation identifies the conflicting target
And no target content is removed
And installation exits non-zero
```

## Known caveats

- The repository's schema-generation step remains responsible for refreshing
  the canonical source files. This contract owns only installation of their
  stable home path.
