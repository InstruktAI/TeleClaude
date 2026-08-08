---
description: "Idempotent bootstrap for the mirror store's schema — mirrors, tombstones, the full-text index, and the index-sync triggers — plus per-process compatibility migrations that keep older databases readable by newer code."
visibility: 'public'
---

# Mirror Schema Bootstrap — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

The session_mirrors service owns its own store with three logical
objects: the mirrors record table, the tombstones table for
empty-transcript memory, and a full-text index over the mirrors'
conversation text. Sync triggers keep the full-text index aligned with
the row table on insert, delete, and update.

Schema bootstrap is lazy on first use and guarded so a given store path
runs through the create-if-missing flow only once per process. Older
stores created before the `summary`, `human_email`, `visibility`,
`command`, `slug`, `is_worker`, and `derivation_version` fields
existed get those fields added via best-effort compatibility migrations
that swallow "field already exists" errors. The `human_email` and
`is_worker` indexes are also created idempotently.

Bootstrap also converges an existing store's derived columns, because those
carry values the current rules compute rather than values anyone authored.
A store still holding the legacy `is_agent_spawn` column has it renamed to
`is_worker` and the legacy index dropped; every row's `is_worker` is realigned
with the current worker-command set; and a row whose title no longer matches
what its recorded launch command renders has that title rebuilt. Each step
reads the row's persisted `command`, so convergence costs narrow updates
rather than re-reading transcripts. Title repair is bounded to commands that
name a deployed artifact or a mapped lifecycle role, since detection also
matches pasted paths and prose, and those rows hold a real first-message title
that rendering would destroy.

Two engine caches sit alongside the schema state: one for the writable
engine (used for upserts and tombstone writes) and one for read-only
engines (one for the mirror store, one for the upstream session record
store). The read-only engines are only constructed after the writable
engine has confirmed the schema exists.

## Canonical fields

### Use cases

#### Initial bootstrap

```
Given the mirror store path points to a database that does not yet exist
When any store function is invoked
Then the store path is resolved (home-expanded) and the parent directory is created if missing
And the writable engine is constructed
And on the first connection, the schema bootstrap runs
And the full schema (mirrors, indexes, tombstones, full-text index, three triggers) is created
And the per-process compatibility migration runs (idempotent field-adds)
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
And a `slug` field is added to the mirrors table
And an `is_worker` field (defaulting to 0) is added to the mirrors table
And a `derivation_version` field (defaulting to 0) is added to the mirrors table
And each add that fails because the field already exists is swallowed
And any other migration failure is re-raised
And a human-email index and an is_worker index are created idempotently
```

#### UC-MSB-3: Existing rows converge on the current derivation rules

```
Given a store whose rows were written by an older version
When the compatibility migration runs
Then a surviving `is_agent_spawn` column is renamed to `is_worker` and the legacy index is dropped
And a rename attempt against a store that has no such column is swallowed, while any other failure is re-raised
And every row whose `is_worker` disagrees with the current worker-command set is realigned from its persisted `command`
And a row whose recorded command names a deployed artifact or a mapped lifecycle role has its title rebuilt from that command and slug
And a row whose recorded command names neither keeps its stored title, so a spurious detection never overwrites the human's own words
And re-running the migration against a converged store performs no further writes
```

#### Read-only engine gating

```
Given a caller requests a read-only engine for a path that has never been bootstrapped
When the read-only engine is constructed
Then the writable engine is constructed first so schema initialization completes
And then the read-only engine is created
And the read-only engine is cached for subsequent reuse
```

#### Upstream session-record read-only engine

```
Given the session_mirrors service needs to read upstream session records
When the upstream read-only engine is requested
Then a read-only engine is constructed against the upstream session-record store
And the engine is cached
And subsequent calls reuse the cached engine
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
