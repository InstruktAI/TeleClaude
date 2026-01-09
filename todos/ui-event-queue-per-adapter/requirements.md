# UI Event Queue Per Adapter

## Summary
Decouple UI adapter updates from MCP tool response time by routing UI actions
through an internal event/queue system with one worker per adapter. This keeps
current user-visible behavior but removes Telegram retry latency from the tool
call window and allows per-adapter pacing.

## Goals
- Preserve current behavior and message semantics (no functional changes to UI).
- Keep adapter fan-out identical to today (origin adapter + observers).
- Remove UI retry time from MCP tool response window.
- Allow per-adapter throughput control (e.g., Telegram slower than terminal).
- Provide clear delivery visibility via logs (no new user-facing messages).
- Maintain deterministic ordering per adapter (FIFO within each adapter).
- **Crash recovery** - pending UI actions survive daemon restart and are replayed.

## Non-Goals
- No new fallback or "best-effort" behavior changes.
- No user-facing notifications about delivery success/failure.
- No change to existing command semantics or adapter routing rules.
- No cross-adapter ordering guarantees (only per-adapter order is required).

## Current Behavior (Baseline)
- AdapterClient methods call UI adapters directly (synchronous await).
- Telegram send/edit retries and rate limits can block tool calls.
- Output streaming edits are already async; this work targets direct UI actions:
  - create_channel
  - send_message
  - send_feedback
  - send_file
  - edit_message

## Functional Requirements
1) **Event-based dispatch**
   - UI actions are emitted as internal events and enqueued per adapter.
   - The originating call returns after enqueue.

2) **Per-adapter workers**
   - One worker per UI adapter type (telegram, terminal, etc.).
   - Each worker consumes only its adapter queue.
   - Workers apply adapter-specific retry/backoff as implemented in adapters.

3) **Preserve fan-out semantics**
   - Origin adapter remains primary destination.
   - Observer adapters still receive the same action (best-effort).
   - Routing logic remains in AdapterClient (no new routing policy).

4) **Ordering**
   - FIFO ordering within a given adapter queue.
   - No requirement for ordering across different adapters.

5) **Delivery tracking**
   - Log on enqueue with delivery_id, session_id, adapter_type, action.
   - Log on completion (success/failure) with same delivery_id.
   - No UI side-effects beyond existing outputs.

6) **Blocking option (contract parity)**
   - Support `await_ui=True` to preserve current contract where required.
   - Default is non-blocking for observer fan-out.
   - **Contract rule**:
     - Origin adapter actions remain blocking (await_ui=True) when they are
       contract-critical (create_channel, send_feedback with message_id use,
       send_message/send_file when immediate message_id is required).
     - Observer fan-out actions are non-blocking (await_ui=False).

7) **Failure handling**
   - If delivery fails, log error with context and action payload summary.
   - Do not retry beyond adapter-level retry rules.
   - Do not surface to user unless existing adapter logic already does.

8) **Durable queue storage (SQLite)**
   - Queue actions are persisted to SQLite (`ui_queue` table) before returning.
   - Schema: `delivery_id`, `session_id`, `adapter_type`, `action`, `payload` (JSON),
     `status` (pending/processing/completed/failed), `created_at`, `completed_at`.
   - On daemon startup: query `status IN ('pending', 'processing')` and replay.
   - On successful delivery: update `status = 'completed'`.
   - On permanent failure: update `status = 'failed'` with error context.
   - Completed/failed rows can be pruned after configurable retention (default 1 hour).

9) **Crash recovery semantics**
   - Actions marked `processing` at startup are retried (daemon may have crashed mid-delivery).
   - Idempotency: adapters must handle duplicate delivery gracefully (Telegram edit
     of same message, terminal re-print is acceptable).
   - Recovery happens before normal queue processing resumes.

## Observability
- Structured logs for:
  - queue enqueue
  - worker start/stop
  - delivery success/failure
  - queue length snapshot (periodic, optional)
- Must include session_id and adapter_type in logs.

## Performance/Capacity
- Configurable per-adapter queue size (default matches current outbound queue max).
- Backpressure strategy: reject enqueue (error log) if adapter queue is full.
- No global queue contention between adapters.

## Compatibility
- **Database migration required**: adds `ui_queue` table to `teleclaude.db`.
- Works with existing AdapterClient and UiAdapter interfaces.
- Compatible with current MCP wrapper and tool call pipeline.

## Acceptance Criteria
- MCP tool responses are no longer delayed by Telegram retry/backoff.
- UI output remains functionally identical in Telegram and other adapters.
- Per-adapter workers can be observed in logs.
- No regressions in existing tests.
- **Crash recovery**: pending actions are delivered after daemon restart.
- **Idempotency**: duplicate delivery (from crash recovery) does not break UI state.
