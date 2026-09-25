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

An established configuration file reaches the declared state through
advancement, which brings it to the current configuration contract when its
root is adopted and whenever that contract changes. An absent tier is obtained
from the registries that define the tiers — the designated locations for the
home's own configuration, person, and company files, and the project manifest
for project roots. A file those registries do not name is not advanced. A file
the platform creates is written declared. Loading never advances: a file that
reaches loading without a valid declaration fails wherever it sits, and a
declaration naming an unknown or tier-inconsistent kind is never advanced over:
it fails, and the file is never loaded as another tier.

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

### Advancement

- Advancement is an ordered set of steps. Each step recognizes one legacy
  shape in a file and transforms it: an absent tier declaration, an absent or
  non-canonical schema reference, a key the contract has retired, and, in a
  project declaration, a capability left without a value
  (`project/spec/feature/config/project-capability-manifest`). The steps are
  the only record of what the current shape is, and the file itself shows which
  shape it is in. Advancement keeps no other record: no eligible set, no
  completion record, and nothing that distinguishes a root adopted early from
  one adopted late.
- A file in the current shape matches no step and is not written, so advancing
  it again changes nothing. A file that matches is written once, atomically, and
  keeps its comments and the order of the keys that remain.
- An absent tier comes from the registries: the designated location of the
  home's own configuration, person, or company file, or the project manifest's
  entry for a project root. A present declaration is never rewritten, and one
  that contradicts the registries leaves the file as stored.
- A key no step recognizes is never migrated, removed, or guessed at; loading
  keeps rejecting it by name.
- Advancement runs at two boundaries only. Adopting a root advances that root.
  A change to the configuration contract or its steps, once it reaches canonical
  main, advances every root the registries name through post-commit maintenance
  (`project/spec/feature/integration/post-commit-maintenance`). Loading,
  context resolution, and daemon start never advance.
- A root that is unavailable, unreadable, or unwritable when advancement runs is
  reported for that root and skipped; every other root is still advanced.

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

#### UC-CFG-WSD6: A file the registries name is advanced to its declaration

```
Given a same-named configuration file carrying no tier declaration
And the tier registries name its root
When advancement runs over that root
Then the file carries the tier declaration the registries give its root
And advancing it again leaves the file byte-identical
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
When that file is advanced
Then the file is advanced to carry its schema reference
And its existing tier declaration is left as it stands
```

#### UC-CFG-WSD11: A file that cannot be written is reported and left failing its load

```
Given a same-named configuration file the tier registries name
And that file is not writable by the invoking user
And that file carries no tier declaration
When advancement runs over every named root
Then that root is reported as not advanced, naming the file
And every other named root is still advanced
And loading that file fails with an error naming the file and the declaration it needs
```

#### UC-CFG-WSD12: An unavailable registered root is advanced by a later run

```
Given a registered project root that was unavailable at an earlier advancement run
And its configuration file carries no tier declaration
When a later advancement run finds the root available
Then its file carries its tier declaration
And no record of the earlier run was needed to reach that outcome
```

#### UC-CFG-WSD13: A schema reference is never written ahead of its schema

#### UC-CFG-WSD14:

#### UC-CFG-WSD15:

#### UC-CFG-WSD16:

#### UC-CFG-WSD17:

#### UC-CFG-WSD18:

#### UC-CFG-WSD19: A written file carries its tier's schema reference on every machine

```
Given a declared configuration file of any tier
And the machine writing it may or may not hold that tier's published schema
When an agent's configuration operation writes that file
Then the file carries its tier's schema reference
And the written content is identical to what any other machine writes for the same document
```

#### UC-CFG-WSD20: Loading never advances a file

```
Given a same-named configuration file carrying no tier declaration
And the tier registries name its root
When that file is loaded or its root is resolved as an invocation context
Then loading fails with an error naming the file and the missing declaration
And the file is byte-identical after the failed load
```

#### UC-CFG-WSD21: Adopting a root advances that root

```
Given a repository whose configuration file carries no tier declaration
And its root is not yet in the project manifest
When an agent adopts that repository as a project
Then its configuration file carries the project declaration before adoption reads the declaration
And no other root's configuration file is written by that adoption
```

#### UC-CFG-WSD22: A configuration contract change advances every named root

```
Given canonical main advances with a commit that changes the configuration contract or its advancement steps
And the tier registries name roots whose files are in a legacy shape
When post-commit maintenance runs for that commit
Then every named root's file is brought to the current shape
And every named root's file already in the current shape is left byte-identical
```

#### UC-CFG-WSD23: A retired key is removed without losing the file's comments

```
Given a named root's configuration file carrying a key the contract has retired
And that file carries comments and other keys around the retired key
When advancement runs over that root
Then the retired key is absent from the file
And every comment in the file is still present
And the remaining keys keep their order
```

#### UC-CFG-WSD24: An unrecognized key is never advanced over

```
Given a named root's configuration file carrying a key that neither the contract nor any advancement step recognizes
When advancement runs over that root
Then that key is still present, unchanged
And loading the file fails with an error naming that key
```

#### UC-CFG-WSD25: A declaration contradicting the registries is left as stored

```
Given the project manifest names a root whose configuration file declares a tier other than project
When advancement runs over that root
Then that root is reported as contradicting its registry entry
And its configuration file is byte-identical
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
