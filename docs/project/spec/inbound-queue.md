---
description: 'Architecture, schema, worker design, and retry policy for the durable inbound message queue.'
visibility: 'public'
---

# Inbound Queue — Spec

## What it is

The inbound queue provides guaranteed delivery of user messages to their agent sessions. Adapters enqueue messages and return immediately. Successful enqueue is the accepted-input boundary for non-terminal UI input: core records accepted session metadata after durable insert and before typing callbacks, worker start, or projection-visible wakeups. A per-session worker drains the queue, delivering messages to the tmux session with FIFO ordering and exponential backoff retry.

For non-terminal input, the successful enqueue boundary is also the accepted-input boundary. After a queue insert succeeds, core records the accepted session metadata before any typing callback, worker start, or projection-visible wakeup can observe the session. Terminal input bypasses the inbound queue, so terminal-origin freshness is recorded by the `user_prompt_submit` hook path defined in `project/spec/session-projection`.

## Canonical fields

### Table Schema

<!-- planned-change:fix-user-turn-reflection-identity-segments-r -->
```sql
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text' CHECK(message_type IN ('text', 'voice', 'file')),
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
    created_at TEXT NOT NULL,
    processed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    locked_at TEXT,
    source_message_id TEXT,
    source_channel_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status
    ON inbound_queue(session_id, status, next_retry_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup
    ON inbound_queue(origin, source_message_id) WHERE source_message_id IS NOT NULL;
```
<!-- change:fix-user-turn-reflection-identity-segments-r -->
```sql
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    text_kind TEXT NOT NULL DEFAULT 'ordinary',
    source_feature TEXT NOT NULL DEFAULT '',
    occurrence_key TEXT,
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    processed_at TEXT,
    reflected_at TEXT,
    reflection_claimed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    locked_at TEXT,
    source_message_id TEXT,
    source_channel_id TEXT,
    caller_session_id TEXT,
    caller_author_kind TEXT,
    caller_author_display TEXT,
    caller_agent_runtime TEXT,
    caller_thinking_mode TEXT,
    caller_machine_role TEXT,
    caller_job_role TEXT,
    caller_origin_prefix_len INTEGER,
    caller_origin_suffix_len INTEGER,
    binding_disposition TEXT
        CHECK(binding_disposition IN ('legacy_pre_cutover', 'input_conflict'))
);

CREATE TABLE IF NOT EXISTS accepted_turn_bindings (
    binding_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(native_runtime, native_session_id, native_entry_id)
);

CREATE TABLE IF NOT EXISTS turn_authored_parts (
    binding_id TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    original_source_session_id TEXT,
    author_kind TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_agent_runtime TEXT,
    author_thinking_mode TEXT,
    author_machine_role TEXT,
    author_job_role TEXT,
    origin_surface TEXT,
    PRIMARY KEY (binding_id, part_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS turn_receipt_envelopes (
    binding_id TEXT NOT NULL,
    inbound_queue_id INTEGER NOT NULL,
    envelope_index INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    text_kind TEXT NOT NULL,
    envelope_span_start INTEGER NOT NULL,
    envelope_span_end INTEGER NOT NULL,
    body_span_start INTEGER NOT NULL,
    body_span_end INTEGER NOT NULL,
    authored_part_id INTEGER,
    PRIMARY KEY (binding_id, inbound_queue_id, envelope_index),
    UNIQUE(inbound_queue_id, envelope_index),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS binding_conflict_candidates (
    inbound_queue_id INTEGER NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (inbound_queue_id, native_runtime, native_session_id, native_entry_id)
);

CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status
    ON inbound_queue(session_id, status, next_retry_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup
    ON inbound_queue(origin, source_message_id) WHERE source_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_accepted_turn_bindings_session
    ON accepted_turn_bindings(session_id);
CREATE INDEX IF NOT EXISTS idx_turn_receipt_envelopes_inbound
    ON turn_receipt_envelopes(inbound_queue_id);
```
<!-- /planned-change:fix-user-turn-reflection-identity-segments-r -->

