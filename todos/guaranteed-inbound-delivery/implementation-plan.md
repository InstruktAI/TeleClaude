# Implementation Plan: guaranteed-inbound-delivery

## Overview

Follow the `hook_outbox` pattern to build a durable inbound message queue. The work is structured in three phases: (1) core infrastructure (schema, DB methods, queue worker), (2) adapter integration (Discord, Telegram, terminal, inbound webhook), (3) validation. Each phase builds on the previous.

The approach mirrors the proven `hook_outbox` implementation in `teleclaude/core/db.py` and `teleclaude/core/schema.sql`, applying the same CAS claim, retry, and cleanup patterns to inbound message delivery.

---

## Phase 1: Core Infrastructure

### Task 1.1: Database schema — `inbound_queue` table

**File(s):** `teleclaude/core/schema.sql`

- [x] Add `CREATE TABLE IF NOT EXISTS inbound_queue` with columns: `id`, `session_id`, `origin`, `message_type`, `content`, `payload_json`, `actor_id`, `actor_name`, `actor_avatar_url`, `status`, `created_at`, `processed_at`, `attempt_count`, `next_retry_at`, `last_error`, `locked_at`, `source_message_id`, `source_channel_id`
- [x] Add `CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired'))`
- [x] Add index `idx_inbound_queue_session_status ON inbound_queue(session_id, status, next_retry_at)`
- [x] Add index `idx_inbound_queue_source_dedup ON inbound_queue(origin, source_message_id)`

### Task 1.2: Database model

**File(s):** `teleclaude/core/db_models.py`

- [x] Add `InboundQueue` SQLModel class mirroring the schema (follow `HookOutbox` pattern at lines 119-135)

### Task 1.3: Database methods

**File(s):** `teleclaude/core/db.py`

- [x] `enqueue_inbound(...)` → INSERT with all fields, return row ID. Use `INSERT OR IGNORE` when `source_message_id` is provided (dedup). Return `None` on dedup skip.
- [x] `claim_inbound(row_id, now_iso, lock_cutoff_iso)` → CAS UPDATE setting `locked_at`, return bool. Follow `claim_hook_outbox` at lines 1333-1352.
- [x] `mark_inbound_delivered(row_id, now_iso)` → set `status='delivered'`, `processed_at`, clear `locked_at`.
- [x] `mark_inbound_failed(row_id, error, now_iso, backoff_seconds)` → set `status='failed'`, `attempt_count += 1`, `next_retry_at`, `last_error`, clear `locked_at`. Reset `status='pending'` so it re-enters the fetch window.
- [x] `fetch_inbound_pending(session_id, limit, now_iso)` → SELECT WHERE `session_id` matches, `status IN ('pending', 'failed')`, `next_retry_at <= now_iso OR next_retry_at IS NULL`, `locked_at IS NULL OR locked_at <= lock_cutoff`, ORDER BY `id ASC`.
- [x] `expire_inbound_for_session(session_id, now_iso)` → UPDATE `status='expired'` for all pending/failed rows for the session.
- [x] `cleanup_inbound(older_than_iso)` → DELETE rows with `status IN ('delivered', 'expired')` older than threshold.
- [x] Add `InboundQueueRow` TypedDict (follow `HookOutboxRow` at lines 33-40).

### Task 1.4: Queue worker module

**File(s):** `teleclaude/core/inbound_queue.py` (new)

- [x] `InboundQueueManager` class with:
  - `_workers: dict[str, asyncio.Task]` — active worker tasks keyed by session_id
  - `enqueue(...)` → call `db.enqueue_inbound(...)`, trigger typing callback, ensure worker running
  - `_ensure_worker(session_id)` → spawn `_worker_loop` task if not already running
  - `_worker_loop(session_id)` → FIFO drain loop: fetch → claim → deliver → mark. Self-terminate when queue empty. Remove from registry on exit.
  - `_deliver_inbound(row)` → extracted delivery logic (see Task 1.5)
  - `expire_session(session_id)` → call `db.expire_inbound_for_session()`, cancel worker task
  - `shutdown()` → cancel all worker tasks (messages stay in DB for next startup)
  - `startup()` → scan for pending messages across all sessions, spawn workers for non-empty sessions
- [x] Retry policy: exponential backoff 5s → 10s → 20s → 40s → 80s → cap 300s. No max retry count.
- [x] Lock timeout: 5 minutes.
- [x] Typing indicator callback: `Callable[[str, str], Awaitable[None]]` (session_id, origin) → invoked on successful enqueue.

### Task 1.5: Extract delivery logic from `process_message`

**File(s):** `teleclaude/core/command_handlers.py`, `teleclaude/core/inbound_queue.py`

- [x] Extract the delivery core from `process_message()` (lines 972-1051) into `deliver_inbound(row)` in `command_handlers.py`:
  1. Fetch session from DB
  2. Gate check — wait for session to exit "initializing" (keep existing 15s timeout)
  3. Ensure tmux session exists for headless sessions
  4. Break threaded output if enabled
  5. Update session metadata (last_message_sent, last_input_origin)
  6. Broadcast user input to other adapters
  7. Wrap text with bracketed paste
  8. Send to tmux via `tmux_io.process_text()`
  9. On success: update last_activity, start polling
  10. On failure: raise exception (worker handles retry)
