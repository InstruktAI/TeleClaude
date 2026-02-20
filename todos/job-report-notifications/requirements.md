# Requirements: job-report-notifications

## Goal

Replace the hardcoded job notification system with subscription-driven execution and delivery. Subscription jobs only run when someone subscribes (subscriber controls schedule). System jobs run unconditionally and deliver results to all admins. People can toggle subscriptions on/off without deleting them.

**Design doc:** `docs/plans/2026-02-20-job-report-notifications-design.md`

## Scope

### In scope:

- `category: Literal["subscription", "system"]` field on `JobScheduleConfig`
- New subscription models: `Subscription` (base with `enabled` toggle), `JobSubscription`, `YoutubeSubscription`, `SubscriptionNotification`
- Discriminated union `SubscriptionEntry` on `PersonConfig.subscriptions`
- Move `telegram_chat_id` from `NotificationsConfig` to `TelegramCreds.chat_id`
- `enabled: bool = True` toggle on `Subscription` base — disabled subscriptions are ignored by execution and delivery
- `last_notified` field on `CronState.JobState` for mailbox flag pattern
- `discover_job_recipients()` — subscription + admin discovery for notifications
- Mailbox flag scan (`find_undelivered_reports`) comparing report mtimes to `last_notified`
- `delivery_channel` column on `notification_outbox` table + DB migration
- `enqueue_job_notifications()` on `NotificationRouter` for per-recipient enqueue
- Worker routing by `delivery_channel` (Telegram V1, Discord/email as stubs)
- Subscription-driven job execution in cron runner: subscription jobs skip when no enabled subscribers
- Delete legacy: `NotificationsConfig`, old `SubscriptionsConfig`, `_notification_channel_for_job()`, `_notification_message_for_job_result()`
- Person config migration script (old format → new subscriptions list)
- Tests for all new behavior

### Out of scope:

- Discord DM delivery backend (stub only)
- Email delivery backend (stub only)
- Delivery intervals / daily digest
- Channel subscriptions (Redis streams as subscription source)
- TUI changes for subscription management
- API endpoints for managing subscriptions

## Success Criteria

- [ ] `JobScheduleConfig.category` defaults to `"subscription"`, accepts `"system"`
- [ ] `Subscription` base model has `enabled: bool = True` toggle
- [ ] Subscription jobs with no enabled subscribers do not execute
- [ ] Subscription jobs run when at least one enabled subscriber's `when` schedule is due
- [ ] System jobs run on project-level schedule regardless of subscribers
- [ ] System job results auto-delivered to all admins (`PersonEntry.role == "admin"`)
- [ ] Opt-in system job subscribers receive results via their preferred channel
- [ ] Disabled subscriptions (`enabled: false`) are ignored by both execution and delivery
- [ ] `last_notified` in cron state tracks delivery progress per job
- [ ] Undelivered reports detected by comparing mtime > `last_notified`
- [ ] `notification_outbox.delivery_channel` routes delivery to correct backend
- [ ] Legacy `NotificationsConfig` and old `SubscriptionsConfig` removed
- [ ] Migration script converts existing person configs to new format
- [ ] Full test suite passes (`make test`)
- [ ] Lint passes (`make lint`)

## Key Files

| File                                    | What changes                                                                                                        |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `teleclaude/config/schema.py`           | Add `category` to `JobScheduleConfig`, `chat_id` to `TelegramCreds`, new subscription models, update `PersonConfig` |
| `teleclaude/cron/state.py`              | Add `last_notified` to `JobState`/`JobStateDict`, add `mark_notified()` to `CronState`                              |
| `teleclaude/cron/job_recipients.py`     | **New** — `discover_job_recipients()`                                                                               |
| `teleclaude/cron/notification_scan.py`  | **New** — `find_undelivered_reports()`                                                                              |
| `teleclaude/cron/runner.py`             | Delete hardcoded notification functions, add `_should_run_subscription_job()`, integrate notification scan          |
| `teleclaude/core/db_models.py`          | Add `delivery_channel` to `NotificationOutbox`                                                                      |
| `teleclaude/core/schema.sql`            | Add `delivery_channel` column to `notification_outbox`                                                              |
| `teleclaude/notifications/router.py`    | Add `enqueue_job_notifications()`                                                                                   |
| `teleclaude/notifications/worker.py`    | Route delivery by `delivery_channel` column                                                                         |
| `teleclaude/notifications/discovery.py` | Gut or delete (replaced by `job_recipients.py`)                                                                     |
| `scripts/migrate_person_configs.py`     | **New** — migration script                                                                                          |

## Constraints

- Default behavior must not break — `category` defaults to `"subscription"`, `enabled` defaults to `True`
- Backward-compatible during migration: old person config format accepted via validator
- V1 delivers via Telegram only; Discord/email are documented stubs
- `notification_outbox` migration must be additive (new column with default)

## Risks

- Person config migration touches all people YAML files — needs dry-run mode and backup
- Subscription-driven execution changes job scheduling semantics — needs careful test coverage of edge cases (no subscribers, all disabled, mixed schedules)
- `last_notified` timestamp comparison with file mtime requires consistent timezone handling (UTC)
