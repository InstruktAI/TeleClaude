# Implementation Plan: job-report-notifications

## Overview

Replace hardcoded job-to-channel notification mapping with a subscription-driven model. Subscriptions on `PersonConfig` drive both job execution and notification delivery. A mailbox-flag scan discovers undelivered reports and enqueues outbox rows per recipient. The existing `NotificationOutboxWorker` delivers via Telegram (V1).

**Design doc:** `docs/plans/2026-02-20-job-report-notifications-design.md`

**Tech Stack:** Python 3.12, Pydantic v2, SQLModel, SQLAlchemy async, pytest

## Phase 1: Schema and State (foundation)

### Task 1.1: Subscription models and `category` field

**File(s):** `teleclaude/config/schema.py`, `tests/unit/test_config_schema.py`

- [x] Add `category: Literal["subscription", "system"] = "subscription"` to `JobScheduleConfig`
- [x] Add `chat_id: str | None = None` to `TelegramCreds`
- [x] Add `SubscriptionNotification` model (`preferred_channel`, `email`)
- [x] Add `Subscription` base model with `type: str`, `enabled: bool = True`, `notification: SubscriptionNotification`
- [x] Add `JobSubscription(Subscription)` with `job: str`, `when: JobWhenConfig | None`
- [x] Add `YoutubeSubscription(Subscription)` with `source: str`, `tags: list[str]`
- [x] Add `SubscriptionEntry = Annotated[JobSubscription | YoutubeSubscription, Field(discriminator="type")]`
- [x] Update `PersonConfig.subscriptions` to accept `list[SubscriptionEntry]` (keep old format via validator for migration)
- [x] Write tests: category defaults, chat_id optional, subscription roundtrips, enabled toggle, person config with new subscriptions
- [x] Run `pytest tests/unit/test_config_schema.py -v` — PASS

### Task 1.2: CronState — `last_notified` field

**File(s):** `teleclaude/cron/state.py`, `tests/unit/test_cron_state.py` (create)

- [ ] Add `last_notified: str | None` to `JobStateDict`
- [ ] Add `last_notified: datetime | None = None` to `JobState` dataclass
- [ ] Update `JobState.to_dict()` and `JobState.from_dict()` to serialize/deserialize `last_notified`
- [ ] Add `CronState.mark_notified(name, timestamp)` method
- [ ] Write tests: default None, roundtrip with last_notified, mark_notified creates job if missing
- [ ] Run `pytest tests/unit/test_cron_state.py -v` — PASS

### Task 1.3: DB migration — `delivery_channel` column

**File(s):** `teleclaude/core/db_models.py`, `teleclaude/core/schema.sql`, `teleclaude/core/migrations/`, `teleclaude/core/db.py`

- [ ] Add `delivery_channel: str = "telegram"` to `NotificationOutbox` model
- [ ] Add `delivery_channel TEXT NOT NULL DEFAULT 'telegram'` to `CREATE TABLE notification_outbox` in schema.sql
- [ ] Create migration file `0XX_add_delivery_channel.py` with ALTER TABLE
- [ ] Update `db.enqueue_notification()` to accept `delivery_channel: str = "telegram"` parameter
- [ ] Write test: enqueue with delivery_channel, verify it persists
- [ ] Run `pytest tests/unit/test_notifications.py -v` — PASS

---

## Phase 2: Discovery and Scanning (business logic)

### Task 2.1: Subscriber discovery — `discover_job_recipients()`

**File(s):** `teleclaude/cron/job_recipients.py` (create), `tests/unit/test_job_recipients.py` (create)

- [ ] Create `discover_job_recipients(job_name, job_category, *, root) -> list[tuple[CredsConfig, SubscriptionNotification]]`
- [ ] Subscription jobs: find all people with matching `JobSubscription` where `enabled=True`
- [ ] System jobs: all admins auto-included + explicit enabled subscribers; dedup within person
- [ ] Disabled subscriptions (`enabled=False`) skipped entirely
- [ ] Write tests: subscription job finds subscribers, system job includes admins, admin+subscriber dedup, disabled subscription ignored, no subscribers returns empty
- [ ] Run `pytest tests/unit/test_job_recipients.py -v` — PASS

### Task 2.2: Notification scan — mailbox flag pattern

**File(s):** `teleclaude/cron/notification_scan.py` (create), `tests/unit/test_notification_scan.py` (create)

- [ ] Create `find_undelivered_reports(jobs_dir, state) -> dict[str, list[Path]]`
- [ ] Glob `jobs/*/runs/*.md`, compare mtime to `last_notified` in cron state
- [ ] Reports with mtime > last_notified (or no last_notified) are undelivered
- [ ] Write tests: finds undelivered, skips already notified, empty when no reports
- [ ] Run `pytest tests/unit/test_notification_scan.py -v` — PASS

---

## Phase 3: Notification Pipeline (routing and delivery)

### Task 3.1: Notification router — subscription-based enqueue

**File(s):** `teleclaude/notifications/router.py`, `tests/unit/test_notifications.py`

