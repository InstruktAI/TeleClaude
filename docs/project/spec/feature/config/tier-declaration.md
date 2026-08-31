---
description: Every same-named configuration file (global, project, person, company)
  declares its own tier, and resolution reads that declaration — the nearest anchoring
  tier declaration establishes the context root, a company declaration terminates
  context resolution with no context root, and git topology answers only where a project's
  shared state lives.
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

An established configuration file reaches the declared state by being advanced
before it is loaded, with an absent tier obtained from the registries that
define the tiers — the designated locations for the home's own configuration,
person, and company files, and the project manifest for project roots. A file
those registries do not name is not advanced. A file the platform creates is
written declared. A file that reaches loading without a valid declaration fails
wherever it sits, and a declaration naming an unknown or tier-inconsistent kind
is never advanced over: it fails, and the file is never loaded as another
tier.

## Canonical fields

### Declaration shape

- Every same-named configuration file carries a `kind` field declaring which
  tier it is: `global`, `project`, `person`, or `company`. The machine
  configuration file is outside this contract — it carries a different
  filename and never participates in tier resolution.
- Every file references its editor schema, so an editor validates the file as
  its declared tier. The reference names a schema in the file's own tree — a
  project configuration names a sibling at its project root, a home-tree file
  names the home's copy — so it resolves from every checkout of the file that
  carries it, with no network fetch and no path that means something different
  on another machine.
- The declaration is a declared, validated field of each tier's typed
  schema — never an unvalidated passenger key. The four values are one closed
  vocabulary, and each tier's schema accepts only its own value.
- The declaration and the schema reference are independent properties of a
  file: either is supplied or repaired without regard to the other. Only the
  declaration is load-bearing, and a file never references a schema that is not
  in place.
- Advancement runs against an epoch, opened only by the versioned installation
  upgrade that introduces it and never by a load. Its eligible set is captured
  from the registries when it opens and includes manifest entries that are
  unavailable at that moment. Only a root in that set is ever advanced, and
  completion is recorded per root. With no open epoch every root is strict, as
  is any root outside the set and any root already recorded complete: a file there missing or
  misdeclaring its tier fails, that failure is settled before any repair is
  attempted, and no declaration is restored. The schema reference carries no
  evidential weight and its absence never makes a root eligible again.

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

#### UC-CFG-WSD6: A file the registries name is advanced before it is loaded

```
Given a same-named configuration file authored before tier declarations existed
And its root is in the advancement epoch's eligible set and not yet complete
When that file is loaded
Then it is advanced to carry its correct tier declaration before the load reads it
And its root is recorded complete
And loading it again leaves the file unchanged
```

#### UC-CFG-WSD7: An undeclared file fails wherever it sits

```
Given a same-named configuration file carrying no tier declaration
And the tier registries do not name its location
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier is derived from the file's location
And the file is never loaded as any tier
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

#### UC-CFG-WSD10: A declared file missing its schema reference is repaired

```
Given a same-named configuration file the tier registries name
And that file carries a valid tier declaration and no schema reference
And that file's schema is in place
When that file is advanced
Then the file is advanced to carry its schema reference
And its existing tier declaration is left as it stands
```

#### UC-CFG-WSD11: A file that cannot be written fails its own load

```
Given a same-named configuration file the tier registries name
And that file is not writable by the invoking user
And that file carries no tier declaration
When that file is loaded
Then loading fails with an error naming the file and the declaration it needs
And the file is never loaded as any tier
```

#### UC-CFG-WSD12: An unavailable registered root is advanced when it returns

```
Given a registered project root that is unavailable when the advancement epoch opens
When that root becomes available and its configuration file is loaded
Then the root was carried in the eligible set as pending rather than omitted
And that file is advanced before the load reads it
And an unwritable file at one root leaves every other root resolving
```

#### UC-CFG-WSD13: A schema reference is never written ahead of its schema

```
Given a configuration file whose schema is not yet in place at its root
When that file is advanced
Then its tier declaration is written
And no schema reference is written
And the schema reference is written by a later advance once the schema is in place
```

#### UC-CFG-WSD14: A declaration removed after advancement is not restored

```
Given a root recorded complete
And its configuration file's tier declaration has been removed
And the tier registries name that root
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And the failure is reached before any repair is attempted
And no tier declaration is restored
And the file is never loaded as any tier
```

#### UC-CFG-WSD15: Removing the schema reference too does not reopen advancement

```
Given a root recorded complete
And its configuration file carries neither a tier declaration nor a schema reference
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is restored
And editing the file does not return its root to the eligible state
```

#### UC-CFG-WSD16: A root outside the eligible set is strict from the start

```
Given a project root registered after the advancement epoch opened
And its configuration file carries no tier declaration
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is supplied from the root's location
```

#### UC-CFG-WSD17: Moving a repository does not reopen advancement

```
Given a configuration file whose tier declaration has been removed
And its repository is cloned to a machine where its root is not in an eligible set
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is restored on that machine
```

#### UC-CFG-WSD18: No open epoch means every root is strict

```
Given an installation with no open advancement epoch
And a same-named configuration file carrying no tier declaration
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no epoch is opened by the load
And no tier declaration is supplied from the file's location
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
