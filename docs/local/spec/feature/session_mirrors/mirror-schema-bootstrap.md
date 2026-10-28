---
description: "Idempotent bootstrap for the mirror store's schema — mirrors, tombstones, the full-text index, and the index-sync triggers — plus per-process compatibility migrations that keep older databases readable by newer code."
visibility: 'public'
---

# Mirror Schema Bootstrap — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

The session_mirrors service owns conversation mirrors, session attribution,
conversation-owned source observations and messages, negative file observations,
and a full-text index. Each conversation retains its source observations
independently when another session records the same native source. Shrink
refusals and unreprojectable observations belong to that conversation's source;
tombstones describe the native file. Sync triggers keep the full-text index
aligned with conversation inserts, deletes and updates
(`sdlc/policy/code-quality`).

Schema bootstrap is lazy on first use and guarded so a given store path
runs through the create-if-missing flow only once per process. A store that
does not exist yet is created at the current shape and records the newest
convergence revision, because nothing written under an earlier shape exists to
converge. Older stores created before the `summary`, `human_email`,
`visibility`, `command`, `is_worker`, and `derivation_version` fields existed
get those fields added via best-effort compatibility migrations that swallow
"field already exists" errors. The `human_email` and `is_worker` indexes are
also created idempotently. Nothing that runs on every open names a field a
convergence step renames or adds: such a field belongs to its step, which runs
once, so a later open cannot restore a field a step renamed away.

Bootstrap also converges an existing store's derived columns, because those
carry values the current rules compute rather than values anyone authored.
A store still holding the legacy `is_agent_spawn` column has it renamed to
`is_worker` and the legacy index dropped. Every mirror whose transcript the
per-runtime subagent rule recognizes, and every mirror whose session id is
null, is deleted together with its tombstone and unreprojectable entries.
Every remaining row that has a session record has its `is_worker` set from
that record's system role; a row with no session record keeps the value it
was written with, because nothing re-derives it.

Convergence is recorded in the store's own schema revision rather than repeated
per process. Bootstrap reads that revision first and skips the work once it
matches, so the usual cost is a single pragma read instead of a table scan on
every command that opens the store. The revision is explicit, not derived:
changing what a converged row should hold requires bumping it, and a rule
changed without a bump leaves existing rows on the old shape. When the database
is locked — another process is mid-write, typically the daemon reconciling —
convergence is abandoned for that open and the revision is left unset, so the
work retries later and a reader never fails for convergence it did not need.

Convergence is an ordered chain of steps, each owning the revision it brings the
store to. A store behind by several steps runs each missing step once, in order,
and records the revision after each; a step already applied is never repeated,
so adding a step never re-runs the deletions an earlier step performed. The
session-attribution step renames the mirror's identity fields to the names the
rest of the platform uses — the agent-native session id, the project path, and the
todo — and attributes every existing mirror its session record claims, restoring
from that record any identity fact an earlier write left empty. It deletes no
mirror.

Two engine caches sit alongside the schema state: one for the writable
engine (used for upserts and tombstone writes) and one for read-only
engines over the mirror store. The read-only engines are only constructed
after the writable engine has confirmed the schema exists. Session-record
facts are not read through an engine of the mirror store's own: they come
from the session record's published queries (`mirror-identity-enrichment`),
because the session record belongs to agent runtime (`local/projects/teleclaude/spec/domain/context-map`).

## Canonical fields

### Session-owned conversation convergence

Structural migrations required by the current source-observation model complete
before bootstrap publishes or caches that schema as ready. A failed structural
migration preserves the pre-migration store and leaves its revision pending;
domain operations consume the current shape
(`sdlc/policy/backward-compatibility-hygiene`).

The mirror is keyed by retained TeleClaude session identity. Source associations
preserve native provenance beneath that identity. Convergence consolidates the
recorded lineage while retaining archived text whose source is unavailable.
The migration uses the existing pre-change snapshot, applies forward once and
remains idempotent (`sdlc/policy/backward-compatibility-hygiene`). Historical
associations follow
`local/projects/teleclaude/spec/feature/session_mirrors/session-id-namespaces`.
The recorded conversation and established access facts survive consolidation.

### Use cases

#### Initial bootstrap

```
Given the mirror store path points to a database that does not yet exist
When any store function is invoked
Then the store path is resolved (home-expanded) and the parent directory is created if missing
And the writable engine is constructed
And on the first connection, the schema bootstrap runs
And the full schema (mirrors, session attributions, indexes, tombstones, retained-after-shrink observations, full-text index, three triggers) is created
And the store records the newest convergence revision, so no convergence step runs against it
And the path is recorded so subsequent calls skip bootstrap
```

#### UC-MSB-2: Idempotent compatibility migration

