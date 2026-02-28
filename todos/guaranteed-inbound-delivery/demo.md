# Demo: guaranteed-inbound-delivery

## Validation

```bash
# 1. Verify inbound_queue table exists in the database
sqlite3 data/teleclaude.db ".schema inbound_queue"
```

```bash
# 2. Run the test suite to confirm all queue operations work
make test
```

```bash
# 3. Verify no lint issues
make lint
```

```bash
# 4. Check that pending messages survive daemon restart
# (Enqueue a message, restart, verify it gets delivered)
sqlite3 data/teleclaude.db "SELECT COUNT(*) FROM inbound_queue WHERE status='pending'"
```

## Guided Presentation

### Step 1: The Problem — Silent Message Loss

**What to do:** Show the original failure path in `command_handlers.py` (before this change). Explain that when `tmux_io.process_text()` returned False, the message was dropped with only an error log.

**What to observe:** The old code at `command_handlers.py:1042-1045` had `return` after failure — no persistence, no retry.

**Why it matters:** User input is sacred. A 79-second voice message can vanish because the event loop was saturated for 5 seconds.

### Step 2: The Queue Schema

**What to do:** Show the `inbound_queue` table schema.

```bash
sqlite3 data/teleclaude.db ".schema inbound_queue"
```

**What to observe:** The table mirrors `hook_outbox` patterns — `locked_at` for CAS claim, `next_retry_at` for backoff, `status` for lifecycle, `source_message_id` for dedup.

**Why it matters:** This is the durable foundation. Once a message is INSERTed here, it cannot be silently lost.

### Step 3: Adapter Decoupling

**What to do:** Show a Discord/Telegram message handler. Point out that it enqueues and returns immediately — no synchronous tmux call.

**What to observe:** The adapter's responsibility ends at `enqueue()`. The typing indicator fires immediately after. The user sees "typing..." within milliseconds.

**Why it matters:** Adapters are no longer blocked by slow tmux delivery. Event loop starvation in one path doesn't affect message receipt.

### Step 4: The Delivery Worker

**What to do:** Show `InboundQueueManager._worker_loop()`. Walk through the claim → deliver → mark cycle.

**What to observe:** Per-session FIFO ordering. One worker per session. If message A fails, message B waits — no leapfrogging. Workers self-terminate when the queue is empty.

**Why it matters:** Order preservation + automatic retry = guaranteed delivery.

### Step 5: Retry Under Failure

**What to do:** Demonstrate a failed delivery and the retry mechanism.

```bash
# Check retry state in the queue
sqlite3 data/teleclaude.db \
  "SELECT id, session_id, status, attempt_count, next_retry_at, last_error FROM inbound_queue WHERE status='failed' LIMIT 5"
```

**What to observe:** Failed messages have `attempt_count > 0`, a scheduled `next_retry_at` with exponential backoff, and `last_error` showing the failure reason.

**Why it matters:** Transient failures (tmux timeout, event loop pressure) are automatically recovered. No user intervention needed.

### Step 6: Daemon Restart Resilience

**What to do:** Show that the queue survives daemon restart — pending messages are picked up by `startup()`.

**What to observe:** After restart, workers are spawned for sessions with pending messages. Messages queued before shutdown are delivered after startup.

**Why it matters:** Even a daemon crash doesn't lose user messages. SQLite durability guarantees survival.

### Step 7: Webhook Error Response Fix

**What to do:** Show the inbound webhook handler now returns 5xx on dispatch failure (was 200).

**What to observe:** Platforms that retry on error (WhatsApp) will get a second chance. The queue provides dedup via `source_message_id` to handle replays.

**Why it matters:** Two layers of protection — platform retry + core queue retry.
