---
description: Connection-qualified workflow persistence observations for attributing transaction contention without changing persistence behavior.
visibility: internal
delivered_by:
  - enable-workflow-lock-attribution
---

# Transaction Observation — Spec

## What it is

The workflow context exposes persistence observations that let an investigator
correlate a failed or waiting workflow operation with overlapping transactions
on the same local store. The observation spans raw bootstrap migrations and
synchronous and asynchronous runtime connections, including connections in
the same process.

This contract defines diagnostic evidence, not a determination of the cause of
any incident. Workflow persistence and adapter boundaries remain owned by
`local/projects/teleclaude/design/architecture/workflow-store`; logging follows
`sdlc/policy/observability` and its Python realization in
`sdlc/policy/python/logging`.

## Canonical fields

### Correlation and coverage

An observation identifies the store through an opaque canonical database
identity shared by its bootstrap and runtime connections. Distinct processes,
process incarnations, connections and transaction attempts remain
distinguishable. Linked worktrees resolving the same store share its database
identity. Reused connection objects do not merge separate transaction attempts.

Each observation carries its application boundary: the workflow operation or
bootstrap migration executing it, and an existing request or durable-operation
identity when one is available. Bootstrap that precedes request admission
remains attributable to its process and migration without inventing a durable
operation. Missing correlation is explicit.

The workflow adapter owns the attribution contract. Shared connection
infrastructure supplies connection observations through an explicit seam;
workflow consumers continue using the existing store contract.

### Transaction evidence

An enabled diagnostic window retains timestamped evidence of write acquisition
attempts, confirmed acquisition where observable, transaction completion and
release, and failed acquisition or persistence. Completion distinguishes commit,
rollback and connection closure. An interrupted or incomplete observation
remains visibly incomplete.

Records distinguish an attempted or deferred transaction from a confirmed
writer. They carry the available SQLite result and extended result code on
failure, preserving unavailable values as unknown. They expose enough ordering
and elapsed-time information to compare an operation's wait with transactions
on the same database across connections and processes.

The evidence supports identifying overlapping candidate holders and the
application paths that produced them. It claims a blocking relationship only
when the observations establish it. A failed writer, open file descriptor,
nearby timestamp or successful later retry does not by itself identify a
holder.

### Observation operation

The diagnostic window has an explicit activation and deactivation path through
the supported logging configuration. Activation precedes the operation being
observed. Detailed transaction evidence follows the owning logging policy's
level and aggregation contract; ordinary failure records retain the available
connection and operation correlation. The implementation declares its
observation coverage and any gaps, including incomplete records after process
termination.

Observation remains outside the observed database's write path: emitting or
retaining a diagnostic record performs no write to that database. Capture is
bounded in memory and output, and any resulting loss of correlation evidence
is explicit. Its implementation and independent review account for overhead
and effects on locking.

Diagnostic content consists of correlation identities, static application
boundary labels, timing and typed outcomes. SQL statement text, bound parameter
values and record contents are outside this diagnostic surface. Database
identity does not disclose a filesystem location. Sensitive-data handling
follows `sdlc/policy/observability`.

### Persistence neutrality

Enabling observation preserves the observed operation's result, exception,
cancellation and transaction boundaries. Busy handling, timeouts, retries,
transaction ordering and migration behavior remain the persistence owner's
existing contract. Diagnostic emission failures cannot replace the original
operation outcome and remain observable through the logging boundary without
recursing into the observed store.

## Known caveats

The surface observes instrumented workflow connections. Transactions outside
that coverage remain unattributed unless separate evidence identifies them.
An observation window cannot reconstruct transaction identities or intervals
that preceded activation.
