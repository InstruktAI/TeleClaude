# Review Findings: role-based-notifications

**Review round:** 2
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-14
**Verdict:** REQUEST CHANGES

---

## Round 1 Resolution Status

| Finding | Status             | Notes                                                            |
| ------- | ------------------ | ---------------------------------------------------------------- |
| C1      | Resolved           | Done-callback + try/except in `_notify_job_completion` — correct |
| C2      | Partially resolved | No longer marked "delivered", but see C3 below                   |
| I1      | Partially resolved | MAX_RETRIES added, but terminal state broken — see C3            |
| I2      | Resolved           | try/except around `load_person_config` — correct                 |
| I3      | Resolved           | Send/DB separated into independent try/except — correct          |
| I4      | Resolved           | HTTP status check + JSON parse safety — correct                  |
| I5      | Resolved           | Per-recipient try/except in router loop — correct                |
| I6      | Resolved           | 8 tests added covering all telegram.py paths                     |
| I7      | Resolved           | `attempt_count: int`, `created_at: str`, coercions removed       |
| S2      | Resolved           | Dead `* 1` removed                                               |
| S4      | Resolved           | Truncation warnings added                                        |

---

## Critical

### C3: Permanently failed rows re-selected every poll cycle (infinite loop)

**Files:** `teleclaude/notifications/worker.py:118-123, 130-138`, `teleclaude/core/db.py:1344-1348`

Both the **undeliverable path** (no chat_id, line 118) and the **max-retry exceeded path** (line 137) call `mark_notification_failed(row_id, attempt, "", error)` with `next_attempt_at=""`. This sets `status="failed"` but leaves `delivered_at=NULL`.

The `fetch_notification_batch` query (db.py:1346-1348) selects rows where:

- `delivered_at IS NULL` — true (never set)
- `status IN ('pending', 'failed')` — true
- `next_attempt_at <= now_iso` — `"" <= "2026-..."` is always true in SQLite string comparison

Result: the row is re-selected on every poll cycle (~1 second). The worker logs a warning/error and writes the same `mark_notification_failed` call, repeating forever. This produces unbounded log spam, wastes DB queries, and defeats both the C2 fix and the I1 fix.

Trace for undeliverable row:

1. Poll N: row fetched, no chat_id → `mark_notification_failed(id, 10, "", "No telegram_chat_id...")` → returns
2. Poll N+1: same row fetched again (status=failed, next_attempt_at="" <= now) → same call → infinite

Trace for max-retry row:

1. Poll N: attempt 10 >= MAX_RETRIES → `mark_notification_failed(id, 10, "", error)` → returns
2. Poll N+1: row re-fetched, send attempted (real HTTP call), fails → attempt 11 >= 10 → same mark → infinite (with actual retried sends for transient failures that recovered)

**Fix:** Add an `attempt_count` filter to `fetch_notification_batch`:

```python
.where(db_models.NotificationOutbox.attempt_count < MAX_RETRIES)
```

Or introduce a terminal status (e.g., `"dead_letter"`) that's excluded from the `IN` filter. The `attempt_count` filter is simplest and follows the existing query pattern.

---

## Important

No new important findings. All round 1 important issues (I1-I7) are resolved or subsumed by C3.

---

## Suggestions

### S1 (carried): `status: str` should use `Literal["pending", "delivered", "failed"]`

**File:** `teleclaude/core/db_models.py:137`

Not addressed in round 1 fixes. Still a minor improvement for type safety.

### S3 (carried): Recipient cache never invalidates at runtime

**File:** `teleclaude/notifications/worker.py:48-70`

Not addressed in round 1 fixes. Config changes require daemon restart.

### S5 (carried): Unrelated change in `extract_runtime_matrix.py`

**File:** `scripts/diagrams/extract_runtime_matrix.py`

Not addressed. Should be in a separate commit.

### S6 (carried): `_notification_file_for_job_result(job_result: object)` — `object` is too broad

