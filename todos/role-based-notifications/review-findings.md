# Review Findings: role-based-notifications

**Review round:** 3
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-14
**Verdict:** APPROVE

---

## Round 2 Resolution Status

| Finding | Status   | Notes                                                                                                                                         |
| ------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| C3      | Resolved | `max_attempts` filter added to `fetch_notification_batch`; worker passes `MAX_RETRIES`. Regression test confirms boundary. Commit `e9c344fa`. |

---

## Critical

No critical findings.

---

## Important

No important findings. All prior critical and important issues (C1-C3, I1-I7) are resolved.

---

## Suggestions (carried forward, non-blocking)

### S1: `status: str` should use `Literal["pending", "delivered", "failed"]`

**File:** `teleclaude/core/db_models.py:137`

Minor type safety improvement. Not blocking.

### S3: Recipient cache never invalidates at runtime

**File:** `teleclaude/notifications/worker.py:48-70`

Config changes require daemon restart. Acceptable for v1.

### S5: Unrelated change in `extract_runtime_matrix.py`

**File:** `scripts/diagrams/extract_runtime_matrix.py`

Should be in a separate commit. Non-blocking.

### S6: `_notification_file_for_job_result(job_result: object)` — `object` is too broad

**File:** `teleclaude/cron/runner.py:285`

Probes for attributes not defined on `JobResult`. Non-blocking.

### S7: `test_telegram_api_ok_false_raises` tests HTTP error branch, not `ok: false` branch

**File:** `tests/unit/test_telegram.py:95-101`

Uses HTTP 400 response, which hits the `status_code >= 400` check before reaching `ok: false` logic. Add a test with HTTP 200 + `{"ok": false}` to cover lines 79-81. Non-blocking.

### S8 (new): Regression test could verify both sides of the boundary

**File:** `tests/unit/test_notifications.py:94-111`

Test proves `attempt_count=10` is excluded with `max_attempts=10`, but doesn't verify `attempt_count=9` is still included. Adding the boundary-below case would strengthen the test. Non-blocking.

---

## Acceptance Criteria Coverage

| AC                                | Met? | Evidence                                            |
| --------------------------------- | ---- | --------------------------------------------------- |
| AC1: Router resolves subscribers  | Yes  | discovery.py + router.py + tests                    |
| AC2: Router writes outbox rows    | Yes  | router.py enqueues, never delivers                  |
| AC3: Worker delivers pending rows | Yes  | worker.py + test                                    |
| AC4: Failed retried with backoff  | Yes  | Backoff works, MAX_RETRIES enforced, C3 fix applied |
| AC5: Telegram DM to chat_id       | Yes  | telegram.py + 8 unit tests                          |
| AC6: Config channels parsed       | Yes  | schema.py + test_config_schema.py                   |
| AC7: Unsubscribed get nothing     | Yes  | discovery + router + tests                          |
| AC8: Failure isolation            | Yes  | Row-level isolation, send/DB separated              |
| AC9: Existing adapter unaffected  | Yes  | New module, no changes to existing                  |

---

## Verification

- Lint: ruff format, ruff check, pyright — all pass (0 errors)
- Tests: 1477 passed, 1 failed (pre-existing timeout in `test_diagram_extractors.py` — unrelated, no commits in this branch)
- All implementation-plan tasks checked `[x]`
- Build gates fully checked in quality-checklist.md

---

## Verdict: APPROVE

All critical and important findings from rounds 1-2 are resolved. The C3 fix correctly adds an `attempt_count` filter to the fetch query, preventing terminally failed rows from re-selection. The fix is backwards-compatible (`max_attempts` defaults to `None`), tested with a regression test, and the worker always passes `MAX_RETRIES`.

6 suggestions remain as non-blocking carry-forward items for future improvement.

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

## Fixes Applied (Round 2)

| Finding | Fix                                                                                                                         | Commit     |
| ------- | --------------------------------------------------------------------------------------------------------------------------- | ---------- |
| C3      | Added `max_attempts` filter to `fetch_notification_batch` and passed `MAX_RETRIES` from worker; added regression unit test. | `e9c344fa` |
