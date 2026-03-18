# Requirements: fix-integrate-api-hang

## Goal

Eliminate thread pool exhaustion caused by the `/todos/integrate` REST endpoint
running inline. The endpoint must return immediately with a receipt, matching the
established pattern used by `/todos/work`.

## Problem Statement

The `/todos/integrate` endpoint currently keeps the API request open while the
integration state machine performs long-running git and network work through
thread-backed execution. That ties up shared thread-pool capacity for the life
of the integrate run and can starve unrelated API work.

The system already has a receipt-first contract for long-running todo
operations. Integrate must adopt that same contract instead of completing inline
in the request handler.

## Scope

### In scope

- R1: `POST /todos/integrate` must use the existing receipt-first contract for
  long-running todo operations instead of waiting for integration completion in
  the request handler.
- R2: Integrate execution must run as a durable background operation with the
  same lifecycle guarantees as the existing todo-work receipt flow: nonterminal
  status tracking, progress reporting, heartbeat, failure handling, and stale
  detection.
- R3: Callers may provide an optional `client_request_id` so duplicate integrate
  submissions from the same caller session reattach to the existing nonterminal
  operation instead of starting another integrate run.
- R4: The background integrate run must preserve the caller session identity so
  existing lease ownership and clearance semantics continue to apply.
- R5: The integrate submission and polling flow must conform to the existing
  operation-receipt contract, including immediate receipt return and status
  retrieval through the operations API.
- R6: `telec todo integrate` must remain usable against the new receipt-first
  contract, using the established operations polling flow if blocking behavior
  is still required by the caller.

### Out of scope

- Optimizing the integration state machine itself (subprocess batching, async
  git, or remote-call reduction).
- Redesigning integrate behavior beyond changing how it is submitted and
  executed relative to the HTTP request.
- Changes to the `/todos/prepare` endpoint (it is lightweight and does not
  exhibit this problem).
- Client-side changes beyond preserving the existing integrate workflow.

## Success Criteria

- [ ] `POST /todos/integrate` returns HTTP 202 with a receipt that conforms to
      the existing operation-status contract, including a durable operation ID
      and a pollable status path.
- [ ] The HTTP request completes before the integrate run reaches a terminal
      result; the remaining work is observable through operation status polling.
- [ ] Duplicate requests with the same `client_request_id` from the same caller
      session reattach to the existing nonterminal integrate operation.
- [ ] Integrate progress and terminal states follow the same receipt semantics
      already used for todo-work operations.
- [ ] The background integrate run executes with the caller session identity so
      lease ownership and authorization behavior remain unchanged.
- [ ] Existing CLI callers remain functional under the new API contract,
      either by surfacing the receipt or by continuing through the established
      operations polling flow.

## Constraints

- The change must conform to the existing operation-receipt contract and the
  API-server invariant that long-running work returns immediately instead of
  blocking the request.
- The fix is limited to changing when and where integrate executes; it does not
  redesign integration-state-machine behavior.
- Caller session identity must remain intact from submission through background
  execution [inferred from the current integrate lease-ownership model].

## Verification Expectations

- Verification must include executable, expected-failure-marked test
  specifications for receipt return, duplicate-request reattachment, background
  execution, and caller-visible polling behavior.
- Error and stale-operation handling must be verified against the existing
  operation-receipt contract or explicitly deferred during planning.

## Risks

- The CLI `telec todo integrate` command may need to be updated to poll the
  operation instead of expecting an inline result. This is in scope only if
  the CLI currently interprets the response [inferred from current command
  behavior].
