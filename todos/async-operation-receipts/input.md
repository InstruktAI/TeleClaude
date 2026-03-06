# Input: async-operation-receipts

## Problem Frame

- The API should not spend tens of seconds or minutes executing orchestration inside a request.
- Long-running work such as `telec todo work` should be acknowledged quickly, then completed outside request scope.
- The caller is usually an AI using a CLI tool, not a browser or a durable subscription client.

## Hard-Won Clarifications

1. Tmux injection is not the primary answer for long-running command results.
2. The agent feedback loop is not "subscribe to arbitrary events"; the natural model is receipt + poll.
3. A blocking CLI is still acceptable if it is implemented as submit + poll in the client.
4. Hiding the receipt completely inside a blocking wrapper is dangerous because recovery becomes fragile.
5. `next_work()` is not idempotent and should not be made idempotent.
6. The idempotency boundary is operation creation, not state-machine execution.
7. Simplicity wins: keep the agent-facing command blocking, but move all waiting to submit + poll behavior in the CLI.

## Desired End State

- API:
  - validates request
  - persists operation
  - returns receipt quickly
- Worker:
  - claims operation once
  - executes long-running function
  - records progress and terminal result
- CLI:
  - auto-waits by polling by default
  - never requires one long HTTP request
  - can recover if interrupted
  - always exposes the durable receipt needed for recovery

## Initial Target

- First adopter: `telec todo work`

Why first:

- It is the main source of slow-request behavior.
- It already carries important orchestration identity (`caller_session_id`).
- It is the route most likely to benefit from preserving current "blocking command" ergonomics while changing transport.

## Near-Term Follow-On Candidates

- `telec todo integrate`
- `DELETE /sessions/{id}`
- `/sessions/{id}/revive`

These are follow-on adopters, not first-pass scope.

## Architecture Principles To Preserve

- API is control plane, not execution lane.
- Durable state is the source of truth, not transient events.
- Eventing may accelerate updates but must not be required for correctness.
- Existing next-machine invariants stay intact:
  - per-repo+slug single-flight
  - finalize lock ownership
  - current `next_work()` result meaning

## Failure Cases That Must Shape the Design

1. Submit succeeded, but client never received the response.
2. Client received receipt, then wrapper process died.
3. Worker claimed operation, then daemon restarted.
4. Worker is alive but slow; caller must not confuse slow with stuck.
5. Duplicate submit caused by retry must not execute `next_work()` twice.

## Chosen Direction

1. `telec todo work` will remain blocking from the caller's perspective by default.
2. Under the hood, that blocking behavior will be implemented as `submit + poll + reattach`.
3. Receipt recovery is not optional. The command must always expose the durable handle needed to inspect or resume the operation.
4. Re-running the same command for the same caller while a matching operation is still active should reattach rather than enqueue a new execution.
5. Build only the amount of generic operation infrastructure needed to land `todo work` cleanly; broaden adoption later.

## Notes For Preparation

- Keep the implementation grounded in `todo work` first.
- Do not drift into an event-platform rewrite.
- Do not treat submit idempotency as workflow idempotency.
- Prefer an explicit, auditable contract over convenience that hides recovery semantics.
