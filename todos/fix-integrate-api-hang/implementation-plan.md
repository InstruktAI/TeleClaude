# Implementation Plan: fix-integrate-api-hang

## Overview

Mirror the `submit_todo_work` / `_run_todo_work_operation` pattern for integrate.
Three files change: `service.py` (new operation kind + submit + runner), `todo_routes.py`
(route becomes 202), `todo.py` (CLI polls receipt). No new abstractions — every piece
copies the existing work pattern with integrate-specific arguments.

---

## Task Status

- [x] Task 1: Add integrate operation to `OperationsService`
- [x] Task 2: Convert `POST /todos/integrate` route to 202
- [x] Task 3: Update CLI handler to poll
- [x] Task 4: Tests

---

## Task 1: Add integrate operation to `OperationsService`

**File:** `teleclaude/core/operations/service.py`

**Satisfies:** R1, R2, R3, R4

**Why:** The operations service is the single entry point for durable background
operations. Adding integrate here reuses heartbeat, progress, stale detection, and
deduplication without inventing new infrastructure.

**Steps:**

1. Add `OPERATION_KIND_TODO_INTEGRATE = "todo_integrate"` constant next to
   `OPERATION_KIND_TODO_WORK`.

2. Add `submit_todo_integrate` method mirroring `submit_todo_work`:
   - Parameters: `slug: str | None`, `cwd: str`, `caller_session_id: str`,
     `client_request_id: str | None` (R3 deduplication).
   - Uses `OPERATION_KIND_TODO_INTEGRATE` as the kind.
   - Same submit lock, nonterminal reattach, and idempotent creation pattern.

3. Add `_run_todo_integrate_operation` method mirroring `_run_todo_work_operation`:
   - Claims the operation, starts heartbeat, sets progress callback.
   - Calls `next_integrate(self._db, operation.slug, operation.cwd, operation.caller_session_id)`.
   - `caller_session_id` is read from the stored operation record (R4).
   - Completes or fails the operation on return/exception.

4. Add `_ensure_integrate_operation_task` (or extend `_ensure_operation_task` to
   accept a runner factory) so the integrate runner is spawned instead of the work runner.

**Verification:** `submit_todo_integrate` creates an operation with
`kind=todo_integrate`, state `queued`, spawns a background task.
Duplicate calls with same `client_request_id` return the existing operation.

---

## Task 2: Convert `POST /todos/integrate` route to 202

**File:** `teleclaude/api/todo_routes.py`

**Satisfies:** R1, R5

**Why:** The route currently awaits `next_integrate` inline. It must delegate to the
operations service and return immediately, matching `todo_work`.

**Steps:**

1. Change route decorator: `status_code=202`, `response_model=OperationStatusDTO`,
   `response_model_exclude_none=True`.

2. Change return type to `SerializedOperation`.

3. Add `client_request_id: Annotated[str | None, Body()] = None` to the signature.

4. Replace the body: call `operations.submit_todo_integrate(...)` instead of
   `next_integrate(...)` directly.

5. Remove the `try/except` block that logged inline exceptions — the runner handles that.

6. Remove the `next_integrate` import from this file (no longer called here).

**Verification:** `POST /todos/integrate` returns HTTP 202 with `operation_id`,
`state`, `poll_after_ms`, and `status_path`. The request completes before
the integrate run finishes.

---

## Task 3: Update CLI handler to poll

**File:** `teleclaude/cli/tool_commands/todo.py`

**Satisfies:** R6

**Why:** The CLI handler currently prints the inline result. It must now treat the
202 response as a receipt and poll until terminal, matching `handle_todo_work`.

**Steps:**

1. After `tool_api_call("POST", "/todos/integrate", json_body=body)`, extract
   `operation_id` from the response.

2. If `operation_id` is present, enter the same poll loop used in `handle_todo_work`:
   - Sleep `poll_after_ms` (default 250ms).
   - `GET /operations/{operation_id}` until terminal state.
   - On `KeyboardInterrupt`, print recovery command and `raise SystemExit(130)`.

3. Print the final terminal status as JSON.

**Verification:** `telec todo integrate` polls until the operation reaches a terminal
state and prints the result. `Ctrl-C` prints the recovery command.

---

## Task 4: Tests

**Files:**

- `tests/unit/core/operations/test_service.py`
- `tests/unit/api/test_todo_routes.py`

**Satisfies:** Verification Expectations

**Steps:**

1. `test_submit_todo_integrate_creates_operation`: calling `submit_todo_integrate`
   creates an operation with `kind=todo_integrate`, state `queued`, spawns a task.

2. `test_submit_todo_integrate_reattaches_nonterminal`: a second call with the same
   key returns the existing operation.

3. `test_submit_todo_integrate_deduplicates_by_client_request_id`: duplicate
   `client_request_id` returns the original operation (R3).

4. `test_todo_integrate_returns_202`: route returns HTTP 202 with `operation_id`.

5. `test_todo_integrate_requires_cwd`: missing `cwd` raises 400 (unchanged).

---

## Referenced Files

- `teleclaude/core/operations/service.py`
- `teleclaude/api/todo_routes.py`
- `teleclaude/cli/tool_commands/todo.py`
- `tests/unit/core/operations/test_service.py`
- `tests/unit/api/test_todo_routes.py`
