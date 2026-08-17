---
description: "Periodic background worker that discovers known agent transcripts and refreshes any mirror whose stored mtime is older than the file's mtime. Logs reconciliation counters and store-WAL size deltas per pass."
visibility: 'public'
---

# Mirror Reconciliation Loop — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Mirror creation through the event-driven path can miss transcripts —
service restarts, hook drops, or fresh installs all leave gaps. A
background worker fills those gaps. The worker is started by the
session_mirrors service on boot and ticks every five minutes (300
seconds). Each pass discovers all transcript files under the per-agent
session roots, asks the mirror store for each transcript's last known
state, and rebuilds the mirror when the transcript file is newer than the
stored record (or when no record exists yet). Tombstones for known-empty
transcripts short-circuit the rebuild (see `empty-transcript-tombstone`).

The worker emits one structured log line per pass with discovered /
processed / failed / skipped_unchanged counters, the pass duration, and
the store's write-ahead-log size before and after the pass. Per-transcript
exceptions are caught and logged at error level; the pass continues with
the next transcript.

## Canonical fields

### Use cases

#### Periodic tick

```
Given the session_mirrors service is running
And the reconciliation worker is started at service boot
When the worker enters its loop
Then it executes one reconciliation pass off the event loop
And then sleeps for the reconcile interval (300 seconds) before the next pass
And on cancellation it exits the loop cleanly
And on any other exception it logs at error level and continues to the next sleep
```

#### UC-MRL-2: Per-pass discovery and skip-unchanged

```
Given the mirror store holds rows for known transcript paths
When a reconciliation pass starts
Then the worker enumerates candidate transcript files under the per-agent session roots
And reads each known transcript's last known source_identity, updated_at, and derivation_version
For each discovered candidate:
  When the existing mirror's updated_at is greater than or equal to the candidate file's mtime
    And the existing mirror's derivation_version equals the current derivation version
  Then the candidate is counted as skipped_unchanged and skipped
  When the existing mirror's derivation_version is older than the current derivation version
  Then the candidate is re-derived regardless of mtime so the row converges to the current derivation rules
```

#### Tombstone short-circuit

```
Given a candidate's source_identity has a tombstone with file_size and file_mtime equal to the candidate's current stat
When the worker checks the tombstone
Then the candidate is counted as skipped_unchanged and skipped
Given the candidate's stat differs from the tombstone
Then the tombstone is cleared and processing continues
```

#### Generate or re-tombstone

```
Given a candidate passes the skip checks
When the worker invokes mirror generation
Then on success the candidate is counted as processed
  And any prior tombstone for the source_identity is cleared
And on "no conversation extracted"
  Then a tombstone is recorded for the source_identity with current file_size and file_mtime
  And any existing mirror record keeps its stored conversation text
  And the candidate is counted as processed
```

#### UC-MRL-5: Orphan re-derivation sweep

```
Given mirror rows whose transcript file no longer exists on disk
And whose derivation_version is older than the current derivation version
When a reconciliation pass runs the orphan sweep
Then each such row is re-derived in place from its stored title and conversation_text
And its title, command, slug, and is_worker are recomputed by the same detection used at extraction
And the row is never deleted and its transcript is never required
And its derivation_version is advanced to the current version so the sweep is idempotent
```

#### Failure isolation and counters

```
Given an exception is raised while processing one candidate
When the per-candidate handler catches it
Then the failed counter is incremented
And an error log "Mirror reconciliation failed for transcript <path> (<agent>)" with traceback is emitted
And the worker continues to the next candidate without rolling back already-processed work
```

#### Pass completion log

```
Given a pass finishes (success or partial failure)
When the worker logs the result
Then one INFO log line is emitted with template
  "mirror.reconciliation.complete discovered=%d processed=%d failed=%d
   skipped_unchanged=%d duration_s=%.3f wal_before_kb=%d wal_after_kb=%d"
And the values are the pass counters and the store's WAL size before and after the pass
```

#### Async surface

```
Given a caller awaits a single-pass entry point
When the call resolves
Then the work has run off the caller's event loop
And the returned result holds the counters for the pass
```

#### UC-MRL-8: A wedged pass cannot stall the loop indefinitely

```
Given the reconciliation worker is running its loop
And one reconciliation pass blocks without raising and does not return within the per-pass time budget
When the budget elapses
Then the worker stops awaiting that pass
And sleeps and proceeds to the next cycle so a subsequent pass runs without a daemon restart
```

#### UC-MRL-10: The mirror outlives its transcript

```
Given a mirror whose transcript file no longer exists on disk
When reconciliation runs
Then the candidate is never visited, because discovery walks transcripts that exist
And the mirror keeps its stored conversation text indefinitely
And the mirror remains the durable copy of that conversation
```

#### UC-MRL-11: Project attribution resolves the repository, not the path tail

```
Given a transcript recorded from a git worktree of a repository
When the mirror's project is derived
Then the project resolves to the repository the worktree belongs to
And it is not taken from the final segment of the transcript directory name
```

## Known caveats

- The interval is fixed at 300 seconds; there is no environment variable
  or config knob to tighten or loosen it.
- Tombstone size + mtime equality is the only short-circuit. A transcript
  that is rewritten in place with the same size and same nanosecond mtime
  will be treated as unchanged.
- Per-pass discovery rescans the full session roots every tick. There is
  no incremental file-watch integration; the cost scales with the number
  of transcripts on disk.
- The pass binds to the resolved mirror-store path at worker construction
  time and does not honor path overrides applied after the worker has
  started.
- A failing summary or generator step is counted as `failed` and logged
  with traceback. The corresponding mirror is left in its previous state —
  there is no retry queue.
- The orphan sweep re-derives from the row's stored rendered
  `conversation_text`, which is lossier than a live transcript: detection and
  title derivation parse the rendered "[<ts>] Role: …" blocks rather than the
  original structured turns. A row whose transcript still exists is re-derived
  through the full extraction path instead, which is exact.
