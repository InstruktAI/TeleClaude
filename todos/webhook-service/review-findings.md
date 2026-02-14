# Review Findings: webhook-service

**Review date:** 2026-02-14
**Reviewer:** Claude (automated multi-lane review)
**Review round:** 2
**Verdict:** APPROVE

---

## Round 2 Assessment

All 16 findings from Round 1 (5 Critical, 6 Important, 5 Test gaps) have been addressed correctly. The fixes are well-scoped, introduce no regressions, and the new tests are correct and sufficient.

### R1 Critical — All Fixed

| Finding                         | Fix                                                     | Verified                      |
| ------------------------------- | ------------------------------------------------------- | ----------------------------- |
| C1: 4xx marked as "delivered"   | `status="rejected"` terminal status with error captured | Yes — `delivery.py:119-127`   |
| C2: Double body read in inbound | `json.loads(body)` from already-read bytes              | Yes — `inbound.py:86,99`      |
| C3: Unbounded retries           | `WEBHOOK_MAX_ATTEMPTS=10`, dead-letter terminal status  | Yes — `delivery.py:27,88-95`  |
| C4: Secret exposure in API      | `secret: None` in response DTO                          | Yes — `api_routes.py:64`      |
| C5: Missing target validation   | Exactly-one-of check with HTTP 422                      | Yes — `api_routes.py:100-106` |

### R1 Important — All Fixed

| Finding                               | Fix                                                     | Verified                    |
| ------------------------------------- | ------------------------------------------------------- | --------------------------- |
| I1: Delivery loop crashes on DB error | Per-iteration try/except with sleep-and-retry           | Yes — `delivery.py:61-82`   |
| I2: Webhook init kills daemon         | try/except in `start()`, continues without webhooks     | Yes — `daemon.py:1578-1581` |
| I3: Cache race on load                | Atomic swap via temporary dict                          | Yes — `registry.py:23-30`   |
| I4: Silent drops for invalid targets  | Warning log in else branch                              | Yes — `dispatcher.py:84-85` |
| I5: Missing exc_info in catch blocks  | `exc_info=True` added to all error logs in catch blocks | Yes — all 6 files           |
| I6: Config load summary missing       | Counts tracked and summary logged                       | Yes — `config.py:41,80-90`  |

### R1 Test Gaps — All Addressed

| Gap                              | Coverage Added                                                                | Verified |
| -------------------------------- | ----------------------------------------------------------------------------- | -------- |
| T1: Delivery worker `_deliver()` | 3 tests: 4xx→rejected, dead-letter, run recovery                              | Yes      |
| T2: Inbound endpoint framework   | 4 tests: signed payload, bad JSON, normalizer error, dispatch error           | Yes      |
| T3: Dispatcher error paths       | 3 tests: missing handler, handler failure, enqueue failure                    | Yes      |
| T4: API routes                   | 4 tests: target validation, secret redaction, 503 guard, full HTTP round-trip | Yes      |
| T5: Signature correctness        | Exact HMAC value assertion                                                    | Yes      |

Test count: 32 original + 15 new = 47 unit tests.

### R1 Suggestions — Deferred (Non-blocking)

S1-S5 from Round 1 were suggestions, not blocking issues. They remain unaddressed and are acceptable for merge:

- S1: Dead config types (`SubscriptionContractConfig`, `SubscriptionTargetConfig`) — cleanup opportunity
- S2: `Contract` frozen — not feasible without refactoring registry mutation patterns
- S3: `PropertyCriterion` match/pattern mutual exclusivity — defensive improvement
- S4: Daemon accesses private `_cache` — add `__len__` or property to `ContractRegistry`
- S5: `EnqueueWebhook` Protocol return type — cosmetic type mismatch

---

## Round 2 New Findings

No new Critical or Important issues were introduced by the fixes.

### Suggestions

#### S6: Misleading format string in `_mark_failed` log

**File:** `teleclaude/hooks/delivery.py:100`

The format string uses `status=%s` but the argument is `reason` (e.g., "HTTP 500"), not a status value. Cosmetic.

#### S7: `daemon.py:1552` still accesses `_cache` directly

Carried from S4. `len(contract_registry._cache)` could use a public method.

---

## Verdict: APPROVE

The implementation is solid. All critical security (secret exposure, HMAC verification), resilience (crash recovery, retry caps, atomic operations), and correctness (status tracking, error handling) issues from Round 1 have been properly resolved. Test coverage is comprehensive at 47 tests across all subsystem modules.
