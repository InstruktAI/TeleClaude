---
description: Every same-named configuration file (global, project, person, company)
  declares its own tier, and resolution reads that declaration — the nearest anchoring
  tier declaration establishes the context root, a company declaration terminates
  context resolution with no context root, and git topology answers only where a project's
  shared state lives.
---

# Tier Declaration — Spec

## Required reads

- @docs/local/spec/domain/config.md

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
  ancestors means no context root: the docs read surfaces offer the caller's
  default read set with no landed home. Git plays no part in this question.
- **Project state** (projects only) — where a project's shared state lives.
  The git metadata at the project root decides: a primary checkout owns its
  own state; a linked worktree's shared state lives at the owning checkout;
  a project with no git checkout at its root fails loud. This question does
  not exist for the global, person, or company tiers — persons and companies
  commit into the home repository, not repositories of their own.

An established configuration file reaches the declared state through the
configuration migration list (`local/projects/teleclaude/spec/feature/config/document-migration`).
A document that has not passed the declaring migration obtains an absent tier
from the registries that define the tiers — the designated locations for the
home's own configuration, person, and company files, and the project registry
for project roots and the linked worktrees of those roots. A read supplies that tier in memory; a migration run or a
writer stores it. Every tier but project has a designated location, so a
document from before the declaring migration that declares no tier and that
those registries do not name can only be a project: a read gives it the project tier without registry
standing. A file the platform creates is written declared. A file past the
declaring migration that reaches loading without a valid declaration fails
wherever it sits, and a declaration naming an
unknown or tier-inconsistent kind is never replaced: it fails, and the file is
never loaded as another tier.

## Canonical fields

### Declaration shape

- Every same-named configuration file carries a `kind` field declaring which
  tier it is: `global`, `project`, `person`, or `company`. The machine
  configuration file is outside this contract — it carries a different
  filename and never participates in tier resolution.
- Every file references its editor schema, so an editor validates the file as
  its declared tier. The reference is relative and is fixed by the tier alone:
  a project configuration names its tier schema through the project root's
  machine-local schema link, and a home-tree file names the home's published
  schema directory from its designated location. The same file content
  therefore resolves on every machine that has published its schemas, with no
  network fetch and no path that means something different on another machine.
- The declaration is a declared, validated field of each tier's typed
  schema — never an unvalidated passenger key. The four values are one closed
  vocabulary, and each tier's schema accepts only its own value.
- The declaration and the schema reference are independent properties of a
  file: either is supplied or repaired without regard to the other. Only the
  declaration is load-bearing. Every write of a declared file carries its
  tier's schema reference, whether or not the writing machine holds that schema,
  so a file's committed content never depends on the state of the machine that
  wrote it.
- Whether an absent declaration may still be supplied is decided by the
  document's own version and nothing else. Only a document that has not passed
  the declaring migration is declared from the registries. A document past it is
  strict wherever it sits and on whichever machine reads it: a missing or
  misdeclared tier fails, and no declaration is restored. The schema reference
  carries no evidential weight, and neither its absence nor any edit other than
  the document's version makes a document eligible for a declaration again.

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

#### UC-CFG-WSD6: A file the registries name is declared by its migration

```
Given a same-named configuration file authored before tier declarations existed
And the tier registries name its location
When an agent loads that file
Then it loads as the tier the registries name
And the stored file is unchanged by the load
And once a migration run has stored it, the file carries that tier declaration
```

#### UC-CFG-WSD7: An unregistered file from before declarations loads as a project

```
Given a same-named configuration file authored before tier declarations existed
And the tier registries do not name its location
When that file is loaded
Then it loads as a project configuration without registry standing
And the stored file is unchanged by the load
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
<!-- planned-change:personal-assistant-project-creation -->
And company configuration composes alongside its member projects through their declared company membership
<!-- change:personal-assistant-project-creation -->
And company configuration composes alongside the projects that company owns
<!-- /planned-change:personal-assistant-project-creation -->
```

#### UC-CFG-WSD10: A declared file missing its schema reference gains it when stored

```
Given a same-named configuration file the tier registries name
And that file carries a valid tier declaration and no schema reference
When a migration run or an agent's configuration operation stores that file
Then the file carries its schema reference
And its existing tier declaration is left as it stands
```

#### UC-CFG-WSD11: A file that cannot be written still loads

```
Given a same-named configuration file the tier registries name
And that file is not writable by the invoking user
And that file carries no tier declaration and has not passed the declaring migration
When an agent loads that file
Then it loads as the tier the registries name
And the file is not modified
```

#### UC-CFG-WSD12: An unavailable registered root is migrated when it returns

```
Given a registered project root that is unavailable while a migration run executes
When that root becomes available and its configuration file is loaded
Then the file loads in its current shape
And a later migration run stores it at the current version
And its absence left every other root migrated by the earlier run
```

#### UC-CFG-WSD13: A schema reference is never written ahead of its schema

#### UC-CFG-WSD14: A declaration removed after migration is not restored

```
Given a configuration file stored past the declaring migration
And its tier declaration has been removed
And the tier registries name its location
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is restored
And the file is never loaded as any tier
```

#### UC-CFG-WSD15: Removing the schema reference too does not restore a declaration

```
Given a configuration file stored past the declaring migration
And it carries neither a tier declaration nor a schema reference
When that file is loaded
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is restored
```

#### UC-CFG-WSD16: A root registered later is declared by its registration

```
Given a project root whose configuration file was authored without a tier declaration
And the root is not yet registered
When an operator or agent registers that project
Then its configuration file is stored declaring the project tier
```

#### UC-CFG-WSD17: Moving a repository does not restore a declaration

```
Given a configuration file stored past the declaring migration whose tier declaration has been removed
And its repository is cloned to another machine
When that file is loaded there
Then loading fails with an error naming the file and the missing declaration
And no tier declaration is restored on that machine
```

#### UC-CFG-WSD18: Loading an undeclared file writes nothing

```
Given a same-named configuration file carrying no tier declaration
When that file is loaded
Then the stored file is byte-identical before and after the load, whether the load succeeds or fails
And no record of the load is kept that a later load consults
```

#### UC-CFG-WSD19: A written file carries its tier's schema reference on every machine

```
Given a declared configuration file of any tier
And the machine writing it may or may not hold that tier's published schema
When an agent's configuration operation writes that file
Then the file carries its tier's schema reference
And the written content is identical to what any other machine writes for the same document
```

### Cross-context references

- How a document reaches its current shape, including its declaration, is
  specified in `local/projects/teleclaude/spec/feature/config/document-migration`.
- The layered overlay composition this declaration dispatches is specified in
  `local/projects/teleclaude/spec/feature/config/layered-overlay-resolution.md`; the declared
  tier replaces path-shape detection as the dispatch signal.
- The tier model — designated locations, the project manifest, tier
  relationships, and read authorization — is consolidated in
  `general/design/configuration-tiers.md`; this contract delivers its
  declaration-driven resolution assertions.
- Directories with no anchoring declaration ancestor land in no home: the docs
  surfaces read the caller's default read set without one
  (`local/projects/teleclaude/design/architecture/context-selection`).

## Allowed values

- `kind`: `global`, `project`, `person`, `company`.

## Known caveats

- The declaration identifies what a configuration file is; it does not by
  itself verify that a person directory belongs to a registered person.
  Identity verification is owned by the identity context and person-tier
  work.
