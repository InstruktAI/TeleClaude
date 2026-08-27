---
description: "Every same-named configuration file (global, project, person, company) declares its own tier, and resolution reads that declaration — the nearest anchoring tier declaration establishes the context root, a company declaration terminates context resolution with no context root, and git topology answers only where a project's shared state lives."
delivered_by:
  - config-kind-declaration
---

# Tier Declaration — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every same-named configuration file states what it is: a tier declaration
inside the file identifies it as the global, project, person, or company
configuration, and an editor schema reference lets editors validate the file
as its declared tier. Meaning comes from the file, never from where it sits.
The company file participates in self-identification only: its declaration
marks a company registry entry, not a root anything resolves against, and a
company configuration reaches composition through its member projects' declared
company membership, never through its own declaration.

Resolution reads declarations instead of inferring from location, and it
answers two separate questions:

- **Context** — which configuration and documentation context applies to an
  invocation. The nearest ancestor directory carrying an anchoring tier
  declaration (global, project, or person) is the context root, and that
  file's declared tier governs the invocation. A company declaration is
  never a context root: resolution recognizes it and terminates without
  anchoring, so invocation from within a company folder behaves as
  invocation with no context root. No anchoring declaration among the
  ancestors means no context root: read surfaces proceed with global-scope
  information only. Git plays no part in this question.
- **Project state** (projects only) — where a project's shared state lives.
  The git metadata at the project root decides: a primary checkout owns its
  own state; a linked worktree's shared state lives at the owning checkout;
  a project with no git checkout at its root fails loud. This question does
  not exist for the global, person, or company tiers — persons and companies
  commit into the home repository, not repositories of their own.

A sanctioned one-time transition brings existing configuration files to the
declared state; afterwards loading is strict — a same-named configuration file
without a valid declaration is an error and is never loaded as another tier.

## Canonical fields

### Declaration shape

- Every same-named configuration file carries a `kind` field declaring which
  tier it is: `global`, `project`, `person`, or `company`. The machine
  configuration file is outside this contract — it carries a different
  filename and never participates in tier resolution.
- Every file references its published editor schema, so an editor validates
  the file as its declared tier. The schema files are published by this
  repository alongside the existing MCP-registry schema.
- The declaration is a declared, validated field of each tier's typed
  schema — never an unvalidated passenger key.

### Use cases

#### UC-CFG-WSD1: Declared tier governs, not location

```
Given a root directory whose teleclaude.yml declares itself a person configuration
And the directory does not sit under any conventional person-folder location
When an agent loads configuration for that root
Then the file is loaded as a person overlay
And the invocation resolves to the person tier at that root
```

#### UC-CFG-WSD2: Nearest anchoring tier declaration is the context root

```
Given a human or agent invokes the CLI from a subdirectory below an anchoring tier declaration
When the context is resolved
Then the nearest ancestor directory carrying an anchoring tier declaration is the context root
And that file's declared tier governs the invocation
```

#### UC-CFG-WSD3: A person context needs no git checkout

```
Given a person directory whose configuration declares itself a person configuration
And no git checkout exists at or above that directory
When an agent invokes a read surface such as the docs index from within it
Then the invocation resolves to the person tier
And no failure about a missing project checkout occurs
```

#### UC-CFG-WSD4: Worktree shared state resolves to the owning checkout

```
Given a linked git worktree of an owning project checkout
When an agent resolves shared project state such as the todo store from within the worktree
Then the shared state root is the owning checkout, never the worktree itself
```

#### UC-CFG-WSD5: A project without git fails loud on shared state

```
Given a root whose configuration declares itself a project configuration
And no git metadata exists at that root
When shared project state is resolved for that project
Then resolution fails with a clear error naming the project root
```

#### UC-CFG-WSD6: The transition brings existing files to the declared state

```
Given existing same-named configuration files authored before tier declarations existed
When the operator runs the sanctioned transition
Then each of those files receives its correct tier declaration
And repeating the transition leaves already-declared files unchanged
```

#### UC-CFG-WSD7: Post-transition loading is strict

```
Given the sanctioned transition has completed
And a same-named configuration file carries no tier declaration
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
```

#### UC-CFG-WSD8: An invalid declaration never loads as another tier

```
Given a same-named configuration file whose declaration names an unknown or tier-inconsistent kind
When that file is loaded
Then loading fails with a clear error naming the file and the invalid declaration
And the file is never loaded as another configuration tier
```

#### UC-CFG-WSD9: A company configuration is recognized, never misclassified

```
Given a company configuration file declaring itself a company configuration
When context resolution encounters it
Then it is recognized as company configuration
And no context root is anchored at the company folder
And it is never treated as an anchoring tier
And invocation from within the company folder behaves as invocation with no context root
And company configuration composes alongside its member projects through their declared company membership
```

### Cross-context references

- The layered overlay composition this declaration dispatches is specified in
  `project/spec/feature/config/layered-overlay-resolution.md`; the declared
  tier replaces path-shape detection as the dispatch signal.
- The tier model — designated locations, the project manifest, tier
  relationships, and read authorization — is consolidated in
  `general/design/configuration-tiers.md`; this contract delivers its
  declaration-driven resolution assertions.
- Directories with no anchoring declaration ancestor keep the delivered
  global-only read behavior of the docs surfaces.

## Allowed values

- `kind`: `global`, `project`, `person`, `company`.

## Known caveats

- The declaration identifies what a configuration file is; it does not by
  itself verify that a person directory belongs to a registered person.
  Identity verification is owned by the identity context and person-tier
  work.
