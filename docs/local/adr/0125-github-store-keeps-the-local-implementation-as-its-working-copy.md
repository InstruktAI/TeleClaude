---
visibility: internal
number: 0125
date: 2026-10-23
description: The GitHub workflow-store adapter serves the port through the existing local implementation as a disposable working copy and writes every change to GitHub before the local commit completes, instead of reimplementing the port's operations against the GitHub API.
---

# GitHub Store Keeps the Local Implementation as Its Working Copy — ADR

## Context

A project may select GitHub as its workflow store, keeping its work items in
its own repository instead of the local todo database, so that a reader of the
repository can follow each item without TeleClaude. The workflow machine reaches
the store only through the workflow-store port, and it must run unchanged on
either backend.

The port has about eighty operations. The local adapter implements them over
SQLite in roughly eight thousand lines, and those lines are not storage alone:
removal refusals, holder transitions, group membership checks, dependency
validation, delivery provenance, stamp evidence binding and show assembly are
decided inside them. The port also relies on properties SQLite supplies and the
GitHub API does not: an atomic update of state together with artifact
evidence, a compare-and-clear of the active runner, transactions that serialize
every process on a computer, and synchronous calls that the daemon makes
inside its event loop. GitHub supports no conditional writes, and every read
is a network round trip.

## Decision

The GitHub adapter serves the port through the existing local implementation,
opened on a working copy that belongs to the GitHub-backed project and is never
its system of record. Every transaction that changes the working copy writes
the changed items' records and new content to GitHub before the local commit
completes; a GitHub write that fails aborts the local commit. Reads are served
from the working copy. The working copy is rebuilt from GitHub when it is
absent and refreshed from GitHub for changes made elsewhere, trusting only
content the platform's App authored.

## Consequences

- Every domain rule keeps its single owner in the local implementation. The
  GitHub adapter owns only the mapping between the working copy and GitHub:
  encoding, the push at commit, rebuild, refresh and conflict refusal.
- Atomic, compare-and-clear and synchronous operations keep their local
  semantics, and processes on one computer stay serialized by the working
  copy's transactions, as on the local backend.
- A write holds the working copy's write lock for the duration of its GitHub
  round trips, so writes on a GitHub-backed project are slower than local
  writes and contend for longer.
- Writes from two computers to the same item are detected by a record revision
  check before each push, but the check and the write are not atomic on
  GitHub; two pushes landing inside that window can lose one.
- A lost or deleted working copy loses nothing, and a computer that never held
  one reaches the project's full state by rebuilding it.
- Any change to the local implementation's storage reaches the GitHub record
  only through the commit-time push, so a write path that commits outside the
  instrumented channels would bypass GitHub. The adapter keeps every write
  channel of its working copy instrumented.

## Alternatives Considered

- **Reimplement every port operation natively against GitHub.** Rejected: it
  places a second copy of every domain rule the local implementation decides
  into the GitHub adapter, where the two drift, and it has to emulate atomicity,
  compare-and-clear and cross-process serialization over an API that offers
  none of them, while every synchronous daemon read becomes a network call.
- **Commit locally first and push to GitHub afterwards.** Rejected: GitHub then
  lags the working copy, and a crash or failed push leaves changes that exist
  only locally, so the repository would no longer be the project's record.
- **Mirror the local backend to GitHub as a reflection.** Rejected: the local
  database stays the system of record, which is the outcome the GitHub store
  exists to replace.
