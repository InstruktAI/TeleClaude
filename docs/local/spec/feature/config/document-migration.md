---
description: Every configuration document carries the version of its shape; reads
  bring an older document to the current shape in memory without writing, and only
  a migration run or a writer persists the migrated shape — a migration run commits
  it in the document's own repository.
---

# Document Migration — Spec

## What it is

Configuration documents — the machine configuration and every same-named
global, person, company, and project configuration — are owned data. Their
stored shape moves forward through one ordered list of numbered migrations, the
way the daemon database moves forward through its migrations. Each migration
takes a document one version forward. Every document states which version it
is at, and the ordered list is the only definition of what each version means:
no other record of migration progress exists anywhere.

A document created by the platform is written at the current version. It is
stamped, never replayed.

Current-schema metadata, document creation, published validation schemas and
reconciliation expose the same version authority. Serialization preserves the
version established with a document's validated shape. Source authoring and
instance reconciliation follow
`local/projects/teleclaude/policy/configuration-migrations`.

Successful read-time adaptation emits no per-read migration outcome at
production log levels. Explicit reconciliation retains its per-document
outcomes and failure diagnostics; routine read observations follow
`sdlc/policy/observability`.

Reading never writes. Every configuration loader visits the same ordered list
in memory before validation. The tier registries supply a subject when they
name the document, so every pending step for that subject brings it to the
current shape. Otherwise a valid tier declaration supplies a read-only
subject: tier-wide shape changes still apply, while a step whose result
depends on registration or an instance waits only when the resulting view is
valid under the current model. A declared unregistered project therefore
loads with recognized retired fields removed and omitted capabilities
unsubscribed; it receives no registered project's grandfathered values. An
overlay from before the declaring migration that declares no tier and that no
registry names loads the
same way as a declared unregistered project, because project is the only tier
not located by a registry. Any other document with neither a registry subject nor
a valid tier declaration fails loading. An unsupported key in the resulting view fails the load. A document
stating a version newer than the installation knows fails the load naming both
versions.

The migrated shape is persisted in exactly two ways:

