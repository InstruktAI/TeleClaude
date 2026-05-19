---
id: 'project/spec/feature/session_mirrors/mirror-reconciliation-loop'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Periodic background worker that discovers known agent transcripts and refreshes any mirror whose stored mtime is older than the file''s mtime. Logs reconciliation counters and WAL size deltas per pass.'
---

# Mirror Reconciliation Loop — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Mirror creation through the AGENT_STOP / SESSION_CLOSED event path can miss
transcripts — daemon restarts, hook drops, or fresh installs all leave gaps.
A background worker fills those gaps. The worker is started by the daemon on
boot and ticks every five minutes (300 seconds). Each pass discovers all
transcript files under the per-agent session roots, asks the mirrors table
for each transcript's last known state, and rebuilds the mirror when the
transcript file is newer than the stored row (or when no row exists yet).
Tombstones for known-empty transcripts short-circuit the rebuild (see
`empty-transcript-tombstone`).

The worker emits one structured log line per pass with discovered / processed
/ failed / skipped_unchanged counters, the pass duration, and the WAL file
size before and after the pass. Per-transcript exceptions are caught and
logged at error level; the pass continues with the next transcript.

## Canonical fields

### Behavioral contract

#### Periodic tick

```
Given the daemon is running
And the mirror worker task is started by daemon.run on boot
When the worker enters its loop
Then it executes one reconciliation pass synchronously off the event loop
And then sleeps for RECONCILE_INTERVAL_S (300 seconds) before the next pass
And on asyncio.CancelledError it propagates and exits the loop
And on any other exception it logs at error level and continues to the next sleep
```

#### Per-pass discovery and skip-unchanged

```
Given the mirrors table holds N rows for known transcript paths
When a reconciliation pass starts
Then the worker calls discover_transcripts() to enumerate candidate files under the per-agent session roots
And calls get_mirror_state_by_transcript() to load each known transcript's source_identity + updated_at
For each discovered candidate:
  When the existing mirror's updated_at >= candidate file mtime
  Then the candidate is counted as skipped_unchanged and skipped
```

#### Tombstone short-circuit

```
Given a candidate's source_identity has a tombstone with file_size and file_mtime equal to the candidate's current stat
When the worker checks the tombstone
Then the candidate is counted as skipped_unchanged and skipped
Given the candidate's stat differs from the tombstone
Then the tombstone is deleted and processing continues
```

#### Generate or re-tombstone

```
Given a candidate passes the skip checks
When the worker invokes generate_mirror_sync(...)
Then on success the candidate is counted as processed
  And any prior tombstone for the source_identity is cleared
And on "no conversation extracted" (generator returns False)
  Then a tombstone is recorded for the source_identity with current file_size and file_mtime
  And the corresponding mirror row is deleted (delete_mirror by session_id + source_identity)
  And the candidate is counted as processed
```

#### Failure isolation and counters

```
Given an exception is raised while processing one candidate
When the per-candidate try block catches it
Then result.failed += 1
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
And the values are the ReconcileResult counters and the WAL file size before and after the pass
```

#### Async surface

```
Given a caller awaits worker.run_once()
When the call resolves
Then the work has run in asyncio.to_thread (off the event loop)
And the returned ReconcileResult holds the counters for the pass
```

### V1 implementation pointers

- `teleclaude/mirrors/worker.py:MirrorWorker` — the worker class.
- `teleclaude/mirrors/worker.py:MirrorWorker.run` — periodic loop body and cancellation handling.
- `teleclaude/mirrors/worker.py:MirrorWorker.run_once` — single-pass async entry point.
- `teleclaude/mirrors/worker.py:MirrorWorker._reconcile_sync` — the actual per-pass logic, discovery, skip-checks, generate/tombstone, logging.
- `teleclaude/mirrors/worker.py:RECONCILE_INTERVAL_S` — 300 seconds tick interval.
- `teleclaude/mirrors/worker.py:ReconcileResult` — dataclass holding counters returned per pass.
- `teleclaude/mirrors/worker.py:MirrorWorker._wal_size_kb` — WAL byte size accessor used in the log line.
- `teleclaude/mirrors/store.py:get_mirror_state_by_transcript` — per-transcript-path lookup for skip decisions.
- `teleclaude/utils/transcript_discovery.py:discover_transcripts` — candidate enumeration.
- `teleclaude/daemon.py:672-674` — worker boot site (`MirrorWorker()` → `asyncio.create_task(worker.run(), name="mirror-worker")`).

## Known caveats

- The interval is fixed at 300 seconds; there is no environment variable or
  config knob to tighten or loosen it.
- Tombstone size + mtime equality is the only short-circuit. A transcript
  that is rewritten in place with the same size and same nanosecond mtime
  will be treated as unchanged.
- Per-pass discovery rescans the full session roots every tick. There is no
  incremental fs-watch integration; the cost scales with the number of
  transcripts on disk.
- The pass operates against the resolved `MIRRORS_DB_PATH` at worker
  construction time and does not honor monkeypatched paths.
- A failing summary or generator step is counted as `failed` and logged with
  traceback. The corresponding mirror is left in its previous state — there
  is no retry queue.
