---
description: 'Architecture, schema, worker design, and retry policy for the durable inbound message queue.'
visibility: 'public'
---

# Inbound Queue — Spec

## What it is

The inbound queue provides guaranteed delivery of user messages to their agent sessions. Adapters enqueue messages and return immediately. Successful enqueue is the accepted-input boundary for non-terminal UI input: core records accepted session metadata after durable insert and before typing callbacks, worker start, or projection-visible wakeups. A per-session worker drains the queue, delivering messages to the tmux session with FIFO ordering and exponential backoff retry.

For non-terminal input, the successful enqueue boundary is also the accepted-input boundary. After a queue insert succeeds, core records the accepted session metadata before any typing callback, worker start, or projection-visible wakeup can observe the session. Terminal input bypasses the inbound queue, so terminal-origin freshness is recorded by the `user_prompt_submit` hook path defined in `local/projects/teleclaude/spec/session-projection`.

## Canonical fields

### Table Schema

The queue and accepted-turn binding tables (`inbound_queue`,
`accepted_turn_bindings`, `turn_authored_parts`, `turn_receipt_envelopes`,
`binding_conflict_candidates`) and their indexes are defined by
`teleclaude/core/schema.sql` for a new database and by the forward migrations
under `teleclaude/core/migrations/` for an existing one. Their columns,
constraints and closed value sets are read there; the sections below state what
the rows mean.

### Accepted-turn binding state

<!-- planned-change:accepted-turn-bindings-never-form -->

Caller-origin conversational rows carry a closed binding disposition with two
terminal values: `legacy_pre_cutover` for delivered rows that predate the
binding cutover and cannot be reconstructed truthfully, and `input_conflict`
when one accepted occurrence cannot be correlated to exactly one native entry.
Absence means the row remains eligible to bind.

<!-- change:accepted-turn-bindings-never-form -->

The accepted-turn binding covers the delivered rows of the classes this section
names as binding. A caller-origin conversational row is one: a row accepted from
a caller send whose text is a keyed caller-origin identity envelope carrying its
occurrence key (`local/projects/teleclaude/spec/message-headers`), whether or
not its caller metadata survived acceptance. A peer bundle carries peer
envelopes rather than a caller-origin one, and is not covered. A covered row
carries a closed binding disposition with two terminal values:
`legacy_pre_cutover` for delivered rows that predate the binding cutover and
cannot be reconstructed truthfully, and `input_conflict` when one accepted
occurrence cannot be correlated to exactly one native entry. Absence means the
row remains eligible to bind.

<!-- /planned-change:accepted-turn-bindings-never-form -->

The accepted-turn binding aggregate persists one runtime-qualified native-entry
root, its ordered authored parts, and the accepted receipt envelopes correlated
to those parts. Receipt envelopes retain the inbound row id, occurrence key,
envelope and body spans, and authored-part id. A native
entry and an accepted occurrence each bind at most once. Binding conflicts keep
their exact native-entry candidates as durable evidence and never acquire a
guessed author.

<!-- planned:github-turn-mirror -->

A comment routed from GitHub binds as one authored part of the `github` kind.
Its delivered row is the authority for the correlation: the native entry whose
authored text equals the row's accepted content is that row's entry, and
nothing is read from the shape of the text. The part spans the whole entry and
names the person who wrote the comment as a human author, with the GitHub login
the comment was written under and the comment's link as its channel facts. The
receipt envelope spans the whole entry as well. The projection pass and the
completed-turns read
(`local/projects/teleclaude/spec/feature/agent_runtime/session-transcript-retrieval`)
both establish the binding, so a turn's input carries its GitHub authorship
whichever of them reads the entry first. A delivered GitHub row that matches no
entry stays unbound and acquires no disposition.

<!-- /planned:github-turn-mirror -->

### Reminder machine input

Reminder firings use the control-delivery surface and never enter this queue.
The inbound schema retains historical `reminder` message/classification members
so owned existing rows remain readable, but no active reminder producer writes
them and no reminder retry path is defined here. Conversational text, voice, and
file input are the queue's active message types.

### Status Lifecycle

```
pending → processing → delivered
                    ↘ failed → pending (retry) → ...
pending/failed/processing → expired (session closed)
```

### Worker Design

Each session has at most one worker task (`asyncio.create_task`). Workers are per-session FIFO drains:

1. `fetch_inbound_pending(session_id, limit=1, now, lock_cutoff)` — fetch next eligible row
2. `claim_inbound(row_id, now, lock_cutoff)` — CAS UPDATE: set `locked_at`, `status='processing'`
3. `deliver_fn(row)` — call the delivery function (raises on failure)
4. `mark_inbound_delivered(row_id, now)` — set `status='delivered'`
5. On exception: `mark_inbound_failed(row_id, error, now, backoff)` — schedule retry

Workers self-terminate when no eligible rows remain. `_ensure_worker` spawns a new worker if one is not already running.

### Singleton

The `InboundQueueManager` is initialized once in `CommandService.__init__` via `init_inbound_queue_manager(deliver_fn, force=True)`. The deliver function is `functools.partial(deliver_inbound, client=client, start_polling=start_polling)`.

Access pattern:

- `init_inbound_queue_manager(fn)` — initialize (call once at startup)
- `get_inbound_queue_manager()` — returns the singleton (raises if not initialized)
- `reset_inbound_queue_manager()` — test-only reset