- **A migration run.** Canonical-main maintenance runs one when an activation
  changes the migration list, inside that activation's stopped-daemon window
  (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`),
  over every document
  the tier registries name: the machine configuration, the home's global
  configuration, every person and company configuration at its designated
  location, and every registered project root. Registering a project runs one
  for the root it adds, and installation runs one over the configuration it has
  seeded. A document outside the registries is never migrated by a run; it
  enters through registration.

- **A writer.** A platform operation that changes a registry-named existing
  document first persists that document's pending migrations, then applies its
  own change to the current shape. A write therefore never records an older
  shape at the current version, and never drops a value a migration still has
  to move.

A migration run never stores a document at a version a running daemon cannot
read (`local/projects/teleclaude/policy/daemon-availability`). A maintenance
run that replaces the daemon performs its migration run while the daemon is
stopped. Any other migration run that maintenance or installation performs
reads, before it writes, the migration reach the running daemon reports. A daemon that
reports a lower reach, reports none, or listens without answering within a
bounded wait withholds the whole run: no document is stored, no retirement
runs, and every document the run covers, other than one whose source the run
retains, is recorded as withheld, naming the daemon's reach and the current
version. When no daemon listens, the run
proceeds. Installation continues past a withheld run, reading the documents as
stored through the in-memory migration, and a later migration run stores them.

The installed release checkout's project declaration is retained source under
`local/projects/teleclaude/spec/feature/reconciliation/release-checkout`.
A migration run evaluates that declaration through the ordinary read-time
migration and validation rules without retiring state, transferring values,
rewriting the document or creating a source commit. Its outcome distinguishes
retained source evaluated in memory from a stored schema migration. A failed
read or unsupported shape is a failed outcome. Other registered documents retain
the persistence rules above; an explicit configuration writer retains its own
write contract.

<!-- planned-change:lean-git-commit-scope -->

A migration run commits what it persists. A document tracked in a git
repository that had no uncommitted changes gets one migration commit in that
repository, containing that document alone. A document that already carried
uncommitted changes is migrated in place and left for whoever owns those
changes; its pending edits are preserved and nothing is committed on their
behalf. A document whose commit is refused is restored to its committed
content. Untracked documents are written without a commit.
<!-- change:lean-git-commit-scope -->

A migration run commits what it persists outside the TeleClaude home. A
document tracked in a git repository that had no uncommitted changes gets one migration commit in that
repository, containing that document alone. A document that already carried
uncommitted changes is migrated in place and left for whoever owns those
changes; its pending edits are preserved and nothing is committed on their
behalf. A document whose commit is refused is restored to its committed
content. Untracked documents are written without a commit.
In the TeleClaude home a migration run commits nothing: the home snapshot
records what it persisted
(`local/projects/teleclaude/spec/feature/reconciliation/home-repository`).
<!-- /planned-change:lean-git-commit-scope -->

A migration that moves a value out of a document delivers it to its
config-owned destination before the document drops it. Where the value's final
owner is another bounded context, the destination is a config-owned hand-off
that the owner imports from; the importing owner's contract governs everything
after the hand-off. Until a document is stored past the migration that moves a
value out of it, the config-owned destination's published reader also finds the
value the document still holds, through the migration list's in-transit query,
reading without writing.

Every migration run also removes the config-owned records the list declares obsolete,
whatever the documents' versions, so the first run
on an installation removes them even when every document is already current.

If the destination already holds a conflicting value, the migration leaves both the source value and existing destination unchanged and records a destination-conflict failure.

The authoring rules every migration obeys are
`local/projects/teleclaude/policy/configuration-migrations`.

## Canonical fields

- **Version.** A non-negative integer each document carries at its top level.
  A document with no version is at version zero. The current version is the
  number of the last migration in the list.
- **Subject.** The document's kind (computer, global, person, company, or
  project), its instance where the registries know one, and whether the
  registries name it. The document at the root of a linked worktree of a
  registered project root has that project's registry subject. A valid tier
  declaration supplies a read-only subject when no registry names the
  document; it supplies no instance or registration standing. A migration
  reads the subject, never the document's location.

- **Migration start signal.** Before a run changes a document — before its
  pending carries, upcasts or replacement — it signals that a migration is
  starting for that document, whatever triggers the run: installation, a
  writer or maintenance. The signal names the document and carries no outcome;
  the installation counts it as a change
  (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).

- **Migration run outcome.** One structured record per document naming the
  document, its subject, the version found, the version reached, and one
  outcome: current, migrated and committed, migrated and left uncommitted,
  written untracked, restored after a refused commit, withheld for the running
  daemon's reach, or failed with a reason.
  A document refused because it breaks a declared field relationship fails
  with that reason and carries the relationship's message, which the run's
  failure diagnostic shows. One document's failure never stops the run over
  the others; a run with any failed document ends failed. A withheld run ends
  unsuccessful and is distinguishable from a failed one.

### Use cases

#### UC-CFG-MIG-1: An operator can keep using an older configuration safely

```gherkin
Given an operator's saved configuration is from an older supported version
When TeleClaude reads it for an operation
Then the operation uses the current configuration shape
And the saved document remains unchanged
```

#### UC-CFG-MIG-2: An operator can diagnose a configuration newer than the installation

```gherkin
Given an operator uses a configuration written by a newer TeleClaude version
When the installed version tries to load it
Then loading is refused with the document and both schema versions identified
And the saved document is unchanged
```

#### UC-CFG-MIG-3: A change to the migration list persists every registered document while the daemon is stopped

#### UC-CFG-MIG-4: A clean tracked document gets one migration commit in its own repository

#### UC-CFG-MIG-5: A document with pending edits is migrated without committing them

#### UC-CFG-MIG-6: A refused migration commit leaves the document as it was

#### UC-CFG-MIG-7: Registration migrates the root it adds

#### UC-CFG-MIG-8: A write never loses a value still in transit

```gherkin
Scenario: Keep the operator's data when changing configuration
  Given an operator changes a configuration that still holds a value being moved to its destination
  When the configuration change is saved
  Then the value is present in its destination and the saved configuration includes the requested change

Scenario: Preserve both values when migration finds a destination conflict
  Given the destination already contains a different value for the migrating data
  When the configuration migration reaches that value
  Then the source value and existing destination remain unchanged
  And the migration outcome reports the conflict
```

#### UC-CFG-MIG-9: A moved value reaches its destination before the document drops it

#### UC-CFG-MIG-10: Installation brings its seeded configuration to the current version

```gherkin
Scenario: Install with a configuration from an older supported version
  Given an operator installs or upgrades TeleClaude with saved configuration
  When installation migrates and validates the configuration
  Then the saved configuration is available in the current shape for the installation

Scenario: Stop installation when a covered configuration cannot be migrated
  Given a configuration covered by installation migration fails to migrate
  When the migration step ends
  Then installation names the document and failure reason
  And it stops before validating configuration
```

#### UC-CFG-MIG-11: A migrated document migrates no further

#### UC-CFG-MIG-12: The first migration run removes retired migration records

#### UC-CFG-MIG-13: A value in transit stays reachable until its migration is stored

#### UC-CFG-MIG-14: A writer does not stamp an unregistered older document as current

#### UC-CFG-MIG-15: A declared unregistered project loads with tier-wide migrations

#### UC-CFG-MIG-16: A failed installation migration names what failed

#### UC-CFG-MIG-17: An operator migrates configuration without rewriting the installed release declaration

```gherkin
Scenario: A readable installed declaration is retained
  Given an operator runs configuration migration from an installed release checkout whose tracked project declaration has an older readable schema
  And another registered home has a configuration document requiring migration
  When the installation runs configuration migration maintenance
  Then the installed declaration loads in its current shape without changing its stored bytes
  And the installed checkout still selects the same release commit with no migration commit
  And the other home receives its ordinary persisted migration outcome
  And the installed declaration outcome states that its source was retained and evaluated in memory

Scenario Outline: A retained declaration receives ordinary validation
  Given an installed release declaration containing <invalid_shape>
  And an ordinary configuration load refuses that declaration
  When the installation runs configuration migration maintenance
  Then that document has a failed outcome with its validation reason
  And its stored bytes and selected release commit remain unchanged
  And the run still evaluates its other registered documents

  Examples:
    | invalid_shape                  |
    | an undeclared key              |
    | a value of an unsupported type |
    | an invalid enumerated value    |
    | an invalid field relationship  |
```

#### UC-CFG-MIG-18: Repeated compatible reads stay quiet

#### UC-CFG-MIG-19: A current document keeps its version when written

#### UC-CFG-MIG-20: A migration run never stores a version the running daemon cannot read

### Cross-context references

- Commit-boundary maintenance selects and runs the migration run as one of its
  owed actions: `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`.
- Which files are same-named tier documents and how their declared tier is
  supplied: `local/projects/teleclaude/spec/feature/config/tier-declaration`.
- Registration writes the project registry:
  `local/projects/teleclaude/spec/feature/config/project-registry`.
- The retired Discord provider identifiers leave the machine configuration
  through the config-owned hand-off; their import is
  `local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state` UC-DARS-2.

## Known caveats

- A declared person file outside the designated person home that lacks its
  identity cannot obtain one from a read: the registries supply no person
  instance there, so normal person validation refuses it. This is an invalid
  file, rather than a recognized older shape at a registered person home.
- A tracked project document shared by several machines receives a migration
  commit from each machine that runs the migration. The commits carry identical
  content, so they merge without conflict.
- Installation-level migrations under `migrations/` are a separate mechanism
  governed by the deployment migration runner, and are not part of this list.
- The daemon's migration reach guards migration runs only. A writer stores the
  document it changes at the current version without reading that reach, and
  installation's agent-settings stage is such a writer of the machine
  configuration, running before installation's migration run. An installation
  run while an older daemon serves can therefore leave that daemon refusing its
  configuration until it is replaced.
