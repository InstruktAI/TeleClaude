---
id: 'project/spec/inbound-queue'
type: 'spec'
scope: 'project'
description: 'Architecture, schema, worker design, and retry policy for the durable inbound message queue.'
---

# Inbound Queue — Spec

## Overview

The inbound queue provides guaranteed delivery of user messages to their agent sessions. Adapters enqueue messages and return immediately. A per-session worker drains the queue, delivering messages to the tmux session with FIFO ordering and exponential backoff retry.

## Table Schema

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

## Worker Design

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

## Retry Policy

Exponential backoff: `[5, 10, 20, 40, 80, 160, 300]` seconds. Index is `min(attempt_count, len-1)`. No maximum retry count — messages are retried indefinitely until delivered or the session is closed.

Lock timeout: 5 minutes. Rows locked longer than this are reclaimable (handles worker crash/restart).

## Delivery Function

`deliver_inbound(row, client, start_polling)` in `command_handlers.py`:

1. Fetch session from DB — raises if not found
2. Startup gate: wait up to 15s for session to exit `initializing` — raises on timeout
3. Headless adoption: if `lifecycle_status == 'headless'`, adopt a tmux session
4. Break threaded output if enabled
5. Update session metadata: `last_message_sent`, `last_input_origin`
6. Broadcast user input to other adapters
7. Wrap text with bracketed paste, send via `tmux_io.process_text`
8. On `process_text` returning False: raise `RuntimeError` (triggers retry)
9. On success: update `last_activity`, start polling

## Deduplication

The unique index on `(origin, source_message_id)` (where `source_message_id IS NOT NULL`) prevents duplicate enqueues. `enqueue_inbound` returns `None` on dedup skip.

Adapters that provide stable message IDs (Discord, Telegram) must pass `source_message_id`. Terminal input can omit it.

## Session Lifecycle Integration

- **Session closed**: `expire_session(session_id)` cancels the worker and bulk-expires pending messages.
- **Daemon startup**: `startup()` scans for pending messages and spawns workers for non-empty sessions.
- **Daemon shutdown**: `shutdown()` cancels all workers. Messages remain in DB for next startup.

## Cleanup

`cleanup_inbound(older_than_iso)` deletes rows with `status IN ('delivered', 'expired')` older than the threshold. Scheduled periodically by the maintenance service.

## Adapter Contract

Adapters enqueue via `InboundQueueManager.enqueue(...)` and return immediately. After a successful enqueue, adapters show a platform-native typing indicator. Adapters must not contain delivery logic.
