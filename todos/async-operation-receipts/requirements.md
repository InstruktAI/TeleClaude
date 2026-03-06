# Requirements: async-operation-receipts

## Intent

Decouple long-running CLI/API workflows from HTTP request scope by introducing durable
operation receipts and polling-based result retrieval. The API must acknowledge work
quickly; the CLI may still present a blocking experience by polling in the client.

## Why

Current long-running routes, especially `/todos/work`, keep the HTTP request open while
executing real orchestration work. That causes `slow_requests` watchdog noise, client
timeouts, and an architectural mismatch between the API's role and the work being done.

The caller model matters:

1. Agents invoke one-shot CLI commands.
2. They do not naturally have a durable async inbox.
3. Tmux injection is not an acceptable primary contract for result delivery.
4. The natural contract is therefore: submit, receive receipt, poll for completion.

## In Scope

1. A durable operation model for long-running local workflows.
2. Submit/status/result contracts for operation-backed commands.
3. A polling contract that keeps the API non-blocking while allowing CLI commands to wait.
4. Submission idempotency at the operation-creation boundary.
5. Initial adoption for `telec todo work`.
6. Recovery semantics for interrupted clients, lost responses, worker crashes, and daemon restarts.
7. Operation progress and observability sufficient to debug hangs and stalled work.
8. A reusable pattern that later adopters can follow (`telec todo integrate`, session cleanup/revive routes).

## Out of Scope

1. Making `next_work()` itself idempotent.
2. Using the in-process event bus or tmux injection as the source of truth for command completion.
3. Requiring agent callers to manage push subscriptions.
4. Converting every currently slow route in the first implementation.
5. Changing the semantic meaning of `next_work()` results; transport changes, result meaning does not.

## Functional Requirements

### FR1: Fast Submit Contract

1. Long-running operation-backed routes MUST acknowledge work quickly on a healthy local system.
2. The target for submit latency SHOULD be under 1 second; 10 seconds is a failure threshold, not an acceptable steady-state target.
3. The submit response MUST return a durable `operation_id`.
4. The submit response MUST include enough polling guidance for a caller to continue without guessing:
   - current state
   - suggested `poll_after_ms`
   - status path or canonical recovery command

### FR2: Durable Operation Record

1. The system MUST persist an operation row before any long-running execution begins.
2. The operation record MUST capture, at minimum:
   - operation kind
   - caller session identity
   - route-specific payload (`slug`, `cwd`, etc.)
   - client request identifier for submit dedupe
   - lifecycle state
   - progress/phase metadata
   - terminal result or terminal error
   - timestamps and worker heartbeat data
3. Operation state MUST be durable across daemon restarts.

### FR3: Execution Semantics

1. Workers MUST execute the underlying long-running function exactly once per claimed operation.
2. For the initial adopter, that function is `next_work()`.
3. `next_work()` MUST remain non-idempotent; retries at the submit layer MUST NOT cause the state machine to advance twice.
4. Terminal operation results for `todo work` MUST preserve the current caller-facing result shape so existing orchestration logic does not need a second migration.

### FR4: Submission Idempotency

1. Submit idempotency applies to operation creation, not to state-machine execution.
2. Re-submitting the same logical request with the same `client_request_id` MUST return the same `operation_id`.
3. Re-submitting the same logical request with the same `client_request_id` MUST NOT enqueue or execute a second `next_work()` run.
4. Dedupe identity MUST include enough context to prevent accidental cross-command collisions.

### FR5: Polling Contract

1. A caller MUST be able to query operation state by `operation_id`.
2. The status endpoint MUST be cheap and safe to poll repeatedly.
3. The server MUST direct polling cadence; clients SHOULD NOT hard-code fixed retry intervals when server guidance is available.
4. The status contract MUST distinguish at least:
   - queued
   - running
   - completed
   - failed
   - cancelled or expired
5. Running-state payloads SHOULD expose current phase/progress when available.

### FR6: CLI Behavior

1. The machine contract MUST remain explicit even if the CLI chooses to wait automatically.
2. A blocking CLI experience is acceptable only if it is implemented as submit + poll, not as one long HTTP request.
3. `telec todo work` MUST auto-wait by default in the first implementation to preserve current agent ergonomics.
4. If the wait path exits due to timeout, interruption, or wrapper failure, the CLI MUST emit a recovery handle before exiting whenever possible.
5. Recovery MUST NOT require tmux injection or hidden side channels.
6. Final CLI output MUST include the durable receipt fields needed for recovery even on successful completion.

