---
id: 'project/spec/feature/session_mirrors/empty-transcript-tombstone'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Tombstone rows that record empty or fully-stripped transcripts so the reconciliation worker can skip them on subsequent passes without re-extracting. Tombstones are keyed by source_identity and cleared whenever a transcript produces conversation text.'
---

# Empty Transcript Tombstone — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Many agent transcripts contain no conversation text after normalization —
session-start hooks with no user input, transcripts that were trimmed to
tool-only blocks, sessions that started but never reached the user prompt.
Re-extracting these on every reconciliation tick wastes IO and CPU. The
mirror store carries a sibling `mirror_tombstones` table that records when a
specific transcript file produced no conversation text, along with the file's
`file_size` and `file_mtime` at the time of the determination.

On the next reconciliation pass the worker compares the candidate file's
current `(size, mtime)` against the tombstone. If they match, processing is
skipped and the candidate counts as `skipped_unchanged`. If they differ, the
tombstone is deleted and the worker reprocesses the file — a new turn may
have arrived. Successful mirror generation always clears any prior tombstone
for that `source_identity`.

## Canonical fields

### Behavioral contract

#### Tombstone identity and uniqueness

```
Given a mirror_tombstones row is upserted
When the worker calls upsert_mirror_tombstone
Then the row is keyed by source_identity (PRIMARY KEY)
And the row carries agent, transcript_path, file_size, file_mtime, created_at
And re-upserting the same source_identity updates all other columns (ON CONFLICT DO UPDATE)
```

#### Skip when file is unchanged

```
Given a tombstone exists for source_identity SI with file_size F and file_mtime M
And the candidate transcript at the same source_identity currently stats to (F, M)
When the reconciliation pass checks _should_skip_tombstoned_transcript
Then the worker returns True without invoking the generator
And the candidate counts as skipped_unchanged
```

#### Re-extract when file changes

```
Given a tombstone exists for source_identity SI with (F0, M0)
And the candidate's current stat is (F1, M1) where (F0, M0) != (F1, M1)
When the worker checks the tombstone
Then the tombstone for SI is deleted via delete_mirror_tombstone
And processing continues to the generator
```

#### Record a tombstone when extraction yields no text

```
Given generate_mirror_sync extracts zero normalized conversation messages from a transcript
When the worker sees the generator return False
Then a tombstone is recorded for the candidate's source_identity with the current (file_size, file_mtime)
And any existing mirror row for that source_identity is deleted
```

#### Clear tombstone on a successful (re-)generation

```
Given the generator returns True for a candidate (text was extracted)
When the worker records the result
Then delete_mirror_tombstone(source_identity) is called
And future passes will reprocess the file from scratch if its mtime advances
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:_MIRRORS_SCHEMA` — `mirror_tombstones` table definition (`source_identity` PRIMARY KEY, `agent`, `transcript_path`, `file_size`, `file_mtime`, `created_at`).
- `teleclaude/mirrors/store.py:get_mirror_tombstone` — read by `source_identity`.
- `teleclaude/mirrors/store.py:upsert_mirror_tombstone` — INSERT … ON CONFLICT DO UPDATE.
- `teleclaude/mirrors/store.py:delete_mirror_tombstone` — DELETE by `source_identity`.
- `teleclaude/mirrors/store.py:MirrorTombstoneRecord` — dataclass for the row.
- `teleclaude/mirrors/worker.py:_should_skip_tombstoned_transcript` — size/mtime equality check.
- `teleclaude/mirrors/worker.py:_record_tombstone` — captures `(file_size, file_mtime)` and writes the row.
- `teleclaude/mirrors/worker.py:_reconcile_sync` — calls these helpers and decides delete-on-clear vs delete-on-record.

## Known caveats

- Tombstones use `file_mtime` as a string (`stat.st_mtime_ns`) plus
  `file_size` for equality. A transcript rewritten in place with the same
  nanosecond mtime AND the same byte size will not resurrect.
- `agent` is stored on the tombstone for debuggability but is not part of
  the lookup key. Looking up a tombstone by agent is not supported.
- Tombstones are never garbage-collected automatically. A removed transcript
  file leaves its tombstone behind permanently. Only a future passage with a
  matching `source_identity` and changed stat clears the row.
- The tombstone short-circuit runs AFTER the updated_at-vs-mtime skip check.
  Mirrors that already exist and are up-to-date are skipped without
  consulting tombstones at all.
