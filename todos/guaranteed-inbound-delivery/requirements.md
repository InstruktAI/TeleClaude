# Requirements: guaranteed-inbound-delivery

## Goal

Guarantee that user messages are never silently lost. Replace the current synchronous, best-effort adapter→tmux delivery chain with a durable, adapter-agnostic inbound queue backed by SQLite. Adapters enqueue and return immediately; core drains the queue and delivers to the agent with retry on failure.

## In scope

- **Core inbound queue** — new `inbound_queue` SQLite table with per-session FIFO ordering, CAS-based claim locking, exponential backoff retry, and cleanup lifecycle.
- **Queue worker** — per-session `asyncio.create_task()` workers that drain the queue. Spawned on-demand when a message is enqueued; self-terminate when queue is empty. Worker registry prevents duplicates.
- **Adapter decoupling** — Discord, Telegram, and terminal adapters enqueue via core API instead of dispatching `ProcessMessageCommand` synchronously. Session resolution stays in the adapter (fast DB lookup). Delivery moves to the queue worker.
- **`process_message` extraction** — the delivery logic currently in `command_handlers.py:961-1053` is extracted into a `_deliver_inbound()` method called by the queue worker. The command handler becomes a thin enqueue call.
- **Inbound webhook fix** — `teleclaude/hooks/inbound.py` returns 5xx (not 200) on dispatch failure, enabling platform-level retries for WhatsApp and future webhook integrations.
- **Typing indicator on journal** — adapters show a platform-native typing indicator immediately after successful enqueue, bridging the gap between receipt and delivery.
- **Voice message durability** — voice messages are enqueued with `payload_json` containing the source URL (Discord CDN or Telegram `file_id`). Fast path: transcribe inline, enqueue text. Durable path: enqueue voice payload, worker transcribes on delivery.
- **Performance fixes on the delivery path** — remove redundant `session_exists` call in `send_keys_existing_tmux` (`tmux_bridge.py:486`); move `psutil` calls to `asyncio.to_thread()` in `session_exists`; review the `asyncio.sleep(1.0)` gap in `_send_keys_tmux`.
- **Database methods** — follow `hook_outbox` patterns: `enqueue_inbound`, `claim_inbound`, `mark_inbound_delivered`, `mark_inbound_failed`, `fetch_inbound_pending`, `cleanup_inbound`.
- **Documentation** — inbound queue spec (`docs/project/spec/inbound-queue.md`), adapter boundaries update.

## Out of scope

- Notification service (autonomous outbound event processing — separate todo).
- `command_retry` decorator changes for outbound Telegram operations (independent concern).
- Telegram long-polling → webhook mode migration (future work; the queue protects messages regardless of adapter ACK model).
- Cross-session message ordering (only per-session FIFO is guaranteed).
- UX typing indicator spec document (can be authored separately; the code change is in scope).

## Success Criteria

- [ ] No user message is silently dropped when tmux delivery fails — failed messages are retried with exponential backoff until delivered or the session is closed.
- [ ] Adapter message handlers return within milliseconds of receiving a message (enqueue is O(1) DB insert, not a synchronous tmux call chain).
- [ ] Messages for the same session are delivered in insertion order (FIFO). A failed message blocks subsequent messages for that session until delivered.
- [ ] Messages for different sessions are delivered independently and in parallel.
- [ ] On daemon restart, pending messages in the queue survive and are retried.
- [ ] Voice messages are recoverable on retry via stored source URL in `payload_json`.
- [ ] The inbound webhook handler returns non-200 on dispatch failure, enabling platform retries.
- [ ] Typing indicator appears on the user's platform within 100ms of message receipt.
- [ ] Existing tests pass; new tests cover enqueue, claim, deliver, retry, dedup, and session-close expiry paths.

## Constraints

- Must use existing SQLite database (single-database policy). No new database files.
- Must follow `hook_outbox` patterns for consistency (schema, CAS claim, backoff).
- Adapter boundary policy: adapters must not contain delivery logic — only enqueue + typing indicator.
- The queue worker must run as `asyncio.create_task()` — no separate processes, no threads for the worker itself.
- Voice re-transcription on retry is acceptable (idempotent, expensive but correct).
- Discord CDN URLs expire after ~24h. For Discord voice, prefer fast-path transcription; fall back to stored audio file path.

## Risks

- **Event loop pressure during retry storms**: if many messages fail simultaneously, retry workers could saturate the event loop. Mitigation: per-session workers process one message at a time; global concurrency is bounded by active session count.
- **SQLite write contention**: high-volume enqueue + claim + mark operations on a single table. Mitigation: WAL mode is already enabled; busy_timeout is 5000ms; queue operations are simple row-level updates.
- **Voice source URL expiry**: Discord CDN URLs expire. Mitigation: fast-path transcription preferred; `payload_json` stores both CDN URL and local file path when available.