- [ ] Add `enqueue_job_notifications(job_name, content, file_path, recipients) -> list[int]` to `NotificationRouter`
- [ ] For each recipient: resolve delivery address from creds + preferred_channel, enqueue outbox row with `delivery_channel`
- [ ] Write test: enqueue creates rows with correct delivery_channel and recipient
- [ ] Run `pytest tests/unit/test_notifications.py -v` — PASS (old + new tests)

### Task 3.2: Notification worker — route by `delivery_channel`

**File(s):** `teleclaude/notifications/worker.py`, `tests/unit/test_notifications.py`

- [ ] Update `_deliver_row` to read `delivery_channel` from row
- [ ] Telegram path: if `recipient_email` contains `@`, resolve via old lookup; else treat as `chat_id` directly
- [ ] Discord/email paths: log + mark failed with "not implemented" message
- [ ] Write test: worker delivers via telegram when delivery_channel is "telegram"
- [ ] Run `pytest tests/unit/test_notifications.py -v` — PASS

---

## Phase 4: Integration (wiring it together)

### Task 4.1: Cron runner — subscription-driven execution + notification scan

**File(s):** `teleclaude/cron/runner.py`, `tests/unit/test_cron_runner_subscriptions.py` (create)

- [ ] Delete: `_notification_channel_for_job`, `_notification_message_for_job_result`, `_notify_job_completion` (and related helpers)
- [ ] Add `_should_run_subscription_job(job_name, state, now, *, root) -> bool`: iterates person configs for enabled `JobSubscription` entries with matching job name, checks if any subscriber's `when` schedule is due
- [ ] In `run_due_jobs`: for subscription jobs, call `_should_run_subscription_job`; skip if False
- [ ] After job execution loop: call `_scan_and_notify(state, schedules, root)` to find undelivered reports, discover recipients, enqueue notifications, advance `last_notified`
- [ ] Write tests: subscription job skipped without subscribers, subscription job skipped when all disabled, system job always due, notification scan integration
- [ ] Run `pytest tests/unit/test_cron_runner_subscriptions.py -v` — PASS

---

## Phase 5: Cleanup and Migration

### Task 5.1: Config cleanup — remove legacy types

**File(s):** `teleclaude/config/schema.py`, `teleclaude/notifications/discovery.py`, `teleclaude/cron/discovery.py`, affected tests

- [ ] Search all references: `rg "NotificationsConfig|SubscriptionsConfig|notifications\.telegram_chat_id" --type py`
- [ ] Delete `NotificationsConfig` and old `SubscriptionsConfig` from schema.py
- [ ] Remove `notifications` field from `PersonConfig`
- [ ] Make `subscriptions` field exclusively `list[SubscriptionEntry]`
- [ ] Update `discover_youtube_subscribers()` in `teleclaude/cron/discovery.py` to use new `YoutubeSubscription` entries
- [ ] Gut or delete `teleclaude/notifications/discovery.py` (replaced by `job_recipients.py`)
- [ ] Fix all tests referencing old config fields
- [ ] Run `pytest tests/ -v` — PASS

### Task 5.2: Person config migration script

**File(s):** `scripts/migrate_person_configs.py` (create)

- [ ] Read each `~/.teleclaude/people/*/teleclaude.yml`
- [ ] Move `notifications.telegram_chat_id` → `creds.telegram.chat_id`
- [ ] Convert `notifications.channels` → explicit `JobSubscription` entries
- [ ] Convert `subscriptions.youtube` → `YoutubeSubscription` entries
- [ ] All migrated subscriptions get `enabled: true` by default
- [ ] Remove old `notifications` block
- [ ] Idempotent: skip configs already in new format
- [ ] Support `--dry-run` flag for preview

---

## Phase 6: Validation

### Task 6.1: Full verification

- [ ] Run `pytest tests/ -v --tb=short` — all PASS
- [ ] Run `make lint` — PASS
- [ ] Verify no unchecked implementation tasks remain
- [ ] Confirm requirements are reflected in code changes

---

## Phase 7: Review Readiness

- [ ] Confirm all success criteria from requirements.md are satisfied
- [ ] Confirm all implementation tasks marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

---

## Task Dependency Graph

```
Task 1.1 (Schema) ──┬──→ Task 2.1 (Discovery) ──→ Task 4.1 (Runner integration)
                     │                                    │
Task 1.2 (CronState)┤──→ Task 2.2 (Scan) ───────────────┘
                     │                                    │
Task 1.3 (DB)───────┤──→ Task 3.1 (Router) ──→ Task 3.2 (Worker)
                     │                                           │
                     └────────────────────────────→ Task 5.1 (Cleanup) ──→ Task 5.2 (Migration)
                                                                                    │
                                                                             Task 6.1 (Verify)
```

**Parallelizable:** Tasks 1.1, 1.2, 1.3 can run in parallel. Tasks 2.1, 2.2, 3.1 can run in parallel after their Phase 1 dependency. Tasks 3.2 depends on 3.1.