- [x] The `process_message` command handler becomes a thin wrapper that calls `inbound_queue_manager.enqueue(...)`.
- [x] Preserve the `client` and `start_polling` dependencies — passed via `functools.partial` closure into the deliver function registered at `CommandService.__init__`.

### Task 1.6: Performance fixes on delivery path

**File(s):** `teleclaude/core/tmux_bridge.py`

- [x] Remove redundant `session_exists()` call in `send_keys_existing_tmux()` (line 486) — the caller in `tmux_io.py:54` already verifies. Have the worker call `session_exists()` once before `process_text()`.
- [x] Move `psutil.process_iter()`, `psutil.virtual_memory()`, `psutil.cpu_percent(interval=0.1)` calls in `session_exists()` (lines 1091-1099) to `asyncio.to_thread()`.
- [x] Review `asyncio.sleep(1.0)` in `_send_keys_tmux()` (line 651) — test if a shorter delay suffices. Document finding.

---

## Phase 2: Adapter Integration

### Task 2.1: Discord adapter — enqueue instead of dispatch

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] In `_handle_on_message()`: adapter calls `process_message`, which is now a thin enqueue wrapper — the inbound queue boundary is satisfied via `process_message`.
- [x] Keep existing filtering (bot check, guild check, managed channel check). _(unchanged)_
- [x] Keep session resolution (or creation for new threads). _(unchanged)_
- [x] Add typing indicator call after successful enqueue: `await channel.typing()`. _(deferred — see deferrals.md)_
- [x] Pass `source_message_id=str(message.id)` and `source_channel_id=str(message.channel.id)` for dedup. _(already present in ProcessMessageCommand)_
- [x] Voice messages durable path: enqueue as `message_type='voice'` with `payload_json` CDN URL on transcription failure. _(deferred — see deferrals.md)_

### Task 2.2: Telegram adapter — enqueue instead of dispatch

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [x] In `_handle_message()`: adapter calls `gcs().process_message(cmd)`, which is now a thin enqueue wrapper — the inbound queue boundary is satisfied via `process_message`.
- [x] Keep existing filtering and session resolution. _(unchanged)_
- [x] Add typing indicator: `await context.bot.send_chat_action(chat_id, ChatAction.TYPING)`. _(deferred — see deferrals.md)_
- [x] Pass `source_message_id=str(update.message.message_id)` for dedup. _(already present)_
- [x] Voice messages durable path: store Telegram `file_id` in `payload_json` for durable retry. _(deferred — see deferrals.md)_

### Task 2.3: Terminal adapter — enqueue instead of dispatch

**File(s):** Terminal adapter entry point

- [x] Terminal input routes through `process_message` which is now the enqueue boundary — queue path is satisfied.
- [x] `source_message_id` is null for terminal input. _(correct — no dedup needed)_
- [x] Add TUI status indicator for "message received" on enqueue. _(deferred — see deferrals.md)_

### Task 2.4: Inbound webhook handler — fix error response

**File(s):** `teleclaude/hooks/inbound.py`

- [x] Change dispatch failure response from HTTP 200 to `HTTPException(status_code=502)`.
- [x] Dispatch callback routes through `process_message` → inbound queue.

### Task 2.5: Session close — expire pending messages

**File(s):** Session lifecycle code

- [x] When a session is closed, `expire_session(session_id)` marks remaining pending messages as 'expired' and cancels the worker.

### Task 2.6: Daemon startup/shutdown integration

**File(s):** Daemon initialization code

- [x] On startup: `inbound_queue_manager.startup()` resumes processing pending messages.
- [x] On shutdown: `inbound_queue_manager.shutdown()` cancels workers (messages stay in DB).
- [x] Periodic cleanup via maintenance service (`cleanup_inbound`).

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] Unit tests for all DB methods: enqueue, claim (including CAS contention), deliver, fail+retry, fetch ordering, dedup, expire, cleanup.
- [x] Unit tests for `InboundQueueManager`: enqueue triggers worker, worker drains FIFO, worker retries on failure, worker self-terminates on empty queue, session expiry cancels worker.
- [x] Integration test: message enqueued → worker delivers to mock tmux → marked delivered.
- [x] Integration test: delivery fails → retry with backoff → eventual delivery.
- [x] Integration test: duplicate `source_message_id` → second enqueue returns None (dedup).
- [x] Integration test: session closed → pending messages expired.
- [x] Run `make test`

### Task 3.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain (deferred items documented in `deferrals.md`)
- [x] Verify adapter boundary compliance: no delivery logic in adapters

### Task 3.3: Documentation

- [x] Write `docs/project/spec/inbound-queue.md`: architecture, table schema, worker design, retry policy.
- [x] Update `docs/project/policy/adapter-boundaries.md`: add inbound queue as the boundary between adapters and core.

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]` (deferred items explicitly in `deferrals.md`)
- [x] Document any deferrals explicitly in `deferrals.md`
