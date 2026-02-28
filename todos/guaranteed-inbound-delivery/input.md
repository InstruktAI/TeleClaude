# Input: guaranteed-inbound-delivery

<!-- Converged design from debugging + brainstorm session (breath cycle: inhale/hold/exhale). Session ee6b59d3 (Feb 28 2026). -->

## Problem

User input can be silently lost. When a Discord voice message was transcribed and delivered to the agent via `tmux send-keys`, the tmux subprocess timed out after 5 seconds. The error path in `command_handlers.py:1042-1045` responded with "Failed to send command to tmux" to the user and **dropped the message**. No retry, no persistence, no recovery. A 79-second voice message — user intent — gone.

This is not a tmux problem. The tmux server is fine (7ms response when tested directly). The 5-second hang was caused by asyncio event loop starvation: slow Telegram API calls (3-13s per `edit_message`), hook outbox queue backlog (depth 0→19), and a synchronous `await` chain from adapter through to tmux. The `asyncio.wait_for()` timeout couldn't fire precisely because the event loop was saturated.

The root cause is architectural: the adapter-to-agent delivery path is synchronous and best-effort. Every adapter (`on_message` handler) awaits the entire chain — session resolution, Telegram broadcasting, tmux send-keys — in a single coroutine. Any stall in that chain blocks the caller. Any failure at the end drops the message.

User input is sacred. It cannot be best-effort. It must be guaranteed delivery.

## Core Concept

A **core inbound queue** — adapter-agnostic, durable, per-session FIFO — that decouples message receipt from message delivery. Adapters enqueue and return immediately. Core drains the queue and delivers to the agent. If delivery fails, the queue retries. If the daemon restarts, the queue survives. The message is never lost.

This is the same pattern as the existing `hook_outbox` (outbound event delivery) applied in reverse to inbound message delivery. The outbox already proves the pattern works at scale.

### What this IS

- A core infrastructure concern — lives in `teleclaude/core/`, not in any adapter
- Adapter-agnostic — Discord, Telegram, terminal, WhatsApp, future adapters all benefit
- A durable SQLite-backed queue with per-session FIFO ordering
- A decoupling layer that makes `send_keys` non-blocking to callers
- The mechanism that makes typing indicator possible (journal receipt = "I received your message")

### What this is NOT

