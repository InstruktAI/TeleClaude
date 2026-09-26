---
description: How a configuration migration is written — one numbered step in one ordered list, a pure transform usable both in memory and when persisted, idempotent against whatever shape it finds, and never carrying a value out of a document before its destination holds it.
delivered_by: [config-migration-chain]
---

# Configuration Migrations — Policy

## Rules

- **One ordered list defines every configuration version.** A configuration
  migration is one numbered step in the single list that covers every
  configuration document kind. The step's number is the version it produces.
  Nothing else — no state file, no epoch, no completion record, no load-time
  repair, no startup step — records or performs configuration migration.
- **A delivered migration is immutable.** Once a numbered step has shipped, its
  number and its effect never change. A correction is a new step.
- **A migration is a pure transform of one document and its subject.** It reads
  only the document and what the registries say the document is, performs no
  I/O, and returns the next document. The same transform runs in memory when a
  registry-named document is read and when a migration run persists it, so the
  two can never disagree.
- **A migration is idempotent and assumes nothing about the shape it finds.** A
  document may reach a step already carrying some or all of its result — created
  at a newer version and edited by hand, or written by a newer installation. The
  step converges on its target whether or not the target is already present.
- **A migration that moves a value out of a document declares the move as a
  persisted effect.** The migration run delivers the value to its config-owned
  destination, idempotently, before the transform drops it from the document.
  A destination that already holds a different value is a conflict: the
  document keeps the value and its version, and the run reports the conflict.
  Where the value's final owner is another bounded context, the destination is a
  config-owned hand-off that owner imports from; a migration never writes
  another context's store.
- **A value in transit stays readable at its destination.** Until a document is
  stored past the migration that moves a value out of it, the config-owned
  destination's published reader also answers with the value that document still
  holds. The reader asks the migration list's published in-transit query, which
  answers from each migration's own definition of what it moves and only for
  documents below that migration; neither the query nor the reader writes.
  Where the destination already holds a different value for the same key, or two
  documents in transit hold different values for it, the reader answers with
  neither: a read never settles a conflict. Consumers outside the configuration
  context use the destination's published reader alone.
- **A step may retire config-owned records the list declares obsolete.** A retirement
  effect removes config-owned records that no current code reads. It is idempotent, never touches a configuration document, and runs on every
  migration run whatever any document's version, so an installation whose documents are
  already current still loses those records on its first run.
- **A migration that needs to know what a document is reads its subject.** The
  subject comes from the tier registries. A migration never derives a document's
  kind or instance from its path, and a document the registries do not name has
  no subject to supply.
- **A read without a subject does not migrate.** It leaves the document's
  stored shape for that reader's normal validation. A writer refuses to stamp
  an older subjectless document at the current version; registration supplies its
  subject before that write can proceed.
- **A shape change ships with its migration.** A change to what a configuration
  document may carry changes the owning model, the platform's generation of new
  documents, and the migration list together. A new document is written at the
  current version; a migration alone leaves new documents wrong, and a model
  change alone leaves stored documents unreadable.
- **A shape no machine still carries gets no migration.** Its keys fail as
  unknown wherever they reappear.

## Rationale

A registry-named document reaches the current shape along two paths — in memory
on every read, and on disk when a migration run or a writer persists it — and
only a pure, idempotent transform gives both paths the same answer. A transform with I/O
would make reading write, and a read path that writes lets every process that
reads configuration — including one running undelivered code — change the live
documents every other process depends on.

Registration bounds which older documents receive migrations. Inferring a
subject from a document's own tier would give an unregistered project the
capability subscriptions reserved for registered projects; stamping a
subjectless older document as current would instead skip the migration it
still needs. Reading its stored shape and refusing that write preserve both
boundaries until registration establishes the subject.

Idempotency is what makes stamping and replay safe together. Newly created
documents skip history while stored documents replay it, and hand edits or a
newer installation can put any part of a step's result in place first. A step
that asserts the shape it was written against fails on exactly the documents
that took the other path, and only when they are next migrated.

Moving a value before dropping it keeps a migration from being a deletion. The
in-memory read cannot write the destination, so the value survives in the
stored document until a run delivers it; a conflict keeps both copies because
neither can be chosen without judgment. A read drops the moved value from its
view of the document, and a run can fail, be delayed, or not yet have reached
the document, so a destination reader that consulted only the destination would
lose a value that is still on disk. Taking the value from the migration's own
definition keeps one statement of what moves. A reader that answered with either
side of a conflict would make, silently and on every read, the choice the run
leaves to judgment.

A retirement effect is keyed to the run rather than to a document's version because the
records it removes belong to no document: an installation can be current in every document
and still hold them.

One ordered list with the version in the document is what makes migration
progress a property of the data rather than of a machine. A copied, cloned, or
restored document carries its own position, and no separate record can drift
from it.

## Scope

Every configuration document the platform owns and every step in the
configuration migration list under `teleclaude/config/migrations/`.

## Enforcement

Reviewers apply these rules to every change that touches the configuration
migration list, a configuration model, or the generation of new configuration
documents.

## Exceptions

- None. A migration that cannot be made pure and idempotent is a migration whose
  target shape is wrong.

## See Also

- docs/project/spec/feature/config/document-migration.md — how documents reach the current shape and what a migration run reports.
- docs/project/policy/schema-and-migrations.md — the same discipline for the daemon database.
- ~/.teleclaude/docs/sdlc/policy/backward-compatibility-hygiene.md — why owned data migrates forward instead of branching.
