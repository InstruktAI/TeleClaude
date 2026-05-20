---
id: 'project/spec/feature/integration/outbound-webhook-delivery'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Background worker that drains the webhook_outbox table and delivers HMAC-signed POST requests to subscriber URLs with exponential backoff, transient/permanent failure classification, and dead-letter at max attempts.'
---

# Outbound Webhook Delivery — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The `WebhookDeliveryWorker` async loop that drains the SQLite
`WebhookOutbox` table and delivers each entry to its target URL via
`httpx.AsyncClient.post`. Rows are written by `enqueue_webhook` (called
from `HookDispatcher.dispatch` when a matched Contract has a URL target).
The worker batches due rows, claims each one atomically, signs the body
with HMAC-SHA256 when a contract secret is set, and classifies the HTTP
response: 2xx/3xx → delivered, 4xx → permanent rejection, 5xx → transient
retry. Transient failures and timeouts retry with exponential backoff
(1s base doubling, 60s cap, 10 attempts) before being dead-lettered.

v1 webhook outbox semantics are simple and standalone: `enqueue_webhook`
is a single SQLite INSERT performed from `HookDispatcher.dispatch` when a
matched Contract has a URL target. There is NO transactional outbox in
v1 — `enqueue_webhook` is not coordinated with the producer's domain
state change in any database transaction; producers don't even know
their event will produce a webhook row. The dispatcher worker drains
asynchronously, and the contract endpoint may see retries until the
delivery succeeds or the attempt budget is exhausted.

## Canonical fields

### Use cases

#### UC-OW1: Successful delivery on first attempt

```gherkin
Given enqueue_webhook wrote a row with target_url="https://sub.example.com/h", target_secret="key", status="pending", next_attempt_at <= now
When the worker's polling tick runs
Then fetch_webhook_batch returns the row (status=pending, next_attempt_at<=now, locked_at IS NULL, ordered by created_at, limit 25)
And claim_webhook atomically sets locked_at = now (CAS)
And _deliver computes X-Hook-Signature = "sha256=" + hmac.sha256(body, secret).hexdigest()
And httpx.AsyncClient.post is invoked with Content-Type: application/json and the signature header
And response.status_code = 200
And db.mark_webhook_delivered records status=delivered, delivered_at=now, locked_at=NULL
And a debug log "Webhook delivered" is emitted
```

#### UC-OW2: 4xx permanent failure → rejected status

```gherkin
Given the subscriber returns HTTP 422
When _deliver evaluates the response
Then it sets status="rejected", increments attempt_count, clears next_attempt_at
And a warning "Webhook permanent failure (4xx)" is logged
And the row is NOT retried (status=rejected excluded from fetch_webhook_batch)
```

#### UC-OW3: 5xx transient failure with exponential backoff

```gherkin
Given the subscriber returns HTTP 503 on attempt 3
When _deliver evaluates the response
Then attempt_count becomes 4
And compute_backoff(4) = 1.0 * 2^3 = 8.0 seconds (capped at 60s)
And next_attempt_at = now + 8 seconds
And status stays "pending"
And the next polling tick will re-claim the row after the backoff elapses
```

#### UC-OW4: Timeout treated as transient

```gherkin
Given httpx raises TimeoutException
When _deliver catches it
Then attempt_count increments
And _mark_failed("timeout", attempt) is called with the transient retry path
And a warning "Webhook timeout: row=<id>" is logged
```

#### UC-OW5: Dead-letter at WEBHOOK_MAX_ATTEMPTS

```gherkin
Given a row's attempt_count reaches WEBHOOK_MAX_ATTEMPTS (10)
When _mark_failed runs
Then db.mark_webhook_failed is called with status="dead_letter", next_attempt_at=None
And an error "Webhook dead-lettered after max attempts" is logged
And the row is never re-fetched (dead_letter excluded from fetch_webhook_batch)
```

#### UC-OW6: Race-safe claim

```gherkin
Given two delivery workers (hypothetical multi-instance) poll the same batch
When both call claim_webhook(row_id, now_iso)
Then the SQL UPDATE WHERE status="pending" AND locked_at IS NULL succeeds for exactly one
And the other claim_webhook returns False
And the loser skips _deliver for that row
```

