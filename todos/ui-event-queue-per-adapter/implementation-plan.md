# Implementation Plan: UI Event Queue Per Adapter

## Overview
Implement an internal UI-event dispatcher with per-adapter queues and workers.
AdapterClient becomes the single producer of UI events while workers execute
the existing adapter methods asynchronously.

## High-Level Steps
1) **Define UI action model**
   - Create a dataclass `UiAction` with:
     - delivery_id (uuid)
     - session_id
     - adapter_type
     - action (enum/string)
     - payload (dict)
     - await_ui (bool)
   - Define action types: create_channel, send_message, send_feedback,
     send_file, edit_message.

2) **Create UI dispatcher**
   - New module: `teleclaude/core/ui_dispatcher.py`.
   - Maintains:
     - `workers: dict[adapter_type, asyncio.Task]`
     - `futures: dict[delivery_id, asyncio.Future]` for await_ui.
   - **SQLite-backed queue** (not in-memory asyncio.Queue):
     - Table: `ui_queue` with columns: `delivery_id`, `session_id`, `adapter_type`,
       `action`, `payload` (JSON), `status`, `created_at`, `completed_at`, `error`.
     - Workers poll DB: `SELECT ... WHERE adapter_type=? AND status='pending' ORDER BY created_at LIMIT 1`
     - Use `FOR UPDATE` semantics or optimistic locking to prevent duplicate pickup.
   - Public API:
     - `start(adapters: dict[str, BaseAdapter])`
     - `stop()`
     - `enqueue(action: UiAction) -> DeliveryHandle`
     - `await_delivery(delivery_id, timeout=None)` (optional)
     - `recover_pending()` - called on startup to replay crashed actions

3) **Wire AdapterClient to enqueue**
   - In `AdapterClient` methods:
     - `create_channel`, `send_message`, `send_feedback`, `send_file`, `edit_message`
   - Replace direct adapter calls with `ui_dispatcher.enqueue(...)`.
   - Preserve routing rules:
     - origin adapter first
     - observers for fan-out
   - Add `await_ui` parameter with contract rules:
     - **Origin adapter**: `await_ui=True` when contract-critical.
     - **Observers**: `await_ui=False` (always async).

4) **Worker execution**
   - Each adapter type has a worker task:
     - Poll DB for next pending action: `SELECT ... WHERE status='pending' AND adapter_type=?`
     - Mark as `processing` before execution (crash safety).
     - Call adapter method (same arguments as today).
     - On success: mark `completed`, set future result for `await_ui`.
     - On failure: mark `failed` with error, set future exception.
     - Log success/failure and queue metrics.
   - Use adapter's own retry/backoff (no new retry logic).
   - Poll interval: 50ms when idle, immediate when work is enqueued (use asyncio.Event).

5) **Lifecycle management**
   - Start dispatcher in daemon startup after adapters are initialized.
   - **Crash recovery on startup**:
     - Query `status IN ('pending', 'processing')` - these survived a crash.
     - Reset `processing` → `pending` (will be retried).
     - Log count of recovered actions per adapter.
     - Process recovered actions before accepting new work.
   - Stop dispatcher on daemon shutdown (cancel workers, mark incomplete as pending).
   - **Pruning**: periodically delete `completed`/`failed` rows older than retention.

6) **Logging/observability**
   - Log on enqueue:
     - `ui_delivery_queued delivery_id session_id adapter_type action`
   - Log on completion:
     - `ui_delivery_result delivery_id status duration`
   - Optional periodic log of queue sizes per adapter.

7) **Tests**
   - Unit tests for:
     - enqueue + worker execution path
     - await_ui returns after completion
     - per-adapter isolation (one slow adapter doesn't block others)
     - **crash recovery**: insert pending rows, call recover_pending(), verify delivery
     - **idempotency**: simulate duplicate delivery, verify no corruption
     - **pruning**: verify old completed rows are deleted
   - Update existing tests if they rely on immediate adapter calls.

8) **Database migration**
   - Add migration `NNN_ui_queue.sql` with `ui_queue` table schema.
   - Run via existing migration system on daemon startup.

## Detailed Design Notes
- **DeliveryHandle**: return object with `delivery_id` and `status="queued"`.
- **Message IDs**:
  - For actions that used to return message_id:
    - If `await_ui=True`, return the real message_id.
    - If `await_ui=False`, return delivery_id (no contract change where id
      was not used); ensure callers that require message_id use await_ui.
- **create_channel**:
  - Must preserve synchronous semantics for session setup.
  - Use `await_ui=True` for the origin adapter in `handle_create_session`.
- **send_feedback**:
  - Use `await_ui=True` for origin adapter when `message_id` is needed for
    pending deletions; observers async.
- **send_message/send_file**:
  - Use `await_ui=True` for origin adapter when immediate `message_id` is
    required; observers async.
- **edit_message**:
  - Origin adapter remains blocking where required; observers async.

## Risk Mitigations
- Add a max queue size per adapter to prevent unbounded memory usage.
- On enqueue failure (queue full), log error and optionally return a failure
  to caller when await_ui is requested.
- Keep per-adapter ordering; do not interleave actions within the same adapter.

## Rollout Plan
1) Implement dispatcher behind a feature flag (config or env).
2) Enable for Telegram only first; keep others synchronous.
3) Observe logs for delivery success rate and queue depth.
4) Expand to all UI adapters once stable.
