# Review Findings: role-based-notifications

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-14
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: `_run_coro_safely` discards task reference — silent error swallowing

**File:** `teleclaude/cron/runner.py:294-301`

When a running event loop exists, `loop.create_task(coro)` discards the returned `Task`. Any exception from `NotificationRouter.send_notification()` is silently lost (Python emits a warning to stderr but it never reaches application logs). Additionally, `_notify_job_completion` (lines 304-328) has no try/except, so in the sync path (`asyncio.run`), notification errors crash the job runner after the job itself succeeded.

**Fix:** Store the task, attach a done-callback that logs exceptions. Wrap the `_run_coro_safely` call in `_notify_job_completion` with try/except so notification failures never crash the cron runner.

### C2: Missing recipient marked "delivered" instead of "undeliverable"

**File:** `teleclaude/notifications/worker.py:113-117`

When a recipient has no configured `telegram_chat_id`, the row is marked `status="delivered"` with `delivered_at` set. The message was never sent, but the DB records it as successful delivery. Any monitoring counting `status="delivered"` gets inflated success counts.

**Fix:** Either introduce a distinct status (e.g., `"undeliverable"`) or use `mark_notification_failed` with a high attempt count and clear error message so the row is not retried but is correctly classified as failed.

---

## Important

### I1: No maximum retry limit — unbounded retries

**File:** `teleclaude/notifications/worker.py:122-132`

The worker increments `attempt_count` and applies exponential backoff capped at 60s, but there is no maximum retry threshold. A permanently failing notification (blocked bot, invalid chat_id) is retried forever. The `fetch_notification_batch` query selects `status IN ('pending', 'failed')` with no attempt count filter.

**Fix:** Add a max retry constant (e.g., 10). After exceeding it, mark the row as permanently failed with a distinct status or set `delivered_at` to prevent re-selection.

### I2: One bad person config aborts all discovery

**File:** `teleclaude/notifications/discovery.py:60-76`

`_iter_person_configs` has no try/except around `load_person_config`. If any single person's `teleclaude.yml` has invalid YAML or fails Pydantic validation, the entire discovery process raises, preventing ALL notifications from routing for ALL channels.

**Fix:** Wrap `load_person_config` in try/except, log the error, and continue to the next person.

### I3: `_deliver_row` conflates send failure with DB update failure

**File:** `teleclaude/notifications/worker.py:119-132`

A single `except Exception` catches both `send_telegram_dm` errors (message NOT sent — retry is safe) and `mark_notification_delivered` errors (message WAS sent — retry causes duplicate). If the Telegram send succeeds but the DB update fails, the row is retried and the message re-sent as a duplicate.

**Fix:** Separate the send and DB update into two try/except blocks. If the send succeeds but DB fails, log an error but do not schedule retry.

### I4: `response.json()` crashes on non-JSON responses

**File:** `teleclaude/notifications/telegram.py:60`

HTTP 502/503 from a proxy returns HTML, not JSON. `response.json()` raises `JSONDecodeError` with an unhelpful error message. The HTTP status code is never checked before parsing.

**Fix:** Check `response.status_code` first. Wrap `response.json()` in try/except for `JSONDecodeError` with a descriptive error message including the status code.

### I5: Router DB error on one recipient skips remaining

**File:** `teleclaude/notifications/router.py:36-43`

If `enqueue_notification` fails mid-loop (DB error, constraint violation), the exception propagates and remaining recipients are skipped. Already-enqueued rows are committed but the caller gets an exception instead of a partial result.

**Fix:** Catch per-recipient failures in the loop, log them, and continue enqueuing remaining recipients.

### I6: `send_telegram_dm` completely untested

**File:** `teleclaude/notifications/telegram.py` (all 67 lines)

The only external I/O boundary in the pipeline has zero test coverage. Token validation, empty content validation, file handling, API error parsing, message truncation, and both HTTP paths (`sendMessage` vs `sendDocument`) are all untested.

**Fix:** Add unit tests with mocked `httpx.AsyncClient` covering: successful text/document sends, missing token, empty content, file not found, Telegram API `ok: false` responses.

### I7: Type annotations misrepresent nullability

**File:** `teleclaude/core/db_models.py:138-140`

- `attempt_count: Optional[int] = 0` — field is never None; forces defensive `or 0` coercion in `fetch_notification_batch` (db.py:1366).
- `created_at: Optional[str] = None` — always set at enqueue time (db.py:1323); SQL schema says `NOT NULL`.

**Fix:** Change to `attempt_count: int = 0` and `created_at: str = ""` (or use `Field(default_factory=...)`). Remove the `or 0` coercion in `fetch_notification_batch`.

---

## Suggestions

### S1: `status: str` should use `Literal["pending", "delivered", "failed"]`

**File:** `teleclaude/core/db_models.py:137`, `teleclaude/core/db.py:46`

Makes the state machine explicit and catches typos at type-check time.

### S2: No-op multiplication in `_backoff_seconds`

**File:** `teleclaude/notifications/worker.py:53`

`float(base * 1)` — the `* 1` is dead code. Remove it.

### S3: Recipient cache never invalidates at runtime

**File:** `teleclaude/notifications/worker.py:46-69`

`_recipient_cache_dirty` is only `True` at init. Config changes require daemon restart. Consider TTL-based refresh.

### S4: Silent message truncation

**File:** `teleclaude/notifications/telegram.py:47, 55`

Messages and captions are silently truncated to 4000/1024 chars. Log a warning when truncation occurs.

### S5: Unrelated change in `extract_runtime_matrix.py`

**File:** `scripts/diagrams/extract_runtime_matrix.py`

The `transcript_path=` pattern detection change is unrelated to notifications. Should be in a separate commit.

### S6: `_notification_file_for_job_result(job_result: object)` — `object` is too broad

**File:** `teleclaude/cron/runner.py:285`

The function probes for `file_path`, `report_path`, `artifact_path` via `getattr`, but `JobResult` doesn't define any of these. The function always returns `None` for standard `JobResult`. Consider adding `file_path: str | None = None` to `JobResult` directly.

---

## Acceptance Criteria Coverage

| AC                                | Met?    | Evidence                                             |
| --------------------------------- | ------- | ---------------------------------------------------- |
| AC1: Router resolves subscribers  | Yes     | discovery.py + router.py + tests                     |
| AC2: Router writes outbox rows    | Yes     | router.py enqueues, never delivers                   |
| AC3: Worker delivers pending rows | Yes     | worker.py + test                                     |
| AC4: Failed retried with backoff  | Partial | Backoff works, but no max retry cap (I1)             |
| AC5: Telegram DM to chat_id       | Yes\*   | telegram.py works but is untested (I6)               |
| AC6: Config channels parsed       | Yes     | schema.py + test_config_schema.py                    |
| AC7: Unsubscribed get nothing     | Yes     | discovery + router + tests                           |
| AC8: Failure isolation            | Partial | Row-level isolation works but send/DB conflated (I3) |
| AC9: Existing adapter unaffected  | Yes     | New module, no changes to existing                   |

---

## Verdict: REQUEST CHANGES

**Critical issues (must fix):** 2 — C1 (fire-and-forget error swallowing), C2 (delivered vs undeliverable)
**Important issues:** 7 — I1-I7
**Suggestions:** 6 — S1-S6

The architecture is sound and follows existing patterns well. The outbox pipeline, discovery, routing, and daemon integration are all correctly structured. The critical issues are about error visibility and status correctness — both fixable with targeted changes.
