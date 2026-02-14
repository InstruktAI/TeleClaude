# Review Findings: webhook-service

**Review date:** 2026-02-14
**Reviewer:** Claude (automated multi-lane review)
**Review round:** 1
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: 4xx permanent failure marked as "delivered"

**Files:** `teleclaude/hooks/delivery.py:97-104`

4xx responses call `mark_webhook_delivered(row_id)`, which sets status to `"delivered"`. This masks permanent rejections (401, 403, 404, 422) as successful deliveries. Subscribers believe events were delivered when they were rejected. No error is captured in the DB row and there is no way to audit which webhooks failed.

**Fix:** Introduce a `"rejected"` or `"failed_permanent"` terminal status. Store the HTTP status code in `last_error`. Do not use `mark_webhook_delivered` for failures.

### C2: Double body read in inbound handler — blocking bug

**Files:** `teleclaude/hooks/inbound.py:91,95`

When signature verification is enabled, `await request.body()` consumes the stream. The subsequent `await request.json()` reads the stream again. In Starlette, `request.body()` is cached internally so this actually works, but the code should still use `json.loads(body)` from the already-read bytes for clarity and to avoid any framework-version dependency on caching behavior.

**Fix:** Replace `payload = await request.json()` (line 95) with `payload = json.loads(body)`.

### C3: Unbounded retries in delivery worker

**Files:** `teleclaude/hooks/delivery.py:105-128`

No max attempt count. A permanently-failing 5xx endpoint retries every 60 seconds indefinitely. `attempt_count` grows without bound. Rows remain in `"pending"` status forever, consuming DB writes and HTTP client resources.

**Fix:** Add `WEBHOOK_MAX_ATTEMPTS = 10` (or similar). When `attempt_count >= max`, mark with a terminal `"dead_letter"` status. Log at error level.

### C4: Secret exposure in API responses

**Files:** `teleclaude/hooks/api_routes.py:64`

`GET /hooks/contracts` returns HMAC secrets in plaintext in the response body via `_contract_to_response`. Secrets must be write-only.

**Fix:** Set `secret` to `None` (or a sentinel like `"***"`) in `ContractResponse`. Never return the actual secret value.

### C5: Missing contract target validation

**Files:** `teleclaude/hooks/api_routes.py:95-99`

Contract creation accepts `Target` with neither `handler` nor `url` set. Such contracts match events but silently drop them — the dispatcher's `if/elif` chain has no `else` branch to flag this. Also allows both `handler` and `url` set simultaneously (ambiguous routing).

**Fix:** Validate after Target construction: exactly one of `handler` or `url` must be non-None. Return HTTP 422 if invalid.

---

## Important

### I1: Delivery worker loop crashes permanently on DB exceptions

**Files:** `teleclaude/hooks/delivery.py:58-78`

The `run()` method wraps the entire loop in a single try/finally. Any unhandled exception from `db.fetch_webhook_batch()` or `db.claim_webhook()` terminates the delivery loop permanently. The daemon's `_log_background_task_exception` callback logs it, but the worker is dead until daemon restart.

**Fix:** Wrap the inner loop body in try/except. On DB errors, log at error level and sleep with backoff before continuing.

### I2: `_init_webhook_service` kills daemon on failure

**Files:** `teleclaude/daemon.py:1517-1552`

No try/except. If any step fails (DB error in `load_from_db`, config parse error), the exception propagates to `start()` which kills the entire daemon. The webhook subsystem is optional — its failure should not prevent sessions, polling, and other core functionality from running.

**Fix:** Wrap `_init_webhook_service()` call in `start()` with try/except. Log the error and continue without webhook service.

### I3: Cache cleared before loading in `load_from_db` — race condition

**Files:** `teleclaude/hooks/registry.py:20-30`

`self._cache.clear()` happens before contracts are loaded. If the DB call raises after clear, or if contracts fail deserialization, the cache is empty or partial. Concurrent `match()` calls during the window see incomplete data.

**Fix:** Build new cache in a temporary dict, then swap atomically: `new_cache = {}; ...; self._cache = new_cache`.

### I4: Dispatcher silently drops events for invalid targets

**Files:** `teleclaude/hooks/dispatcher.py:51-81`

When a matched contract has neither `handler` nor `url`, the dispatch loop silently skips it. No warning is logged. Events disappear with no trace.

**Fix:** Add an `else` branch logging a warning: `"Contract %s matched but has no handler or URL"`.

### I5: Missing `exc_info=True` on error log calls

**Files:** `delivery.py:128`, `dispatcher.py:59-64,75-81`, `config.py:79-80,97-98`, `inbound.py:113`, `registry.py:29`

Many `logger.error()` calls in catch blocks include only `str(exc)` but not the traceback. Stack traces are essential for debugging production issues. Only `bridge.py:114` correctly uses `exc_info=True`.

**Fix:** Add `exc_info=True` to all `logger.error()` calls in catch blocks.

### I6: Config loading swallows errors with no summary

**Files:** `teleclaude/hooks/config.py:79-80`

Individual subscription loading failures are logged at error level, but the system starts with partial contracts and no summary. Operator may not notice missing subscriptions.

**Fix:** Accumulate failure count and log a summary after the loop: `"Loaded X of Y subscriptions (Z failed)"`.

---

## Test Gaps

### T1: Delivery worker `_deliver()` method entirely untested (severity 9/10)

**Files:** `tests/unit/test_webhook_service.py`

Only `compute_signature` and `compute_backoff` helpers are tested. The actual delivery logic (5 response branches, HMAC header injection) has zero coverage.

### T2: Inbound endpoint framework entirely untested (severity 8/10)

**Files:** `teleclaude/hooks/inbound.py` — 124 lines, zero tests

Security-critical HMAC verification, challenge-response, normalizer dispatch, and error resilience are all unverified.

