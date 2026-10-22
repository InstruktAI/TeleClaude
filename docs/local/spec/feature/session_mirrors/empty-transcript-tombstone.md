---
description: 'Tombstone records that capture transcripts mirror generation declined — empty or fully-stripped sources, and parses that would shrink a stored mirror — so the reconciliation worker can skip them on subsequent passes without re-extracting. Tombstones are keyed by source_identity and cleared whenever generation succeeds.'
visibility: 'public'
---

# Empty Transcript Tombstone — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

Mirror generation can yield no conversation text after normalization — for
example, a session-start hook with no user input, a tool-only transcript, or a
session that never reached the user prompt. The stored conversation is left
unchanged, and a tombstone keyed by `source_identity` records the source's
`file_size` and `file_mtime` so an unchanged empty source is skipped on later
reconciliation.

A smaller projection is refused when the stored mirror's derivation version is
current or newer; the stored conversation remains unchanged and the shrink
refusal is recorded separately from tombstones. A smaller projection from an
older derivation version may be accepted as part of upgrading the stored
representation.

On the next reconciliation pass the worker compares the candidate file's
current `(size, mtime)` against the tombstone. If they match, processing is
skipped and the candidate counts as `skipped_unchanged`. If they differ, the
tombstone is cleared and the worker reprocesses the file — a new turn may
have arrived. Successful mirror generation always clears any prior
tombstone for that `source_identity`.

See `local/projects/teleclaude/spec/domain/session_mirrors.md` for the canonical tombstone
field set.

## Canonical fields

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
