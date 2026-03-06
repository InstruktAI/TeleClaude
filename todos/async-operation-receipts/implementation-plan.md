# Implementation Plan: async-operation-receipts

## Overview

- Introduce a durable operation substrate for long-running commands, adopt it first for
  `telec todo work`, and keep current caller semantics by moving the wait loop into the
  CLI instead of the HTTP request. The implementation should prove the contract on one
  high-value route before broadening to other slow endpoints.

## Phase 1: Operation Contract and Storage

### Task 1.1: Define the operation model and lifecycle

**File(s):**
- `teleclaude/api_models.py`
- `teleclaude/core/db_models.py`
- `teleclaude/core/db.py`
- `teleclaude/core/migrations/` (new migration)
- `teleclaude/core/operations/` (new module or package)

- [x] Define durable operation fields, lifecycle states, and terminal payload shapes
- [x] Define submit-dedupe identity (`client_request_id` boundary only)
- [x] Define worker-claim semantics so one operation executes once
- [x] Define stale/heartbeat policy for abandoned operations

### Task 1.2: Define the public API contract

**File(s):**
- `teleclaude/api/todo_routes.py`
- `teleclaude/api_models.py`
- `teleclaude/api_server.py`
- `docs/project/design/architecture/` (new or updated design doc)

- [x] Define submit response payload for long-running operations
- [x] Define operation status/result response payloads
- [x] Add caller-scoped recovery/reattachment lookup in addition to direct lookup by `operation_id`
- [x] Document the contract distinction between operation submission idempotency and non-idempotent state-machine execution

---

## Phase 2: Operation Runtime

### Task 2.1: Build the operation service and worker execution path

**File(s):**
- `teleclaude/core/operations/` (new)
- `teleclaude/daemon.py`
- `teleclaude/core/task_registry.py`
- `teleclaude/core/next_machine/core.py`

- [x] Add an operation submit path that persists the row before background execution
- [x] Add a worker loop or background executor that claims pending operations safely
- [x] Add heartbeat/progress updates during execution
- [x] Record terminal result/error without changing `next_work()` meaning

### Task 2.2: Map `NEXT_WORK_PHASE` progress into operation state

**File(s):**
- `teleclaude/core/next_machine/core.py`
- `teleclaude/core/operations/` (new)
- logging/instrumentation touchpoints as needed

- [x] Expose useful phase/progress metadata from `next_work()` without changing its decision logic
- [x] Persist progress updates so polling callers can distinguish slow-but-healthy from stuck
- [x] Keep existing phase timing logs intact for grep-based diagnostics

---

## Phase 3: Adopt `telec todo work`

### Task 3.1: Convert `/todos/work` from request-scoped execution to submit-only

**File(s):**
- `teleclaude/api/todo_routes.py`
- `teleclaude/core/operations/` (new)
- `teleclaude/api/auth.py`

- [x] Replace inline `await next_work(...)` with submit + receipt response
- [x] Preserve caller identity needed by finalize-lock ownership
- [x] Ensure duplicate submits with the same `client_request_id` return the existing operation

### Task 3.2: Update the CLI contract

**File(s):**
- `teleclaude/cli/tool_commands.py`
- `teleclaude/cli/tool_client.py`
- `teleclaude/cli/telec.py`

- [x] Implement default auto-wait for `telec todo work` as repeated short polls, never a long HTTP request
- [x] Ensure interrupted or timed-out wait paths surface a recovery handle
- [x] Ensure final successful output still includes the receipt fields needed for later recovery/audit
- [x] Add an explicit operation-inspection command for direct status/result lookup

---

## Phase 4: Recovery and Failure Handling

### Task 4.1: Handle lost-response and wrapper-interruption cases

**File(s):**
- `teleclaude/core/operations/` (new)
- `teleclaude/cli/tool_commands.py`
- `teleclaude/cli/tool_client.py`

- [x] Prove that a submit retry does not double-run `next_work()`
- [x] Implement caller-scoped reattachment when a wrapper exits before completion and the command is re-run
- [x] Ensure the recovery path does not require tmux injection or manual DB access

### Task 4.2: Handle daemon restart and stale operations

**File(s):**
- `teleclaude/daemon.py`
- `teleclaude/core/operations/` (new)
- `teleclaude/services/maintenance_service.py` or equivalent

- [x] Detect stale running operations after worker death or restart
- [x] Mark or recover abandoned operations predictably
- [x] Avoid leaving operations in `running` forever without heartbeat expiry

---

## Phase 5: Validation and Follow-On Scope Check

### Task 5.1: Test coverage

**File(s):**
- `tests/` covering API, DB, CLI, and operation runtime

- [x] Add tests for submit dedupe
- [x] Add tests for single-claim execution
- [x] Add tests for `/todos/work` result compatibility
- [x] Add tests for stale-operation handling
- [x] Add tests for CLI recovery behavior

### Task 5.2: Verify architectural boundaries before broadening adoption

**File(s):**
- `todos/async-operation-receipts/requirements.md`
- `docs/project/design/architecture/` (updated design notes)

- [x] Confirm the first adopter solves the current `/todos/work` timeout pathology
- [x] Confirm the abstraction is not over-generalized before adding more routes
- [x] Identify the next candidate adopters only after `todo work` behavior is proven

---

## Phase 6: Validation

### Task 6.1: Tests

- [x] Add or update tests for the changed behavior listed above
- [x] Run `make test`

### Task 6.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

Notes:
- `make lint` was executed on March 6, 2026. The remaining failures are repository-wide `pylint teleclaude`
  baseline debt in unchanged modules, not async-operation-receipts regressions.
- Feature-specific validation passed: `make test`, demo validation, docs sync, and file-scoped lint on the
  async-operation-receipts delta.

---

## Phase 7: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