### FR7: Recovery Semantics

1. Clients MUST be able to recover from the "submit succeeded, response was lost" case without creating duplicate execution.
2. Clients MUST be able to recover from local wrapper interruption while the operation continues in the background.
3. The system MUST detect stale operations whose worker died or stopped heartbeating.
4. Operations MUST not remain in `running` forever with no expiry or stale detection policy.
5. Re-running the same logical `telec todo work` command while a matching nonterminal operation already exists for the same caller MUST reattach to the existing operation rather than create a new execution.

### FR8: Ownership and Authorization

1. Operation inspection MUST preserve caller ownership boundaries.
2. The original caller and authorized operators/admins MAY inspect an operation.
3. Operation-backed commands MUST preserve existing tool-clearance rules.
4. Caller identity required by `next_work()` invariants, especially finalize ownership, MUST survive the async boundary unchanged.

### FR9: Next Machine Invariants

1. The existing per-repo+slug single-flight behavior MUST remain intact.
2. Finalize lock ownership semantics MUST remain intact.
3. Async operation orchestration MUST NOT introduce duplicate finalize dispatches or duplicate worker dispatches for the same logical submit.
4. Existing phase observability (`NEXT_WORK_PHASE`) MUST remain available and SHOULD feed operation progress state where practical.

### FR10: Initial Scope and Follow-On Adoption

1. The first adopter MUST be `telec todo work`.
2. The resulting pattern SHOULD be designed for reuse by other slow routes later.
3. The first implementation MUST avoid over-generalizing beyond what `todo work` and near-term adopters actually need.

## Success Criteria

- [ ] `telec todo work` no longer depends on a long-lived HTTP request to complete successfully.
- [ ] API submit path for long-running work returns quickly with a durable receipt.
- [ ] Repeated submit of the same logical request does not execute `next_work()` twice.
- [ ] The final `todo work` result remains compatible with current orchestrator expectations.
- [ ] An interrupted caller can recover the in-flight operation without manual DB inspection.
- [ ] Operation state exposes enough progress to diagnose "stuck vs still running" cases.
- [ ] Existing finalize-lock and single-flight behavior remain correct under async execution.

## Constraints

- Everything runs on the local machine; the solution does not need a distributed queue to be valid.
- The API is the control plane and should primarily validate, persist intent, and return.
- The CLI may remain ergonomically blocking, but the underlying system contract must stay explicit and recoverable.
- The event bus may accelerate updates, but durable operation state is the source of truth.
- The design must not rely on tmux injection as the primary result-delivery mechanism for agent callers.

## Risks

- Hiding the receipt entirely behind a blocking wrapper makes recovery fragile when the wrapper dies before exposing it.
- Over-generalizing the operation framework before the first adopter lands can slow delivery and increase complexity.
- Incorrect stale-operation detection can race with legitimately slow local work and cause false failure handling.
- Submit dedupe that is too broad can collapse distinct requests; submit dedupe that is too narrow can allow duplicate execution.

## Background Notes

- `/todos/work` is the first and most important adopter because it currently runs substantial orchestration inside the request path.
- The system already has eventing and listener mechanisms, but they are not sufficient as the authoritative result contract for CLI-driven long-running commands.
- The key architectural distinction is:
  - `next_work()` is not idempotent.
  - operation creation must be idempotent.

## Resolved Decisions

1. `telec todo work` will default to auto-wait after submit so agents keep the current blocking command ergonomics.
2. Auto-wait is an implementation detail of the CLI only; the API contract remains receipt-first and non-blocking.
3. The CLI must always surface a recovery artifact, even on success. At minimum that includes:
   - `operation_id`
   - terminal or current `state`
   - `poll_after_ms` when still nonterminal
   - canonical recovery command for direct inspection
4. Recovery-by-resubmit with only `client_request_id` is not sufficient by itself.
5. The system must support both:
   - submit dedupe by `client_request_id`
   - caller-scoped reattachment to an existing matching nonterminal operation
