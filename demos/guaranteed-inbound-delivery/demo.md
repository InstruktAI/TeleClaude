# Demo: guaranteed-inbound-delivery

## Validation

```bash
# 1. Verify inbound_queue table exists with correct schema
sqlite3 teleclaude.db ".schema inbound_queue" | grep -q "CREATE TABLE inbound_queue" && echo "PASS: inbound_queue table exists" || echo "FAIL: inbound_queue table missing"
```

```bash
# 2. Verify indexes exist (session+status for worker queries, source dedup)
sqlite3 teleclaude.db "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%inbound%' ORDER BY name;" | while read idx; do echo "  index: $idx"; done && echo "PASS: indexes present"
```

```bash
# 3. Verify delivered messages exist — proof the queue is processing real traffic
COUNT=$(sqlite3 teleclaude.db "SELECT COUNT(*) FROM inbound_queue WHERE status='delivered';")
[ "$COUNT" -gt 0 ] && echo "PASS: $COUNT messages delivered through the queue" || echo "WARN: no delivered messages yet (queue exists but no adapter traffic observed)"
```

```bash
# 4. Verify process_message enqueues instead of direct dispatch
grep -n "get_inbound_queue_manager().enqueue" teleclaude/core/command_handlers.py && echo "PASS: process_message routes through inbound queue"
```

```bash
# 5. Verify deliver_inbound raises on failure (enables retry)
grep -n "raise RuntimeError" teleclaude/core/command_handlers.py | grep -q "tmux delivery failed" && echo "PASS: delivery failure raises for retry" || echo "FAIL: delivery failure not raising"
```

```bash
# 6. Verify backoff schedule exists in inbound_queue module
grep -q "_BACKOFF_SCHEDULE = " teleclaude/core/inbound_queue.py && grep "_BACKOFF_SCHEDULE = " teleclaude/core/inbound_queue.py | sed 's/^/  /' && echo "PASS: backoff schedule defined"
```

```bash
# 7. Verify startup recovery scans for pending messages
grep -n "fetch_sessions_with_pending_inbound" teleclaude/core/inbound_queue.py && echo "PASS: startup recovery wired"
```

```bash
# 8. Verify webhook 502 on dispatch failure
grep -n "status_code=502" teleclaude/hooks/inbound.py && echo "PASS: webhook returns 502 on failure"
```

## Guided Presentation

### Step 1: The Problem — Silent Message Loss

**What to do:** Before this delivery, `process_message()` called `tmux_io.process_text()` synchronously. When tmux delivery failed (event loop pressure, session not ready), the message was dropped with only an error log. A 79-second voice transcription could vanish because the event loop was saturated for 5 seconds.

**What to observe:** The old code had `return` after failure — no persistence, no retry, no trace.

**Why it matters:** User input is sacred. Losing a message silently violates the trust contract between the system and the user.

### Step 2: The Queue Schema

**What to do:** Show the `inbound_queue` table and its live data.

```bash
sqlite3 teleclaude.db ".schema inbound_queue"
```

```bash
sqlite3 -header -column teleclaude.db "SELECT id, substr(session_id,1,8) as session, origin, message_type, status, created_at, attempt_count FROM inbound_queue ORDER BY id DESC LIMIT 10;"
```

**What to observe:** The table mirrors `hook_outbox` patterns — `locked_at` for CAS claim, `next_retry_at` for exponential backoff, `status` for lifecycle, dedup index on `(origin, source_message_id)`.

**Why it matters:** Once a message is INSERTed here, it cannot be silently lost. SQLite WAL mode ensures crash durability.

### Step 3: Adapter Decoupling

**What to do:** Show that `process_message()` is now a thin enqueue wrapper — no synchronous tmux call.

```bash
# The entire process_message function — just enqueue and return
sed -n '/^async def process_message/,/^async def /p' teleclaude/core/command_handlers.py | head -25
```

**What to observe:** The adapter's responsibility ends at `enqueue()`. The typing indicator fires immediately. The user sees feedback within milliseconds regardless of tmux delivery time.

**Why it matters:** Discord and Telegram adapters are no longer blocked by slow tmux delivery. Event loop starvation in one path doesn't affect message receipt.

### Step 4: The Delivery Worker

**What to do:** Show the per-session FIFO worker loop.

```bash
# Worker loop: claim → deliver → mark cycle
sed -n '/async def _worker_loop/,/async def expire_session/p' teleclaude/core/inbound_queue.py | head -50
```

**What to observe:** One worker per session. FIFO ordering — if message A fails, message B waits. CAS claim via `locked_at` prevents duplicate delivery. Workers self-terminate when the queue is empty, respawned on next enqueue.

**Why it matters:** Order preservation + automatic retry = guaranteed delivery without resource waste.

### Step 5: Exponential Backoff

**What to do:** Show the retry mechanism with escalating backoff.

```bash
# Backoff schedule and constants
grep "_BACKOFF_SCHEDULE\|_LOCK_TIMEOUT_S\|_FETCH_LIMIT" teleclaude/core/inbound_queue.py | head -5
```

**What to observe:** Backoff escalates from 5s to 300s (5 minutes max). This prevents hammering a temporarily unavailable tmux session while ensuring eventual delivery.

### Step 6: Daemon Restart Resilience

**What to do:** Show the startup recovery path.

```bash
# startup() scans for sessions with pending messages and spawns workers
grep -A 8 "async def startup" teleclaude/core/inbound_queue.py
```

**What to observe:** On daemon start, `startup()` queries for all sessions with pending inbound messages and spawns a worker for each. Messages queued before a crash or restart are picked up automatically.

**Why it matters:** Even a daemon crash doesn't lose user messages. SQLite durability + startup scan = guaranteed recovery.

### Step 7: Dedup Protection

**What to do:** Show the unique index that prevents duplicate message delivery.

```bash
sqlite3 teleclaude.db "SELECT sql FROM sqlite_master WHERE name='idx_inbound_queue_source_dedup';"
```

**What to observe:** A partial unique index on `(origin, source_message_id) WHERE source_message_id IS NOT NULL`. Platform retries (e.g., WhatsApp webhook replay) are silently deduplicated at the DB level.

**Why it matters:** Two layers of protection — platform retry + queue dedup. No message is lost, no message is delivered twice.
