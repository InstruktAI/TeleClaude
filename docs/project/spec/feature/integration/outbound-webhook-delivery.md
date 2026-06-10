---
description: 'Background worker that drains the webhook outbox and delivers HMAC-signed requests to subscriber endpoints with exponential backoff, transient/permanent failure classification, and dead-letter at max attempts.'
visibility: 'public'
---

# Outbound Webhook Delivery — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A delivery worker that drains the webhook outbox and delivers each entry
to its target subscriber endpoint. Entries are recorded by the dispatch
enqueue path (called when a matched contract has a URL target). The
worker batches due entries, claims each one atomically, signs the body
with an HMAC-SHA256 digest when a contract secret is set, and classifies
the response: success → delivered, permanent rejection → rejected,
transient failure → retry. Transient failures and timeouts retry with
exponential backoff (1s base doubling, 60s cap, 10 attempts) before
being dead-lettered.

v1 webhook outbox semantics are simple and standalone: the dispatch
enqueue happens whenever a matched contract has a URL target. There is
NO transactional outbox in v1 — the enqueue is not coordinated with the
producer's domain state change in any shared transaction; producers
don't even know their event will produce a webhook entry. The delivery
worker drains asynchronously, and the contract subscriber may see
retries until the delivery succeeds or the attempt budget is exhausted.

For the canonical aggregate shape, see `project/spec/domain/integration.md`.

## Canonical fields

### Use cases

#### UC-OW1: Successful delivery on first attempt

```gherkin
Given the dispatch enqueue recorded an outbox entry with target URL "https://sub.example.com/h", target secret "key", status "pending", next-attempt-at <= now
When the worker's polling tick runs
Then a fetch-batch call returns the entry (pending, due, unclaimed, oldest first, bounded batch)
And a claim call atomically sets the claim lock
And the delivery computes the signature "sha256=<hmac-sha256 over body under secret>"
And the subscriber endpoint receives the request with the standard content type and signature header
And the subscriber accepts the delivery
And the entry is marked delivered with delivered-at = now and the claim lock cleared
And a debug log "webhook delivered" is emitted
```

#### UC-OW2: Permanent client failure → rejected status

```gherkin
Given the subscriber rejects the delivery as a permanent client failure
When the delivery evaluates the response
Then it sets status="rejected", increments the attempt count, clears next-attempt-at
And a warning "webhook permanent failure" is logged
And the entry is NOT retried (rejected status excluded from fetch-batch)
```

#### UC-OW3: Transient server failure with exponential backoff

```gherkin
Given the subscriber returns a transient server failure on attempt 3
When the delivery evaluates the response
Then attempt count becomes 4
And the backoff for attempt 4 = 1.0 * 2^3 = 8.0 seconds (capped at 60s)
And next-attempt-at = now + 8 seconds
And status stays "pending"
And the next polling tick will re-claim the entry after the backoff elapses
```

#### UC-OW4: Timeout treated as transient

```gherkin
Given the client raises a timeout
When the delivery catches it
Then attempt count increments
And the failure is marked transient with cause "timeout"
And a warning "webhook timeout" is logged with the entry id
```

#### UC-OW5: Dead-letter at max attempts

```gherkin
Given an entry's attempt count reaches the max attempts (10)
When the failure path runs
Then the entry is marked dead-letter with no next-attempt-at
And an error "webhook dead-lettered after max attempts" is logged
And the entry is never re-fetched (dead-letter excluded from fetch-batch)
```

#### UC-OW6: Race-safe claim

```gherkin
Given two delivery workers (hypothetical multi-instance) poll the same batch
When both call claim on the same entry
Then exactly one claim succeeds (atomic compare-and-set)
And the other claim returns false
And the loser skips delivery for that entry
```

#### UC-OW7: Empty batch sleeps and retries

```gherkin
Given no entries are due
When fetch-batch returns an empty list
Then the worker sleeps for the poll interval (2 seconds)
And loops to the next iteration
```

#### UC-OW8: Shutdown stops the loop and closes the client

```gherkin
Given shutdown is initiated
When the worker's loop guard is evaluated
Then the loop exits
And the provider client is closed
And an "event loop is closed" runtime error during shutdown is suppressed with a debug log
```

#### UC-OW9: Loop-level exception is logged and retried

```gherkin
Given an unhandled exception occurs in the outer guard (persistence issue, parallel-fanout fault)
When the worker catches it
Then "webhook delivery loop failure, retrying" is logged with the exception info
And the worker sleeps for the poll interval before continuing
```

### Cross-context references

- Producer is `eventbus-hook-bridge` via the hook dispatcher's enqueue
  path (whenever a matched contract has a URL target).
- Consumes contracts managed by `subscriber-driven-contract-routing`
  (the named exception).
- Operates entirely in the integration context; no consumers outside
  integration call into the delivery worker.

## Known caveats

- The outbound signature header is `X-Hook-Signature` (TeleClaude
  convention), not `X-Hub-Signature-256` (GitHub-style). Inbound
  verification accepts both headers, but outbound signing emits the
  TeleClaude name exclusively.
- The permanent-client-failure rule applies to ALL client failure codes
  including "too many requests". A subscriber that rate-limits will see
  its contract fall into rejected state with no retry.
- The per-delivery timeout is 10 seconds; long-running subscribers will
  be cut off. There is no per-contract timeout override in v1.
- The provider client is lazily created on first delivery and reused
  for the worker's lifetime; shutdown order matters because closing the
  loop before the client triggers the "event loop is closed" runtime
  error, which the close path handles defensively.
- The delivery worker is single-instance per integration service;
  concurrent delivery across multiple subscribers is bounded by the
  per-batch loop (sequential per batch, batch size 25).
- No per-contract concurrency limits or per-host backoff; a flaky
  endpoint cannot be quarantined except via dead-letter.
- The body is taken verbatim from the entry's event payload (UTF-8
  encoded); there is no envelope wrapping with metadata about the
  contract id or delivery attempt — subscribers must rely on the hook
  event shape they declared in their contract.