<!-- planned:fix-user-turn-reflection-identity-segments-r -->
### Accepted-turn binding state

Caller-origin conversational rows carry a closed binding disposition with two
terminal values: `legacy_pre_cutover` for delivered rows that predate the
binding cutover and cannot be reconstructed truthfully, and `input_conflict`
when one accepted occurrence cannot be correlated to exactly one native entry.
Absence means the row remains eligible to bind.

The accepted-turn binding aggregate persists one runtime-qualified native-entry
root, its ordered authored parts, and the accepted receipt envelopes correlated
to those parts. Receipt envelopes retain the inbound row id, occurrence key,
accepted text kind, envelope and body spans, and authored-part id. A native
entry and an accepted occurrence each bind at most once. Binding conflicts keep
their exact native-entry candidates as durable evidence and never acquire a
guessed author.
<!-- /planned:fix-user-turn-reflection-identity-segments-r -->

### Reminder machine input

Reminder firings use the control-delivery surface and never enter this queue.
The inbound queue therefore owns conversational text, voice, and file input
only; it defines no reminder origin, message type, retry path, or turn-part
classification.

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

Delivery is not the primary UI-origin acceptance boundary. Delivery may preserve compatibility for old queued rows, but it must not be the first writer for newly accepted UI input and must never advance `last_projected_at`. Terminal input does not enter through this queue, so terminal-origin freshness is recorded by the `user_prompt_submit` hook path defined in `project/spec/session-projection`.

### Acceptance Metadata

`process_message` owns the non-terminal accepted-input metadata write. The write happens only after durable queue insert succeeds and before the queue manager invokes adapter typing callbacks or starts a drain worker.

The accepted metadata consists of:

- `last_message_sent` — operational preview of the accepted text
- `last_message_sent_at` — acceptance timestamp used by v1 origin freshness checks
- `last_input_origin` — canonical input origin (`telegram`, `discord`, `whatsapp`, `web`)
- origin metadata — typed adapter metadata persisted for the origin when provided

Acceptance code must not write `last_projected_at`. That field is projector-owned, as defined in `project/spec/session-projection`.

### Deduplication

The unique index on `(origin, source_message_id)` (where `source_message_id IS NOT NULL`) prevents duplicate enqueues. `enqueue_inbound` returns `None` on dedup skip. Dedup skips do not refresh accepted metadata; the already accepted queue row remains the source for that adapter message.

Adapters that provide stable message IDs (Discord, Telegram, WhatsApp) must pass `source_message_id`. Web/API input omits it unless the caller supplies a stable client message id. Terminal input can omit it.

### Session Lifecycle Integration

- **Session closed**: `expire_session(session_id)` cancels the worker and bulk-expires pending messages.
- **Daemon startup**: `startup()` scans for pending messages and spawns workers for non-empty sessions.
- **Daemon shutdown**: `shutdown()` cancels all workers. Messages remain in DB for next startup.

### Cleanup

<!-- planned-change:fix-user-turn-reflection-identity-segments-r -->
`cleanup_inbound(older_than_iso)` deletes rows with `status IN ('delivered', 'expired')` older than the threshold. Scheduled periodically by the maintenance service.
<!-- change:fix-user-turn-reflection-identity-segments-r -->
`cleanup_inbound(older_than_iso)` deletes expired rows older than the threshold.
A delivered row becomes cleanup-eligible only after its accepted occurrence is
bound to a runtime-qualified native entry or it carries a terminal binding
disposition. Delivered post-cutover rows with neither survive cleanup so later
projection or recovery can bind them. The maintenance service schedules the
cleanup periodically.
<!-- /planned-change:fix-user-turn-reflection-identity-segments-r -->

### Adapter Contract

Adapters enqueue via `InboundQueueManager.enqueue(...)` and return immediately. After a successful enqueue, adapters show a platform-native typing indicator. Adapters must not contain delivery logic or mutate session origin fields directly; they pass origin metadata into the queue and core records accepted state at the successful enqueue boundary, before adapter-visible side effects.

## See Also

- docs/project/spec/session-projection.md
