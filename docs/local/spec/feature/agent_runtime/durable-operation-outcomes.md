---
description: Every durable operation reaches its recorded caller — completion, failure,
  and staleness each wake the caller with an address, and a caller-less operation
  stands on its row alone.
---

# Durable Operation Outcomes — Spec

## Required reads

- @docs/local/design/architecture/operation-receipts.md
- @docs/local/design/architecture/command-classification.md

## What it is

A command whose work finishes after its response carries a durable operation
row. This surface is what that row does when the work ends: it records who
asked, it reaches a terminal state exactly once, and it tells the asking session
where to read the answer.

Three terminal states are outcomes, not degrees of one. Completion and failure
each emit their own event type. Staleness — an operation abandoned by a daemon
restart or silent past its heartbeat window — is the third, and it delivers like
the other two, so a caller learns its work was abandoned instead of waiting out
a timeout that never arrives.

The wake carries an address, never the record. The row holds the result, the
error, and the progress detail; the caller reads them when it arrives.

## Canonical fields

### Use cases

#### UC-DO1: An operator can read the result of completed asynchronous work

```gherkin
Given an agent acting for a person started asynchronous work
When that work completes successfully
Then the caller can read its result from the operation record
And the caller is told which operation to read
```

#### UC-DO2: An operator can read why asynchronous work failed

```gherkin
Given an agent acting for a person started asynchronous work
When that work fails
Then the caller can read the error from the operation record
And the caller is told which operation to read
And the failure is distinct from a successful outcome
```

#### UC-DO3: An operator can learn when asynchronous work was abandoned

```gherkin
Given an agent acting for a person started asynchronous work
When a daemon restart or an expired heartbeat leaves that work abandoned
Then the caller can read that it ended stale rather than remaining in progress
And the work is not replayed automatically
```

#### UC-DO4: A caller-less operation writes its row and wakes nobody

#### UC-DO5: A caller that has gone away costs the row nothing

#### UC-DO6: A command cannot present asynchronous work as synchronous

#### UC-DO7: Only the outcome notification crosses back to the caller's computer

## Known caveats

- **The row is the authority; the event is a nudge.** A consumer that sees an
  outcome event before the row is terminal trusts the row.
- **Work is never replayed.** A stale transition reports abandonment; it does
  not restart the work. Resubmission is the caller's decision.
- **Delivery is best-effort by design.** A wake that cannot be handed off is
  dropped without retry, because the durable row already carries the outcome.

## See Also

- docs/local/adr/0098-async-work-always-carries-a-receipt.md
- docs/local/design/architecture/operation-receipts.md — receipt submission, terminal transitions, and outcome delivery.
- docs/local/design/architecture/command-classification.md — response modes, event declarations, and computer-boundary relays.
- docs/local/spec/feature/agent_runtime/control-delivery.md