### Retry Policy

Exponential backoff: `[5, 10, 20, 40, 80, 160, 300]` seconds. Index is `min(attempt_count, len-1)`. No maximum retry count — messages are retried indefinitely until delivered or the session is closed.

Lock timeout: 5 minutes. Rows locked longer than this are reclaimable (handles worker crash/restart).

### Accepted input metadata

`InboundQueueManager.enqueue(...)` records accepted input metadata through a core-owned post-insert hook after `enqueue_inbound` returns a row id and before any queue side effects:

- `last_message_sent`
- `last_message_sent_at`
- `last_input_origin`
- typed origin metadata for the origin section

If `enqueue_inbound` returns `None` because `(origin, source_message_id)` dedup skipped the row, the accepted metadata hook does not run. Duplicate source messages must not rewrite accepted-input state. Acceptance code must never write `last_projected_at`; the transcript projector owns that watermark.

### Delivery Function

`deliver_inbound(row, client, start_polling)` in `command_handlers.py`:

1. Fetch session from DB — raises if not found
2. Startup gate: wait up to 15s for session to exit `initializing` — raises on timeout
3. Headless adoption: if `lifecycle_status == 'headless'`, adopt a tmux session
4. Backfill accepted input metadata (`last_message_sent`, `last_message_sent_at`, `last_input_origin`) only for legacy queued rows whose accepted state is absent or stale; the fallback runs before any projection-visible wakeup and never advances `last_projected_at`
5. Drop pending adapter QoS output if needed; this is delivery cleanup only, not projection truth
6. Wrap text with bracketed paste, send via `tmux_io.process_text`
7. On `process_text` returning False: raise `RuntimeError` (triggers retry)
8. On success: update `last_activity`, start polling

Delivery is not the primary UI-origin acceptance boundary. Delivery may preserve compatibility for old queued rows, but it must not be the first writer for newly accepted UI input and must never advance `last_projected_at`. Terminal input does not enter through this queue, so terminal-origin freshness is recorded by the `user_prompt_submit` hook path defined in `local/projects/teleclaude/spec/session-projection`.

### Acceptance Metadata

`process_message` owns the non-terminal accepted-input metadata write. The write happens only after durable queue insert succeeds and before the queue manager invokes adapter typing callbacks or starts a drain worker.

The accepted metadata consists of:

- `last_message_sent` — operational preview of the accepted text
- `last_message_sent_at` — acceptance timestamp used by v1 origin freshness checks
- `last_input_origin` — canonical input origin (`telegram`, `discord`, `whatsapp`)
- origin metadata — typed adapter metadata persisted for the origin when provided

Acceptance code must not write `last_projected_at`. That field is projector-owned, as defined in `local/projects/teleclaude/spec/session-projection`.

### Deduplication

The unique index on `(origin, source_message_id)` (where `source_message_id IS NOT NULL`) prevents duplicate enqueues. `enqueue_inbound` returns `None` on dedup skip. Dedup skips do not refresh accepted metadata; the already accepted queue row remains the source for that adapter message.

Adapters that provide stable message IDs (Discord, Telegram, WhatsApp) must pass `source_message_id`. API input omits it unless the caller supplies a stable client message id. Terminal input can omit it.

### Session Lifecycle Integration

- **Session closed**: `expire_session(session_id)` cancels the worker and bulk-expires pending messages.
- **Daemon startup**: `startup()` scans for pending messages and spawns workers for non-empty sessions.

- **Daemon shutdown**: once the daemon is draining, workers claim no further messages. A message already claimed keeps its delivery owner until its paste, submission and delivered status settle (`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`); then the workers stop. Unclaimed messages remain in DB for next startup.

### Cleanup

<!-- planned-change:accepted-turn-bindings-never-form -->

`cleanup_inbound(older_than_iso)` deletes expired rows older than the threshold.
A delivered row becomes cleanup-eligible only after its accepted occurrence is
bound to a runtime-qualified native entry or it carries a terminal binding
disposition. Delivered post-cutover rows with neither survive cleanup so later
projection or recovery can bind them. The maintenance service schedules the
cleanup periodically.

<!-- change:accepted-turn-bindings-never-form -->

`cleanup_inbound(older_than_iso)` deletes terminal rows older than the
threshold. A delivered row the accepted-turn binding covers that is neither
bound nor terminally dispositioned survives the threshold while its target
session is retained under Session-Scoped Retention
(`local/projects/teleclaude/design/architecture/database`), so that session's
projection can still bind it. Once the session's retention ends, its unbound
rows are pruned with the rest of its runtime state. Rows the binding does not
cover are pruned by age alone. The maintenance service schedules the cleanup
periodically.

<!-- /planned-change:accepted-turn-bindings-never-form -->

### Adapter Contract

Adapters enqueue via `InboundQueueManager.enqueue(...)` and return immediately. After a successful enqueue, adapters show a platform-native typing indicator. Adapters must not contain delivery logic or mutate session origin fields directly; they pass origin metadata into the queue and core records accepted state at the successful enqueue boundary, before adapter-visible side effects.

While the daemon is draining, new input is refused with a retryable shutdown refusal before accepted state is recorded. The adapter answers that refusal through its own reply path or leaves the input unconsumed at its provider; it never drops the input silently (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

## See Also

- docs/local/spec/session-projection.md
