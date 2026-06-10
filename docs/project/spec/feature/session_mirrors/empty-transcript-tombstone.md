---
description: 'Tombstone records that capture empty or fully-stripped transcripts so the reconciliation worker can skip them on subsequent passes without re-extracting. Tombstones are keyed by source_identity and cleared whenever a transcript produces conversation text.'
visibility: 'public'
---

# Empty Transcript Tombstone — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Many agent transcripts contain no conversation text after normalization —
session-start hooks with no user input, transcripts that were trimmed to
tool-only blocks, sessions that started but never reached the user prompt.
Re-extracting these on every reconciliation tick wastes IO and CPU. The
session_mirrors service maintains a tombstone record for each
known-empty transcript, keyed by `source_identity` and carrying the
transcript's `file_size` and `file_mtime` at the time of the determination.

On the next reconciliation pass the worker compares the candidate file's
current `(size, mtime)` against the tombstone. If they match, processing is
skipped and the candidate counts as `skipped_unchanged`. If they differ, the
tombstone is cleared and the worker reprocesses the file — a new turn may
have arrived. Successful mirror generation always clears any prior
tombstone for that `source_identity`.

See `project/spec/domain/session_mirrors.md` for the canonical tombstone
field set.

## Canonical fields

### Use cases

#### Tombstone identity and uniqueness

```
Given the session_mirrors service records a tombstone
When the record is written
Then the record is keyed uniquely by source_identity
And it carries agent, transcript_path, file_size, file_mtime, and the creation timestamp
And re-recording for the same source_identity overwrites all other fields
```

#### Skip when file is unchanged

```
Given a tombstone exists for source_identity SI with file_size F and file_mtime M
And the candidate transcript at the same source_identity currently stats to (F, M)
When the reconciliation pass evaluates the tombstone
Then the worker reports the candidate as skipped_unchanged
And the conversation extractor is not invoked
```

#### Re-extract when file changes

```
Given a tombstone exists for source_identity SI with (F0, M0)
And the candidate's current stat is (F1, M1) where (F0, M0) != (F1, M1)
When the worker evaluates the tombstone
Then the tombstone for SI is cleared
And processing continues to extraction
```

#### Record a tombstone when extraction yields no text

```
Given extraction yields zero normalized conversation messages for a candidate
When the worker records the result
Then a tombstone is written for the candidate's source_identity with the current (file_size, file_mtime)
And any existing mirror for that source_identity is deleted
```

#### Clear tombstone on a successful (re-)generation

```
Given extraction succeeds for a candidate (conversation text was produced)
When the worker records the result
Then the tombstone for the candidate's source_identity is cleared
And future passes will reprocess the file from scratch if its mtime advances
```

## Known caveats

- Tombstone matching is by file size and modification time. A transcript
  rewritten in place with the same nanosecond mtime AND the same byte size
  will not resurrect.
- `agent` is stored on the tombstone for debuggability but is not part of
  the lookup key. Looking up a tombstone by agent is not supported.
- Tombstones are never garbage-collected automatically. A removed transcript
  file leaves its tombstone behind permanently. Only a future pass with a
  matching `source_identity` and changed stat clears the record.
- The tombstone short-circuit runs AFTER the updated_at-vs-mtime skip check.
  Mirrors that already exist and are up-to-date are skipped without
  consulting tombstones at all.
