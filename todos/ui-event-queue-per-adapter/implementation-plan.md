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
     - `queues: dict[adapter_type, asyncio.Queue[UiAction]]`
     - `workers: dict[adapter_type, asyncio.Task]`
     - `futures: dict[delivery_id, asyncio.Future]` for await_ui.
   - Public API:
     - `start(adapters: dict[str, BaseAdapter])`
     - `stop()`
     - `enqueue(action: UiAction) -> DeliveryHandle`
     - `await_delivery(delivery_id, timeout=None)` (optional)

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
   - Each adapter type has a worker:
     - `while True: action = await queue.get()`
     - Call adapter method (same arguments as today).
     - Set future result for `await_ui`.
     - Log success/failure and queue metrics.
   - Use adapter’s own retry/backoff (no new retry logic).

5) **Lifecycle management**
   - Start dispatcher in daemon startup after adapters are initialized.
   - Stop dispatcher on daemon shutdown (cancel workers, drain queues).

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
     - per-adapter isolation (one slow adapter doesn’t block others)
   - Update existing tests if they rely on immediate adapter calls.

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