- Not the notification service (that's autonomous event processing, outbound signal pipe)
- Not a message broker (no pub/sub, no routing — just durable delivery to one target: the agent)
- Not adapter-specific (the Discord research agent proposed a `discord_ingress` table — wrong layer)

## Architecture

### The flow today (broken)

```
Adapter on_message
  → await resolve_session()
  → await broadcast_user_input()     ← Telegram API call, 3-13s
  → await tmux_io.process_text()     ← tmux send-keys, can timeout
  → if not success: drop message     ← USER INPUT LOST
```

### The flow after (guaranteed)

```
Adapter on_message
  → INSERT INTO inbound_queue (status='pending')    ← DURABLE, instant
  → adapter callback: show typing indicator          ← UX signal: "received"
  → return                                           ← adapter is free

Core queue worker (per-session, FIFO)
  → claim row (locked_at CAS)
  → resolve_session()
  → broadcast_user_input()
  → tmux_io.process_text()
  → success → mark 'delivered'
  → failure → mark 'failed', exponential backoff → retry
```

The adapter's job ends the moment the message is persisted. The core's job begins there. The typing indicator bridges the gap.

### Why this naturally fixes the performance bottlenecks

The performance issues found during investigation are all symptoms of the synchronous chain:

1. **Redundant `session_exists` checks** — `tmux_io.py:54` calls it, then `send_keys_existing_tmux` calls it again at `tmux_bridge.py:486`. Two tmux subprocesses for one operation. The queue worker can call it once.

2. **Blocking `psutil` calls in async context** — `psutil.process_iter()`, `psutil.virtual_memory()`, `psutil.cpu_percent(interval=0.1)` run synchronously in `session_exists` at `tmux_bridge.py:1091-1099`. These block the event loop for 100-300ms. The queue worker can use `asyncio.to_thread()`.

3. **`asyncio.sleep(1.0)` in `_send_keys_tmux`** — burns 1s between text and Enter at `tmux_bridge.py:651`. Invisible to the adapter because the adapter already returned.

4. **Event loop starvation** — slow Telegram calls held the event loop, preventing `asyncio.wait_for()` from enforcing the 5s timeout precisely. With the queue worker running as its own `asyncio.create_task()`, it operates independently of adapter I/O pressure.

5. **Hook outbox queue stall** — serial processing of outbox items behind slow Telegram calls. Not directly related to inbound delivery, but the decoupling means inbound delivery no longer competes for event loop time with outbound operations.

## Inbound Queue Design

### Table: `inbound_queue`

```sql
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,                    -- 'discord', 'telegram', 'terminal', 'whatsapp'
    message_type TEXT NOT NULL DEFAULT 'text', -- 'text', 'voice', 'file', 'keys'
    content TEXT,                             -- text content or transcribed voice
    payload_json TEXT,                        -- attachment metadata, voice file reference, etc.
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
    created_at TEXT NOT NULL,                -- ISO8601 when adapter received the message
    processed_at TEXT,                       -- ISO8601 when delivery succeeded
    attempt_count INTEGER DEFAULT 0,
    next_retry_at TEXT,                      -- ISO8601, for exponential backoff
    last_error TEXT,
    locked_at TEXT,                          -- CAS locking for concurrent worker safety
    source_message_id TEXT,                  -- adapter-specific message ID for dedup
    source_channel_id TEXT                   -- adapter-specific channel/thread ID
);

CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status
    ON inbound_queue(session_id, status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup
    ON inbound_queue(origin, source_message_id);
```

### Key design decisions

- **`session_id` is required** — the adapter resolves the session BEFORE enqueueing. Session resolution is fast (DB lookup) and doesn't involve tmux. If session resolution fails (unknown channel, new customer), that's handled at the adapter level before the queue.

- **`source_message_id` for deduplication** — Discord RESUME replays, Telegram update replays, and REST API backfill can all produce duplicate messages. The `(origin, source_message_id)` index enables `INSERT OR IGNORE` semantics. Not a UNIQUE constraint — terminal input has no source message ID.

- **`payload_json` for voice/file recovery** — voice messages store the Discord CDN URL or Telegram `file_id` here. On retry, the worker can re-download the audio and re-transcribe. The operation is idempotent — same audio produces same text. Expensive on retry (another Whisper call), but correct.

- **`message_type` distinguishes processing paths** — text messages go directly to `tmux send-keys`. Voice messages need transcription first. File messages need download + formatting. The queue worker dispatches by type.

- **Per-session FIFO ordering** — the queue worker processes messages for a session in insertion order. If message A fails, message B for the same session waits. Messages for different sessions process independently and in parallel. This is the same pattern as the existing hook outbox workers.

### DB methods (following hook_outbox patterns)

```python
async def enqueue_inbound(self, *, session_id, origin, message_type, content, payload_json,
                          actor_id, actor_name, actor_avatar_url, source_message_id,
                          source_channel_id, now_iso) -> int | None

async def claim_inbound(self, row_id, now_iso, lock_cutoff_iso) -> bool

async def mark_inbound_delivered(self, row_id, now_iso) -> None

async def mark_inbound_failed(self, row_id, error, now_iso, backoff_seconds) -> None

async def fetch_inbound_pending(self, session_id, limit, now_iso) -> list[Row]

async def cleanup_inbound(self, older_than_iso) -> int
```

### Retry policy

- Exponential backoff: 5s → 10s → 20s → 40s → 80s → capped at 300s (5 min)
- No max retry count — retry forever until delivered or session is closed
- On session close: mark remaining pending messages as 'expired'
- Lock timeout: 5 minutes (if a worker crashes mid-processing, another worker can reclaim)

## Queue Worker Design

### Per-session workers

One queue worker task per session with pending messages. Workers are spawned on-demand when a message is enqueued and self-terminate when the session's queue is drained.

```python
async def _inbound_worker(self, session_id: str) -> None:
    """Drain inbound queue for one session, FIFO."""
    while True:
        rows = await db.fetch_inbound_pending(session_id, limit=1, now_iso=now())
        if not rows:
            break  # queue drained, worker exits

        row = rows[0]
        if not await db.claim_inbound(row.id, now(), lock_cutoff()):
            continue  # another worker claimed it

        try:
            await self._deliver_inbound(row)
            await db.mark_inbound_delivered(row.id, now())
        except Exception as exc:
            await db.mark_inbound_failed(row.id, str(exc), now(), backoff=5.0)
            await asyncio.sleep(row.backoff)  # wait before next attempt
```

### The `_deliver_inbound` method

This is the extracted core of the current `process_message` command handler. It:

1. Gets the session from DB
2. Handles voice: if `message_type == 'voice'` and `content` is empty, re-download from `payload_json` URL and transcribe
3. Wraps text in bracketed paste via `tmux_io.wrap_bracketed_paste()`
4. Calls `tmux_io.process_text()` — the actual `send-keys`
5. On success: starts polling, updates last_activity
6. On failure: raises, letting the worker mark it failed for retry

### Worker lifecycle

- Workers are spawned as `asyncio.create_task()` — fire and forget, runs independently of the adapter
- A registry tracks active workers per session to avoid duplicates
- When a new message is enqueued, check if a worker exists for that session; if not, spawn one
- Workers self-terminate when the queue is empty
- On daemon shutdown: cancel all workers (messages remain in queue for next startup)

## Adapter Changes

### What adapters do now

Each adapter's message handler becomes thin:

1. Receive message from platform
2. Resolve session (DB lookup — fast, no tmux)
3. `INSERT INTO inbound_queue` with all metadata
4. If duplicate (source_message_id already exists), return silently
5. Trigger typing indicator on the adapter
6. Ensure a queue worker is running for that session
7. Return — adapter is free

### Discord adapter (`_handle_on_message`)

The current flow at `discord_adapter.py:1564` resolves the session, builds a `ProcessMessageCommand`, and dispatches it synchronously. Refactor to:

1. Keep existing filtering (bot check, guild check, managed channel check)
2. Keep session resolution (or creation for new threads)
3. Replace `_dispatch_command(ProcessMessageCommand(...))` with `enqueue_inbound(...)`
4. Show typing indicator
5. Return

Voice messages: the `_handle_voice_attachment` handler currently downloads, transcribes, and delivers inline. Refactor to: download audio, enqueue with `message_type='voice'` and `payload_json` containing the file path or CDN URL. If transcription succeeds inline (fast path), enqueue with `message_type='text'` and the transcribed content. If transcription fails or is slow, enqueue with `message_type='voice'` and let the worker handle transcription.

### Telegram adapter

Telegram uses long-polling via `python-telegram-bot`'s `start_polling()`. The library manages the `getUpdates` offset internally — it advances the offset after dispatching to handlers, before we've processed the message. We cannot delay the ACK without fighting the library's design.

Pragmatic path: journal in the handler, retry from the core queue. The Telegram ACK ship has sailed for long-polling mode. If we ever switch to webhook mode, we get a free transactional boundary (don't return 200 until journaled).

### Terminal adapter

Terminal input also goes through `process_message` → `tmux_io.process_text`. Same failure path, same lost message. The core inbound queue protects terminal input equally. The TUI enqueues just like Discord does.

### Inbound webhook handler fix

`teleclaude/hooks/inbound.py:136` currently returns `200 OK` on dispatch failure with the comment "prevent platform retries." This is the opposite of guaranteed delivery. For platforms that retry on non-200 (WhatsApp), this line actively suppresses the free transactional boundary. Fix: return 5xx on dispatch failure, let the platform retry. Journal the message first so we handle dedup on replay.

## Typing Indicator

### First-class UX citizen

The typing indicator is not an afterthought — it's the user's signal that their message was received and is being processed. Two signals:

1. **On journal** (adapter receives message, persists to queue): show typing indicator. This means "I received your message, it's safe."

2. **On delivery** (queue worker delivers to tmux): the agent starts processing, which naturally produces output. The typing indicator transitions to normal agent-working state.

The gap between (1) and (2) is normally milliseconds. Under load it could be seconds. The typing indicator covers this gap so the user never wonders "did my message get through?"

### Implementation

Each adapter exposes a `show_typing(session)` method:

- Discord: `channel.typing()` context manager
- Telegram: `send_chat_action(ChatAction.TYPING)`
- Terminal/TUI: status bar indicator

The enqueue path calls `show_typing()` after successful journal insert.

### UX spec deliverable

Document this in `docs/project/spec/ux/typing-indicator.md`:

- When typing indicator appears (message journaled)
- When it transitions (agent starts responding)
- When it clears (agent turn complete or timeout)
- How it behaves on retry (re-show on retry attempt)
- Per-adapter implementation notes

## Message Ordering

### Per-session FIFO guaranteed

Messages for the same session are delivered in the order they were received. This is enforced by:

1. The queue worker processes one message at a time per session
2. If message A fails and is retried, message B waits — it cannot leapfrog A
3. The `fetch_inbound_pending` query orders by `id ASC` (insertion order)

### Cross-session parallelism

Messages for different sessions are processed independently and in parallel. Each session has its own worker task. Session A's slow delivery does not affect session B.

## Voice Message Atomicity

Voice messages are the most fragile path today:

1. Audio file downloaded to `/tmp/` (ephemeral)
2. Transcription takes 36 seconds (Whisper API)
3. If daemon crashes mid-transcription, both audio and text are lost

With the inbound queue:

- **Fast path**: transcribe inline, enqueue the text. If transcription succeeds quickly, the queue receives a text message — no special handling needed.
- **Durable path**: enqueue the voice message with `payload_json` containing the source URL (Discord CDN URL or Telegram `file_id`). The queue worker downloads and transcribes. On failure, retry re-downloads from the source URL.
- **Source URL durability**: Discord CDN URLs expire after ~24 hours. Telegram `file_id` is permanent. For Discord, the fast path (transcribe-then-enqueue) is preferred. If transcription fails, store the downloaded file path AND the CDN URL.

The operation is idempotent — same audio produces same transcription. Expensive on retry (another Whisper call), but correct.

## Adapter-Specific ACK Opportunities

### Platforms that offer transactional boundaries

| Platform                    | Mechanism                                          | Can we use it?                                            |
| --------------------------- | -------------------------------------------------- | --------------------------------------------------------- |
| **WhatsApp**                | Inbound webhook returns non-200 → platform retries | YES — `inbound.py:136` must stop returning 200 on failure |
| **Telegram (webhook mode)** | HTTP response delayed → Telegram retries           | YES — if we switch from long-polling to webhook           |
| **Telegram (long-polling)** | `getUpdates` offset advanced by library            | NO — library auto-ACKs before our handler runs            |
| **Discord**                 | Gateway fire-and-forget, no ACK mechanism          | NO — must handle entirely consumer-side                   |
| **Terminal**                | No ACK concept — input is local                    | N/A — core queue handles durability                       |

### Where adapter-level ACK adds value

For WhatsApp (and future webhook-based integrations), the adapter should:

1. Receive webhook POST
2. Insert into inbound_queue
3. Return 200 only after successful insert
4. If insert fails (DB error), return 5xx → platform retries

This gives us **two layers of protection**: platform retry (adapter boundary) + core queue retry (delivery boundary).

## What `command_retry` Becomes

The `command_retry` decorator at `utils/__init__.py:22-117` with its 60-second ceiling on Telegram operations becomes largely obsolete for the inbound path. The core queue handles retries with exponential backoff.

For outbound Telegram operations (edit_message for displaying agent output), the decorator is still relevant but the 60-second ceiling is excessive. With the QoS scheduler already coalescing output updates, a failed `edit_message` can simply be dropped — the next coalesced update supersedes it. Recommend reducing outbound retry ceiling to 15 seconds and accepting that some output edits will be skipped under Telegram pressure.

This is a separate concern from inbound delivery and can be addressed independently.

## Performance Fixes (Implementation Details)

These fall naturally out of the architecture but should be tracked explicitly:

1. **Remove redundant `session_exists` in `send_keys_existing_tmux`** (`tmux_bridge.py:486`) — the caller at `tmux_io.py:54` already checked. One fewer tmux subprocess per message.

2. **Move `psutil` calls to `asyncio.to_thread()`** in `session_exists` (`tmux_bridge.py:1091-1099`) — `process_iter()`, `virtual_memory()`, and `cpu_percent(interval=0.1)` are synchronous. The `cpu_percent` call sleeps for 100ms, blocking the event loop.

3. **Review `asyncio.sleep(1.0)` in `_send_keys_tmux`** (`tmux_bridge.py:651`) — with the queue worker decoupled from the adapter, this sleep is invisible to the user. But verify if 1s is still needed or if a shorter delay suffices.

4. **Offload retries to library primitives** — both `discord.py` and `python-telegram-bot` handle 429 rate limiting internally. Where we're retrying on top of their retries, we're doubling the backoff. Let the libraries handle transient rate limits; our retry is for infrastructure failures (tmux timeout, DB error).

## Documentation Deliverables

Part of the definition of done:

| Doc                        | Location                                                  | What                                                        |
| -------------------------- | --------------------------------------------------------- | ----------------------------------------------------------- |
| Inbound queue spec         | `docs/project/spec/inbound-queue.md`                      | Architecture, table schema, worker design, retry policy     |
| UX typing indicator        | `docs/project/spec/ux/typing-indicator.md`                | When it appears, transitions, per-adapter behavior          |
| Adapter boundaries update  | `docs/project/policy/adapter-boundaries.md`               | Add inbound queue as the boundary between adapters and core |
| Discord gateway guarantees | `docs/third-party/discord/gateway-delivery-guarantees.md` | Already created during this session                         |

## Relationship to Other Todos

- **notification-service**: orthogonal. Notification service is autonomous event processing (outbound signal pipe). Inbound queue is user message delivery (inbound message pipe). No dependency in either direction. They share patterns (durable queue, retry, FIFO) but serve different purposes.
- **integration-events-model**: may share the `HookEvent` envelope structure for inbound webhook payloads. Worth checking for alignment but not a blocker.
- **harmonize-agent-notifications** (delivered): addressed outbound notification harmonization. This todo addresses inbound delivery — the other direction.

## Design Process

This design was produced through a debugging + brainstorm session:

1. **Trigger**: "Failed to send command to tmux" error in Discord chat when sending a voice message to session `3d2880de`.

2. **Investigation**: Systematic debugging traced the failure to `tmux send-keys -l` timing out after 5 seconds due to event loop starvation. Root cause: synchronous `await` chain from adapter to tmux, compounded by slow Telegram API calls (3-13s), hook outbox queue backlog (depth 0→19), and `asyncio.wait_for()` unable to enforce timeouts precisely under event loop pressure.

3. **Research**: Discord API transactional capabilities investigated — no message ACK mechanism exists. Gateway is fire-and-forget. RESUME replays events within ~90s window. REST API backfill available via `GET /channels/{id}/messages?after={snowflake}`. Findings captured in `docs/third-party/discord/gateway-delivery-guarantees.md`.

4. **Convergence**: Core inbound queue (not adapter-specific) with per-session FIFO workers, typing indicator as first-class UX, voice message payload journaling for idempotent retry, adapter-level ACK where platforms support it (WhatsApp, future Telegram webhook mode).
