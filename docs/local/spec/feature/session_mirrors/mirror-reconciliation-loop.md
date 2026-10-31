---
description: "Periodic background worker that discovers known agent transcripts and refreshes any mirror whose stored mtime is older than the file's mtime. Logs reconciliation counters and store-WAL size deltas per pass."
visibility: 'public'
---

# Mirror Reconciliation Loop — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

Mirror creation through the event-driven path can miss transcripts —
service restarts, hook drops, or fresh installs all leave gaps. A
background worker fills those gaps. The worker is started by the
session_mirrors service on boot and ticks every five minutes (300
seconds). Each pass loads the mirror store's last known state once and
enumerates transcript files under the per-agent session roots. A known
mirror with current derivation rules whose write timestamp covers the file's
mtime is counted as unchanged before its transcript is opened for admission
classification. New, changed, and derivation-stale candidates pass through
the per-runtime subagent and headless exclusion rules before generation.
The worker resolves changed transcript candidates to retained TeleClaude
sessions and groups them before refreshing each session-owned mirror once.
New source content, a missing mirror, or a changed lineage makes that
conversation eligible for refresh. Tombstones for known-empty transcripts short-circuit the rebuild
(see `empty-transcript-tombstone`).

The worker emits one structured log line per pass with discovered /
processed / failed / skipped_unchanged counters, the pass duration, and
the store's write-ahead-log size before and after the pass. Per-transcript
exceptions are caught and logged at error level; the pass continues with
the next transcript.

## Canonical fields

### Conversation work and readiness

Freshness is evaluated for the retained conversation selected for the candidate
and its source observation. An observation belonging to another session cannot
skip a conversation whose mirror is missing or stale. Negative file tombstones
remain file observations and establish no conversation coverage
(`sdlc/policy/code-quality`).

The existing timer and discovery select refresh work. One TeleClaude session is
the work unit, and its complete lineage goes to the shared conversation
projector. Per-source file observations remain freshness and provenance facts;
they do not select independent conversation rows. Generation follows
`local/projects/teleclaude/spec/feature/session_mirrors/mirror-identity-enrichment`.

Closure requests the same refresh capability for a captured source boundary.
Confirmed coverage reports readiness even when no text rewrite was needed.
Later successful reconciliation can satisfy pending closure work. A failed or
partial read preserves stored conversation and reports its incomplete coverage.

### Subagent exclusion

A transcript the per-runtime subagent rule recognizes is never a candidate. It
is dropped before its identity, project or content is read, and the discovered
counter excludes it. The rule per runtime:

- Claude: a transcript filename beginning with `agent-`, or a `subagents` path
  segment.
- Codex: a session header whose spawn source names a parent thread.
- DeepSeek: a session entry carrying `parentSession`.
- Antigravity: a conversation recognized as a provider-native subagent's
  execution, as
  `local/projects/teleclaude/spec/feature/integration/agent-cli-hook-reception`
  states.

A subagent transcript mirrored under an earlier rule is removed by store
convergence and never refreshed by a pass.

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
  Then the candidate is counted as skipped_unchanged and skipped without opening the transcript
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

#### UC-MRL-5: Orphan sweep marks stale mirrors unreprojectable

```
Given mirror rows whose derivation_version is older than the current derivation version
And whose transcript file no longer exists on disk
When a reconciliation pass runs the orphan sweep
Then each such row is marked unreprojectable by its source identity
And the row is never deleted and keeps its stored title, classification, and conversation_text
And no field of the row is recomputed from its stored text
And a stale row whose transcript still exists is left to the candidate pass, which re-derives it from the transcript
And a row already marked is not visited again, so the sweep is idempotent
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

#### UC-MRL-12: Subagent transcripts are never candidates

#### UC-MRL-13: Headless one-shot invocations are never candidates

```
Given the per-agent session roots hold transcripts written by headless one-shot invocations — a single prompt handed to a runtime as a subprocess, which that runtime records under its own native session id
When a reconciliation pass enumerates candidates
Then a transcript the per-runtime headless rule recognizes is dropped before identity, project, or content is read from it
And for codex the rule matches a session header whose source names the exec invocation mode
And a runtime whose transcript format records no invocation mode carries no headless rule, so its transcripts are enumerated exactly as before
And the rule reads invocation mode from the transcript itself and never consults the presence of a session record
And the discovered counter excludes dropped transcripts
And a headless transcript mirrored under an earlier rule is removed by store convergence, never refreshed by a pass
```

#### UC-MRL-11: Project attribution resolves the repository, not the path tail

```
Given a transcript recorded from a git worktree of a repository
When the mirror's project is derived
Then the project resolves to the repository the worktree belongs to
And it is not taken from the final segment of the transcript directory name
```

#### UC-MRL-14: A pass records the close of every attributed session

```
Given a mirrored session whose recorded attribution is still open
And its session record has since closed
When a reconciliation pass runs
Then the pass records the session's close on its attribution
And it does so whether or not any of the session's transcripts changed since their last write
And a session already recorded as closed is not written again
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
- A failing generator step is counted as `failed` and logged with
  traceback. The corresponding mirror is left in its previous state — there
  is no retry queue.
- A stale row whose transcript is gone is marked unreprojectable rather than
  re-derived: the rendered `conversation_text` is lossier than the transcript,
  so nothing recomputes the row's fields from it. A row whose transcript still
  exists is re-derived through the full extraction path, which is exact.

- Antigravity subagent transcripts mirrored before the Antigravity subagent
  rule existed are not removed: the store convergence that sheds subagent
  mirrors already ran on every existing store, and no pass refreshes them
  again because their transcripts no longer change.
