# Operation Receipts

## Purpose

`telec todo work` now uses a receipt-first contract instead of holding the HTTP request
open until `next_work()` finishes. The daemon persists an operation row, returns a
durable `operation_id`, and runs `next_work()` in a tracked background task. The CLI
keeps the old blocking ergonomics by polling `/operations/{operation_id}` until the
operation reaches a terminal state.

## Flow

1. `POST /todos/work` validates input and submits an operation through the operations service.
2. The service persists the row before execution and returns a receipt immediately.
3. A background task claims the queued operation, heartbeats while running, and stores
   the terminal `next_work()` result or terminal error.
4. `GET /operations/{operation_id}` is the durable source of truth for status, progress,
   recovery, and final result retrieval.

## Ownership

- Operation rows are keyed to the caller session that submitted them.
- Non-admin callers may only inspect their own operations.
- Admins may inspect any operation through the same status route.

## Reattachment

- Submit dedupe uses `client_request_id` scoped by operation kind and caller session.
- Re-running `telec todo work` with the same caller, slug, and cwd reattaches to a
  matching nonterminal operation instead of creating a second execution.

## Progress

`next_work()` already emits `NEXT_WORK_PHASE` logs. The operation runtime hooks into that
phase logging and mirrors the latest phase/decision/reason into the durable operation row
so polling callers can distinguish queued, running, and recent phase progress.

## Restart Policy

`next_work()` is not safe to replay blindly. On daemon startup, any leftover queued or
running operation from the previous process is marked `stale` instead of being resumed
automatically. This keeps the receipt truthful without risking duplicate state-machine
advancement after a crash or restart.
