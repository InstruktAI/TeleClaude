---
description: 'Receipt-first contract for telec todo work with durable operation tracking and polling.'
id: 'project/design/architecture/operation-receipts'
scope: 'project'
type: 'design'
---
# Operation Receipts — Design

## Purpose

`telec todo work` uses a receipt-first contract instead of holding the HTTP request
open until `next_work()` finishes. The daemon persists an operation row, returns a
durable `operation_id`, and runs `next_work()` in a tracked background task. The CLI
keeps the old blocking ergonomics by polling `/operations/{operation_id}` until the
operation reaches a terminal state.

## Inputs/Outputs

- **Input:** `POST /todos/work` with `{slug, cwd, client_request_id}` from the caller session.
- **Output (immediate):** `{operation_id, state: "queued", status_path, poll_after_ms}`.
- **Output (terminal):** `GET /operations/{operation_id}` returns `{state: "completed"|"failed"|"stale", result}`.
- Operation rows are keyed to the caller session; non-admins may only inspect their own.

## Invariants

- Submit dedupe: `client_request_id` scoped by operation kind and caller session prevents
  duplicate executions — re-running `telec todo work` with the same caller, slug, and cwd
  reattaches to a matching nonterminal operation.
- `next_work()` phase logging is mirrored into the durable operation row so polling callers
  can distinguish queued, running, and recent phase progress.

## Primary flows

1. `POST /todos/work` validates input and submits an operation through the operations service.
2. The service persists the row before execution and returns a receipt immediately.
3. A background task claims the queued operation, heartbeats while running, and stores
   the terminal `next_work()` result or terminal error.
4. `GET /operations/{operation_id}` is the durable source of truth for status, progress,
   recovery, and final result retrieval.

## Failure modes

- **Daemon restart:** `next_work()` is not safe to replay blindly. On daemon startup, any
  leftover queued or running operation from the previous process is marked `stale` instead
  of being resumed. This keeps the receipt truthful without risking duplicate state-machine
  advancement after a crash or restart.
- **Caller mismatch:** Non-admin callers attempting to access another session's operation
  receive a 404 (not a 403) to avoid session ID enumeration.