#### UC-OW7: Empty batch sleeps and retries

```gherkin
Given no rows are due
When fetch_webhook_batch returns []
Then the worker sleeps WEBHOOK_POLL_INTERVAL_S (2 seconds)
And loops to the next iteration
```

#### UC-OW8: Shutdown stops the loop and closes the client

```gherkin
Given shutdown_event is set
When the worker's while-loop guard is evaluated
Then the loop exits
And self.close() awaits httpx.AsyncClient.aclose
And RuntimeError("Event loop is closed") during shutdown is suppressed with a debug log
```

#### UC-OW9: Loop-level exception is logged and retried

```gherkin
Given an unhandled exception occurs in the outer try (DB issue, asyncio.gather fault)
When the worker catches it
Then logger.error("Webhook delivery loop failure, retrying") is emitted with exc_info
And the worker sleeps WEBHOOK_POLL_INTERVAL_S before continuing
```

### Implementation pointers (v1)

- `teleclaude/hooks/delivery.py` —
  `WebhookDeliveryWorker` (L42),
  `_deliver` (inside the class),
  `_mark_failed` (inside the class),
  `compute_signature` (L30),
  `compute_backoff` (L36).
- `teleclaude/core/db/_webhooks.py` — `DbWebhooksMixin`:
  `enqueue_webhook`, `fetch_webhook_batch`, `claim_webhook`,
  `mark_webhook_delivered`, `mark_webhook_failed`.
- `teleclaude/daemon_event_platform.py` — task spawn inside
  `_init_webhook_service` (~L569):
  `self.webhook_delivery_task = asyncio.create_task(
delivery_worker.run(self.shutdown_event), name="webhook-delivery")`.
- Constants (top of `delivery.py`):
  - `WEBHOOK_POLL_INTERVAL_S = 2.0`
  - `WEBHOOK_BATCH_SIZE = 25`
  - `WEBHOOK_BASE_BACKOFF_S = 1.0`
  - `WEBHOOK_MAX_BACKOFF_S = 60.0`
  - `WEBHOOK_DELIVERY_TIMEOUT_S = 10.0`
  - `WEBHOOK_MAX_ATTEMPTS = 10`
- DB schema: `WebhookOutbox` table with columns `id`, `contract_id`,
  `event_json`, `target_url`, `target_secret`, `status`, `created_at`,
  `next_attempt_at`, `attempt_count`, `locked_at`, `last_error`,
  `delivered_at`.

### Cross-context references

- Producer is `eventbus-hook-bridge` via `HookDispatcher.dispatch` →
  `enqueue_webhook` (whenever a matched Contract has a URL target).
- Consumes Contracts managed by
  `subscriber-driven-contract-routing` (the named exception).
- Operates entirely in the integration context; no consumers outside
  integration call into the delivery worker.

## Known caveats

- The signature header is `X-Hook-Signature` (TeleClaude convention),
  not `X-Hub-Signature-256` (GitHub-style). Inbound verification
  accepts both headers, but outbound signing emits the TeleClaude name
  exclusively.
- The 4xx → rejected rule applies to ALL 4xx codes including 429
  (Too Many Requests). A subscriber that rate-limits will see its
  contract fall into rejected state with no retry.
- `WEBHOOK_DELIVERY_TIMEOUT_S = 10.0` applies per request; long-running
  subscribers will be cut off. There is no per-contract timeout
  override in v1.
- The `httpx.AsyncClient` is lazily created on first delivery and
  reused for the worker's lifetime; shutdown order matters because
  closing the loop before the client triggers the "Event loop is
  closed" RuntimeError, which the close path handles defensively.
- The delivery worker is single-instance per daemon; concurrent
  delivery across multiple subscribers is bounded by the for-loop
  inside `run` (sequential per batch, batch size 25).
- No per-contract concurrency limits or per-host backoff; a flaky
  endpoint cannot be quarantined except via dead-letter.
- The body is taken verbatim from `row.event_json` (UTF-8 encoded);
  there is no envelope wrapping with metadata about the contract id or
  delivery attempt — subscribers must rely on the HookEvent shape they
  declared in their Contract.
