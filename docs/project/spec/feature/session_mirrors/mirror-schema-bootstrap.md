---
id: 'project/spec/feature/session_mirrors/mirror-schema-bootstrap'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Idempotent bootstrap for the mirror store''s schema — mirrors, tombstones, the full-text index, and the index-sync triggers — plus per-process compatibility migrations that keep older databases readable by newer code.'
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
stores created before the `summary`, `human_email`, and `visibility`
fields existed get those fields added via best-effort compatibility
migrations that swallow "field already exists" errors. The human-email
index is also created idempotently.

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

#### Idempotent compatibility migration

```
Given a store created by an older version that lacks summary / human_email / visibility
When the compatibility migration runs
Then a `summary` field is added to the mirrors table
And a `human_email` field is added to the mirrors table
And a `visibility` field (defaulting to "private") is added to the mirrors table
And each add that fails because the field already exists is swallowed
And any other migration failure is re-raised
And a human-email index is created idempotently
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