```
Given a store created by an older version that lacks the derived-classification fields
When the compatibility migration runs
Then a `summary` field is added to the mirrors table
And a `human_email` field is added to the mirrors table
And a `visibility` field (defaulting to "private") is added to the mirrors table
And a `command` field is added to the mirrors table
And an `is_worker` field (defaulting to 0) is added to the mirrors table
And a `derivation_version` field (defaulting to 0) is added to the mirrors table
And each add that fails because the field already exists is swallowed
And any other migration failure is re-raised
And a human-email index and an is_worker index are created idempotently
And the todo field is not added here: the session-attribution step renames it into place, and adds it to a store that never had it (UC-MSB-5)

Given a store the session-attribution step has already converged
When any later process opens it
Then no field that step renamed away is added back
```

#### UC-MSB-3: Existing rows converge on the session record and shed subagents

```
Given a store whose rows were written by an older version
When the compatibility migration runs
Then a surviving `is_agent_spawn` column is renamed to `is_worker` and the legacy index is dropped
And a rename attempt against a store that has no such column is swallowed, while any other failure is re-raised
And every mirror whose transcript the per-runtime subagent rule recognizes is deleted, with its tombstone and unreprojectable entries
And every mirror whose session id is null is deleted the same way
And every remaining row with a session record has `is_worker` set to whether that record's system role is worker
And a row without a session record keeps its stored `is_worker`, command, slug, and title
And re-running the migration against a converged store performs no further writes
```

#### UC-MSB-4: The revision gate bounds convergence to once per store

```
Given a store whose recorded schema revision already matches the current one
When any process opens the store
Then convergence is skipped after the revision is read
And no row is scanned or written on that open

Given a store whose recorded revision is behind the current one
When convergence completes
Then every transcript-derived session identity is either null or a canonical full UUID
And the store rejects a later write that would restore a non-canonical identity
And only then is the current revision recorded, so later opens skip the work

Given the database is locked by another process while convergence is attempted
When the lock error surfaces
Then convergence is abandoned for that open and the revision is left unrecorded
And the caller continues normally, so a read command never fails for convergence
And a later open retries the work

Given a derivation rule changes without the revision being bumped
Then converged stores keep the old shape, because the revision is the only trigger
```

#### UC-MSB-5: An existing store gains session attribution without losing a mirror

```
Given a store whose mirrors were written before session attribution existed
When the session-attribution convergence step runs
Then every mirror present before the step is present after it, with its conversation unchanged
And every mirror whose transcript a session record claims is attributed to that session, with its position in the session's chain
And an identity fact the mirror holds empty is filled from that session record when the record carries it
And an identity fact the mirror already holds is kept
And a mirror no session record claims is left unattributed
```

#### UC-MSB-6: Convergence steps apply once each, in order

```
Given a store whose recorded revision is behind the newest convergence step
When the store is opened
Then each step newer than the recorded revision runs once, in order
And the revision is recorded after each step completes
And a step at or below the recorded revision does not run again
```

#### Read-only engine gating

```
Given a caller requests a read-only engine for a path that has never been bootstrapped
When the read-only engine is constructed
Then the writable engine is constructed first so schema initialization completes
And then the read-only engine is created
And the read-only engine is cached for subsequent reuse
```

#### Full-text index sync triggers

```
Given the mirrors table receives an insert
When the row is committed
Then the corresponding full-text row is inserted

Given a mirrors row is deleted
Then the corresponding full-text row is removed

Given a mirrors row is updated
Then the old full-text row is removed and the new one inserted
```

#### Missing-table tolerance at read sites

```
Given the mirrors table does NOT exist (fresh install before any bootstrap)
When a read site (search, lookup, listing, transcript-state lookup, tombstone lookup) encounters the missing-table error
Then the read function returns an empty result (None / empty list / empty mapping)
And the error is NOT re-raised
```

## Known caveats

- Rows converged before sessions carried one catalog role keep the `is_worker` they were given; a later convergence sets `is_worker` for rows whose session record carries a focused-class role in the agent role catalog and never rewrites an earlier value from a migrated session. A mirror's session attribution `job` is migrated explicitly, because the attribution upsert coalesces and a cleared job would otherwise leave the stale label standing (`local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration`).

- Engine and bootstrap caches are process-wide. They live for the
  process lifetime; tests that need a fresh state must monkeypatch the
  paths AND clear the caches.
- Bootstrap keys are resolved absolute paths. Two different string
  spellings of the same path resolve to the same key.
- The full-text index triggers do not guarantee multi-row update
  atomicity across the row table and the index under concurrent
  writers; the underlying single-writer model is the safety net.
- The compatibility migration runs once per process per new path. The
  cost is bounded because subsequent connections skip bootstrap.
- The schema does NOT include a foreign-key constraint between mirrors
  and tombstones. The two tables coordinate via `source_identity`
  application-side only.