**File:** `teleclaude/cron/runner.py:285`

Not addressed. The function probes for attributes that `JobResult` doesn't define.

### S7 (new): `test_telegram_api_ok_false_raises` doesn't cover the `ok: false` code path

**File:** `tests/unit/test_telegram.py:95-101`

The test uses `_error_response("chat not found")` which returns HTTP 400. Since `telegram.py:66` checks `status_code >= 400` first, this test exercises the HTTP error branch (lines 66-72), not the `ok: false` branch (lines 79-81). To cover lines 79-81, add a test with HTTP 200 and `{"ok": false, "description": "..."}`.

---

## Acceptance Criteria Coverage

| AC                                | Met?    | Evidence                                                          |
| --------------------------------- | ------- | ----------------------------------------------------------------- |
| AC1: Router resolves subscribers  | Yes     | discovery.py + router.py + tests                                  |
| AC2: Router writes outbox rows    | Yes     | router.py enqueues, never delivers                                |
| AC3: Worker delivers pending rows | Yes     | worker.py + test                                                  |
| AC4: Failed retried with backoff  | Partial | Backoff works, MAX_RETRIES exists, but terminal state broken (C3) |
| AC5: Telegram DM to chat_id       | Yes     | telegram.py + 8 unit tests                                        |
| AC6: Config channels parsed       | Yes     | schema.py + test_config_schema.py                                 |
| AC7: Unsubscribed get nothing     | Yes     | discovery + router + tests                                        |
| AC8: Failure isolation            | Yes     | Row-level isolation, send/DB separated                            |
| AC9: Existing adapter unaffected  | Yes     | New module, no changes to existing                                |

---

## Verification

- Lint: ruff format, ruff check, pyright — all pass (0 errors)
- Tests: 1477 passed, 0 failed
- All implementation-plan tasks checked `[x]`
- Build gates fully checked in quality-checklist.md

---

## Verdict: REQUEST CHANGES

**Critical issues (must fix):** 1 — C3 (permanently failed rows re-selected infinitely)
**Suggestions (carry-forward):** 5 — S1, S3, S5, S6, S7

The round 1 fixes are well-executed — error handling, type correctness, test coverage, and failure isolation are all solid. The single remaining critical issue is that the terminal state mechanism for permanently failed rows doesn't remove them from the fetch query, causing an infinite poll loop. This is a targeted fix (one line in the fetch query or a terminal status change).

---

## Fixes Applied (Round 1)

| Finding | Fix                                                                                                     | Commit     |
| ------- | ------------------------------------------------------------------------------------------------------- | ---------- |
| C1      | Attached done-callback to fire-and-forget tasks; wrapped `_notify_job_completion` in try/except         | `c59f1e09` |
| C2      | Mark missing-chat_id rows as failed (not delivered) using `mark_notification_failed` with `MAX_RETRIES` | `bcef0aad` |
| I1      | Added `MAX_RETRIES=10` constant; permanently fail rows exceeding cap                                    | `bcef0aad` |
| I2      | Wrapped `load_person_config` in try/except; log error and continue to next person                       | `d07ce011` |
| I3      | Separated `send_telegram_dm` and `mark_notification_delivered` into independent try/except blocks       | `bcef0aad` |
| I4      | Check HTTP status before JSON parse; wrap `response.json()` in try/except with descriptive errors       | `10f7c2ed` |
| I5      | Catch per-recipient failures in router enqueue loop; log and continue                                   | `888e85ae` |
| I6      | Added 8 unit tests for `send_telegram_dm` covering all paths (text, document, errors, edge cases)       | `636310c3` |
| I7      | Changed `attempt_count` to `int`, `created_at` to `str`; removed `or 0` coercion                        | `6e5e90f9` |
| S2      | Removed dead `* 1` in `_backoff_seconds`                                                                | `bcef0aad` |
| S4      | Added truncation warnings for message and caption                                                       | `10f7c2ed` |
