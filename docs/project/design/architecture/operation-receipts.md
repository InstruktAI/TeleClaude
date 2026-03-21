---
description: 'Receipt-first contract for durable async operations: immediate operation_id, background execution, polling, and completion event.'
id: 'project/design/architecture/operation-receipts'
scope: 'project'
type: 'design'
---

# Operation Receipts — Design

## Required reads

- @docs/project/design/architecture/command-classification.md

## Purpose

Any command with `response_mode=RECEIPT` uses a receipt-first contract instead of
holding the HTTP request open until the work finishes. The daemon persists an operation
row before execution begins, returns a durable `OperationReceipt` immediately, and runs
the work in a tracked background task. When the task reaches a terminal state, it emits
the `completion_event` declared on the command. Callers may poll
`/operations/{operation_id}` or subscribe to the WebSocket event — both paths are
authoritative.

This pattern applies to any operation that is too long to hold a request open for:
state machines, multi-step orchestration, heavy I/O. It is not appropriate for fast
mutations — those use `IMMEDIATE` or `FIRE_AND_FORGET`.

### Operation kinds inventory

| Kind constant                 | String value     | Endpoint                |
| ----------------------------- | ---------------- | ----------------------- |
| OPERATION_KIND_TODO_WORK      | `todo_work`      | `POST /todos/work`      |
| OPERATION_KIND_TODO_INTEGRATE | `todo_integrate` | `POST /todos/integrate` |
| OPERATION_KIND_TODO_CREATE    | `todo_create`    | `POST /todos/create`    |
| OPERATION_KIND_TODO_PREPARE   | `todo_prepare`   | `POST /todos/prepare`   |

## Inputs/Outputs

- **Input:** Any route backed by a RECEIPT command, e.g. `POST /todos/work` with
  `{slug, cwd, client_request_id}`.
- **Output (immediate):** `OperationReceipt` — `{operation_id, kind, state: "queued",
status_path, poll_after_ms, completion_event, recovery_command}`.
- **Output (terminal):** `GET /operations/{operation_id}` returns the full receipt with
  `state: "completed"|"failed"|"stale"` and `result` or `error`.
- Operation rows are keyed to the caller session; non-admins may only inspect their own.

## Invariants

- **Persist before execute.** The operation row is written to DB before the background
  task is scheduled. The receipt is always valid even if the daemon crashes immediately
  after returning it.
- **Submit dedupe.** `client_request_id` scoped by operation kind and caller session
  prevents duplicate executions. Re-submitting with the same `client_request_id`
  reattaches to a matching nonterminal operation row.
- **Atomic terminal transition.** The background task emits `completion_event` as the
  final step of writing the terminal DB state. The event and the row transition happen
  in the same logical unit — never split.
- **Stale on restart.** Operations in `queued` or `running` state are marked `stale`
  at daemon startup. Work is never replayed blindly. The receipt remains truthful.
- **completion_event is informational.** Callers may use it to avoid polling, but the
  receipt row is the authority. If the event fires but the row is not yet terminal
  (race), trust the row.

## Primary flows

1. Client calls a RECEIPT endpoint. Route creates the command and calls
   `OperationsService.submit(command)`.
2. `OperationsService` deduplicates via `client_request_id`, persists the row
   (`state=queued`), and returns the receipt immediately.
3. A background task claims the queued row (`state=running`), heartbeats periodically,
   and executes the work.
4. On completion, the task writes the terminal result to the row and emits
   `completion_event` on the event bus.
5. Clients either poll `GET /operations/{operation_id}` or listen for the WebSocket
   event — both lead to the same terminal payload.

## Failure modes

- **Daemon restart:** Leftover `queued` or `running` operations are marked `stale`
  at startup. Callers polling the receipt see `state: "stale"` and may resubmit.
  Work is never replayed automatically.
- **Background task panic:** If the task dies before the terminal write, the row stays
  `running` until the heartbeat window expires. The receipt eventually shows `stale`.
  The `completion_event` is not emitted. Callers must detect the stale state via polling.
- **Caller mismatch:** Non-admin callers attempting to access another session's operation
  receive a 404 (not a 403) to avoid session ID enumeration.
- **Event fires, row not yet terminal:** Trust the row. The event is a convenience
  signal; the DB row is authoritative.
