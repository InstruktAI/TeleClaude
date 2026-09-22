---
description: Every durable operation reaches its recorded caller — completion, failure, and staleness each wake the caller with an address, and a caller-less operation stands on its row alone.
delivered_by:
  - no-async-work-without-a-receipt
---

# Durable Operation Outcomes — Spec

## Required reads

- @docs/project/design/architecture/operation-receipts.md
- @docs/project/design/architecture/command-classification.md

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

#### UC-DO1: A completed operation wakes the caller that asked for it

```gherkin
Given a durable operation was submitted by a live caller session
When the operation's work finishes successfully
Then the row reaches its completed state carrying the result
And the command's success event is emitted as the final step of that same terminal write
And the caller session is woken with the operation's identity, its outcome, and the command that reads the record
And the wake carries no part of the result text
```

#### UC-DO2: A failed operation delivers its failure by event type

```gherkin
Given a durable operation was submitted by a live caller session
When the operation's work raises
Then the row reaches its failed state carrying the error
And the command's failure event is emitted, distinct in type from its success event
And no consumer reads the outcome from a field on a shared event type
And the caller session is woken with the operation's identity, its outcome, and the command that reads the record
```

#### UC-DO3: Staleness is an outcome and reaches the caller

```gherkin
Given durable operations are queued or running when the daemon stops
When the daemon starts again and normalizes them to stale
Then each stale transition emits its command's failure event
And each recorded caller that is still live is woken with the operation's identity, its outcome, and the command that reads the record
And an operation whose heartbeat window expires while running reaches the same stale outcome and delivers the same way
```

#### UC-DO4: A caller-less operation writes its row and wakes nobody

```gherkin
Given a durable operation is submitted with no caller session recorded
When the operation reaches any terminal state
Then the row records that outcome exactly as it would for a recorded caller
And the outcome event is emitted
And no wake is attempted and nothing is lost, because the row answers whoever reads it later
```

#### UC-DO5: A caller that has gone away costs the row nothing

```gherkin
Given a durable operation recorded a caller session that is no longer live
When the operation reaches a terminal state
Then the wake fails and is not retried
And the row is unchanged and still answers a later reader
```

#### UC-DO6: A command cannot present asynchronous work as synchronous

```gherkin
Given a command declares its response mode and its outcome events
When the command is constructed
Then a receipt-backed mode without both a success event and a failure event is rejected
And an immediate mode that declares either outcome event is rejected
And the invalid command never reaches the dispatcher
```

#### UC-DO7: The owning computer owns the row and the emission

```gherkin
Given a caller on one computer submits a receipt-backed command for a session another computer owns
When the command is dispatched
Then the owning computer persists the row, runs the work, and emits the outcome event locally
And the receipt returned to the caller names the owning computer
And only the outcome notification crosses the machine boundary, to be delivered locally to the caller's session
And the caller reads the full record on the computer the receipt names
```

## Known caveats

- **The row is the authority; the event is a nudge.** A consumer that sees an
  outcome event before the row is terminal trusts the row.
- **Work is never replayed.** A stale transition reports abandonment; it does
  not restart the work. Resubmission is the caller's decision.
- **Delivery is best-effort by design.** A wake that cannot be handed off is
  dropped without retry, because the durable row already carries the outcome.

## See Also

- docs/project/adr/0098-async-work-always-carries-a-receipt.md
- docs/project/spec/feature/agent_runtime/control-delivery.md
