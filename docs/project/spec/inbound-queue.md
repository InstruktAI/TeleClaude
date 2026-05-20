---
description: 'Architecture, schema, worker design, and retry policy for the durable inbound message queue.'
id: 'project/spec/inbound-queue'
scope: 'project'
type: 'spec'
visibility: 'public'
status: 'actual'
---

# Inbound Queue — Spec

## What it is

The inbound queue provides guaranteed delivery of user messages to their agent sessions. Adapters enqueue messages and return immediately. A per-session worker drains the queue, delivering messages to the tmux session with FIFO ordering and exponential backoff retry.

For non-terminal input, the successful enqueue boundary is also the accepted-input boundary. After a queue insert succeeds, core records the accepted session metadata before any typing callback, worker start, or projection-visible wakeup can observe the session. Terminal input bypasses the inbound queue, so terminal-origin freshness is recorded by the `user_prompt_submit` hook path defined in `project/spec/session-projection`.

## Canonical fields

### Table Schema

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

### Delivery Function

`deliver_inbound(row, client, start_polling)` in `command_handlers.py`:

1. Fetch session from DB — raises if not found
2. Startup gate: wait up to 15s for session to exit `initializing` — raises on timeout
3. Headless adoption: if `lifecycle_status == 'headless'`, adopt a tmux session
4. For legacy rows accepted before enqueue-time metadata existed, idempotently fill missing accepted input metadata before any projection-visible wakeup: `last_message_sent`, `last_message_sent_at`, `last_input_origin`
5. Drop pending adapter QoS output if needed; this is delivery cleanup only, not projection truth
6. Wrap text with bracketed paste, send via `tmux_io.process_text`
7. On `process_text` returning False: raise `RuntimeError` (triggers retry)
8. On success: update `last_activity`, start polling

Delivery is not the primary UI-origin acceptance boundary. Delivery may preserve compatibility for old queued rows, but it must not be the first writer for newly accepted UI input and must never advance `last_projected_at`.

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

`cleanup_inbound(older_than_iso)` deletes rows with `status IN ('delivered', 'expired')` older than the threshold. Scheduled periodically by the maintenance service.

### Adapter Contract

Adapters enqueue via `InboundQueueManager.enqueue(...)` and return immediately. After a successful enqueue, adapters show a platform-native typing indicator. Adapters must not contain delivery logic or mutate session origin fields directly; they pass origin metadata into the queue and the core acceptance path records accepted state before adapter-visible side effects.

## See Also

- docs/project/spec/session-projection.md
