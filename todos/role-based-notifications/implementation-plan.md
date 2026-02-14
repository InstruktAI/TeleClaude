# Implementation Plan: Role-Based Notifications

## Objective

Build notification routing with outbox persistence and delivery worker, following the existing hook outbox pattern.

## [x] Task 1: Notification outbox table

**Files:**

- `teleclaude/core/db_models.py` — add `NotificationOutbox` SQLModel.
- New migration in `teleclaude/core/migrations/`.

Schema follows hook outbox pattern:

```sql
CREATE TABLE notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    content TEXT NOT NULL,
    file_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    locked_at TEXT
);
CREATE INDEX idx_notification_outbox_status ON notification_outbox(status);
CREATE INDEX idx_notification_outbox_next_attempt ON notification_outbox(next_attempt_at);
```

**Verification:** Migration applies cleanly.

## [x] Task 2: Outbox DB methods

**File:** `teleclaude/core/db.py`

- `enqueue_notification(channel, recipient_email, content, file_path=None)` — INSERT pending row.
- `claim_notification(row_id, now_iso, lock_cutoff_iso) -> bool` — lock for delivery.
- `mark_notification_delivered(row_id)` — set status=delivered, delivered_at.
- `mark_notification_failed(row_id, error, attempt_count, next_attempt_at)` — set error, schedule retry.
- `fetch_notification_batch(limit, now_iso) -> list` — SELECT pending rows due for delivery.

Follows existing `claim_hook_outbox` / `mark_hook_outbox_delivered` / `mark_hook_outbox_failed` pattern.

**Verification:** Unit tests for all outbox operations.

## [x] Task 3: Notification router

**File:** `teleclaude/notifications/router.py` (new)

- `NotificationRouter` class.
- `send_notification(channel, content, file=None)` — resolve subscribers, enqueue one outbox row per subscriber.
- Uses discovery to find subscribers for the channel.

**Verification:** Unit test — router enqueues correct rows for subscribed users.

## [x] Task 4: Delivery worker

**File:** `teleclaude/notifications/worker.py` (new)

- Background async loop (registered in daemon startup).
- Fetches pending outbox batch.
- Claims and delivers each row.
- Retry with exponential backoff on failure.
- Per-row failure isolation.

**Verification:** Integration test — worker delivers pending rows, retries failures.

## [x] Task 5: Telegram DM sender

**File:** `teleclaude/notifications/telegram.py` (new)

- `send_telegram_dm(chat_id, content, file=None)` — generalized from existing personal script.
- Uses existing Telegram bot API credentials.

**Verification:** Test with mock API call.

## [x] Task 6: Per-person config extension

**File:** `teleclaude/config/schema.py`

- Extend `PersonConfig.notifications` with `channels: list[str]` and `telegram_chat_id: str`.

**Verification:** Config parsing test.

## [x] Task 7: Discovery extension

**File:** `teleclaude/notifications/discovery.py` (new)

- Scan per-person configs for `notifications.channels`.
- Build `channel -> list[subscriber]` mapping.
- Subscriber includes email and delivery config (telegram_chat_id).

**Verification:** Discovery finds correct subscribers per channel.

## [x] Task 8: Job integration

Wire first consumers:

- Idea miner job → `idea-miner-reports` channel.
- Maintenance job → `maintenance-alerts` channel.

**Verification:** Job completion triggers outbox entry, worker delivers.

## [x] Task 9: Tests

**File:** `tests/unit/test_notifications.py`

- Outbox CRUD operations.
- Router enqueues for subscribed users only.
- Unsubscribed users get nothing.
- Worker processes batch with retry.
- Delivery failure isolation.
- Config parsing with notification channels.

## Files Changed

| File                                    | Change                       |
| --------------------------------------- | ---------------------------- |
| `teleclaude/core/db_models.py`          | Add NotificationOutbox model |
| `teleclaude/core/migrations/`           | New migration                |
| `teleclaude/core/db.py`                 | Add outbox methods           |
| `teleclaude/notifications/__init__.py`  | New package                  |
| `teleclaude/notifications/router.py`    | New — notification router    |
| `teleclaude/notifications/worker.py`    | New — delivery worker        |
| `teleclaude/notifications/telegram.py`  | New — Telegram DM sender     |
| `teleclaude/notifications/discovery.py` | New — subscriber discovery   |
| `teleclaude/config/schema.py`           | Extend PersonConfig          |
| `tests/unit/test_notifications.py`      | New tests                    |

## Risks

1. Telegram bot rate limits — worker should respect per-chat rate limits.
2. Outbox growth — need cleanup of old delivered rows (age-based DELETE, not v1 critical).

## Verification

- All tests pass.
- Outbox persists notifications across daemon restarts.
- Worker delivers and retries correctly.
- Unsubscribed users receive nothing.