### T3: Dispatcher error handling paths untested (severity 8/10)

Handler exceptions, missing handlers, and enqueue failures — all three error branches are untested.

### T4: API routes module untested (severity 7/10)

`GET/POST/DELETE /hooks/contracts` and `GET /hooks/properties` — no coverage. The registry-not-initialized 503 path is also untested.

### T5: Signature correctness not verified against known value

`test_compute_signature` checks format only (`startswith("sha256=")`, `len > 10`). A bug producing the wrong hash would pass.

---

## Suggestions

### S1: Dead config types — `SubscriptionContractConfig` and `SubscriptionTargetConfig`

**Files:** `teleclaude/config/schema.py:133-143`

These Pydantic models are defined but never referenced by `SubscriptionConfig`, which uses `Dict[str, Any]` instead. Either wire them in or remove them.

### S2: `Contract` should be frozen

**Files:** `teleclaude/hooks/webhook_models.py:64`

No evidence of post-construction mutation in the codebase. Making it `@dataclass(frozen=True)` would prevent accidental cache mutations.

### S3: `PropertyCriterion` should enforce match/pattern mutual exclusivity

**Files:** `teleclaude/hooks/webhook_models.py:46-52`

Setting both `match` and `pattern` creates silently broken behavior — `pattern` wins, `match` is ignored. Add a `__post_init__` check.

### S4: Daemon accesses private `_cache` attribute

**Files:** `teleclaude/daemon.py:1552`

`len(contract_registry._cache)` should use a public method or property.

### S5: `EnqueueWebhook` Protocol return type mismatch

**Files:** `teleclaude/hooks/dispatcher.py:16-26`

Protocol returns `None`, but `db.enqueue_webhook` returns `int`. Type-checkers may flag this.

---

## Verdict: REQUEST CHANGES

5 Critical issues, 6 Important issues, 5 Test gaps requiring attention before merge.

The implementation quality is high overall — clean separation of concerns, correct architectural patterns, and solid model design. The issues are primarily around error handling resilience, security (secret exposure), and test coverage gaps.

## Fixes Applied

### C1: 4xx responses now terminal reject (not delivered)

- Fix: `teleclaude/hooks/delivery.py` marks permanent 4xx as `status="rejected"` and stores failure details in `last_error`.
- Commit: 9083e8cf

### C2: Signed inbound endpoint parses body once

- Fix: `teleclaude/hooks/inbound.py` parses inbound payload from `body = await request.body()` using `json.loads(body)` after signature validation.
- Commit: 9083e8cf

### C3: Max attempts and dead-letter terminal status added

- Fix: `teleclaude/hooks/delivery.py` introduces `WEBHOOK_MAX_ATTEMPTS` and moves failed rows to `status="dead_letter"` when exceeded.
- Commit: 9083e8cf

### C4: Secret redaction in contract responses

- Fix: `teleclaude/hooks/api_routes.py:_contract_to_response` now returns `target.secret = None`.
- Commit: 9083e8cf

### C5: Target validation in create contract

- Fix: `teleclaude/hooks/api_routes.py:create_contract` now validates that exactly one of `handler` or `url` is set and rejects invalid requests with HTTP 422.
- Commit: 9083e8cf

### I1: Delivery loop survives DB errors

- Fix: `teleclaude/hooks/delivery.py:run` wraps iteration in `try/except` and retries after `WEBHOOK_POLL_INTERVAL_S` on errors.
- Commit: 9083e8cf

### I2: Webhook subsystem init is non-fatal

- Fix: `teleclaude/daemon.py:start` catches `_init_webhook_service` exceptions and continues startup.
- Commit: 9083e8cf

### I3: Atomic contract cache swap

- Fix: `teleclaude/hooks/registry.py:load_from_db` now builds a temporary cache and swaps to `_cache` only after successful parsing.
- Commit: 9083e8cf

### I4: Invalid contract targets are logged

- Fix: `teleclaude/hooks/dispatcher.py` adds warning branch for matched contracts lacking handler/url.
- Commit: 9083e8cf

### I5: Catch-block logs include tracebacks

- Fix: `teleclaude/hooks/config.py`, `teleclaude/hooks/delivery.py`, `teleclaude/hooks/inbound.py`, `teleclaude/hooks/registry.py`, and `teleclaude/hooks/dispatcher.py` add `exc_info=True`.
- Commit: 9083e8cf

### I6: Hook subscription load summary added

- Fix: `teleclaude/hooks/config.py:load_hooks_config` now summarizes successful vs failed subscription loads.
- Commit: 9083e8cf

### T1: Delivery worker branches and header behavior now covered

- Fix: Added unit tests for rejected delivery, dead-lettering, and known signature value.
- Commit: 9083e8cf

### T2: Inbound endpoint framework coverage added

- Fix: Added tests for signature checks, GET verification challenges, bad payload handling, normalizer exceptions, and dispatch failures.
- Commit: 9083e8cf

### T3: Dispatcher failure branches covered

- Fix: Added tests for missing handler, handler exception, and enqueue failure paths.
- Commit: 9083e8cf

### T4: API route coverage added

- Fix: Added tests for contract CRUD/listing endpoints and registry-missing 503 behavior.
- Commit: 9083e8cf

### T5: Signature correctness now verifies exact HMAC output

- Fix: Updated test to assert exact HMAC signature value.
- Commit: 9083e8cf

Priority order for fixes:

1. C1 + C3: Fix delivery worker status handling and add retry cap
2. C4: Remove secret from API responses
3. C5 + I4: Target validation and dispatcher warning
4. I1: Add per-iteration error handling in delivery loop
5. I2: Graceful degradation for webhook init failure
6. I3: Atomic cache swap
7. T1-T4: Add missing test coverage
