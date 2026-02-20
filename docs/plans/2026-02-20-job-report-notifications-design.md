# Job Report Notification Delivery — Design

## Problem

Job run reports exist as markdown files at known paths but are never delivered to
interested parties. The notification infrastructure exists (outbox, worker,
Telegram DM sender) but is hardwired to Telegram and uses a hardcoded job-to-channel
mapping. Person config mixes credentials with notification preferences. There is no
way for a person to subscribe to a specific job's output.

More fundamentally, the current architecture treats jobs as unconditional — they run
on a fixed schedule regardless of whether anyone wants the output. Most jobs should
only run because someone subscribed to them.

## Job Categories

Jobs fall into two categories:

| Category         | Runs because            | Schedule controlled by | Results go to                               |
| ---------------- | ----------------------- | ---------------------- | ------------------------------------------- |
| **Subscription** | Someone subscribed      | The subscriber         | Subscribers                                 |
| **System**       | Infrastructure needs it | Project config         | All admins (automatic) + opt-in subscribers |

**Subscription jobs** are capabilities the system offers. They only execute when at
least one person subscribes. The subscriber specifies when the job runs (schedule).
If nobody subscribes, the job does not run. Examples: `memory-review`,
`log-bug-hunter`, `youtube-sync`.

**System jobs** run unconditionally on their project-level schedule. Results are
automatically delivered to all people with `role: "admin"`. People can also
subscribe to system jobs to receive the output, but they cannot control the
schedule. Examples: database cleanup, health checks.

## Design

### 1. Job Definition

Job definitions stay at project level in `teleclaude.yml`. A new `category` field
distinguishes subscription from system jobs:

```yaml
# teleclaude.yml (project level)
jobs:
  memory-review:
    category: subscription # only runs if someone subscribes
    type: agent
    agent: claude
    thinking_mode: fast
    message: 'Run memory review'

  log-bug-hunter:
    category: subscription
    type: agent
    agent: claude
    message: 'Hunt for bugs in logs'

  db-cleanup:
    category: system # runs unconditionally, results → admins
    when:
      every: '1d'
    type: script
    script: jobs/db_cleanup.py
```

Subscription jobs have no schedule at the project level — the schedule comes from
the subscriber. System jobs keep their schedule at the project level.

**Schema change:**

```python
class JobScheduleConfig(BaseModel):
    category: Literal["subscription", "system"] = "subscription"
    # ... existing fields
```

### 2. Subscription Model

Subscriptions are first-class objects on `PersonConfig`. Each subscription connects
a person to a source and carries its own notification preferences.

**Models:**

```python
class SubscriptionNotification(BaseModel):
    preferred_channel: Literal["telegram", "discord"] | None = None
    email: bool = False

class Subscription(BaseModel):
    type: str
    notification: SubscriptionNotification = SubscriptionNotification()

class JobSubscription(Subscription):
    type: Literal["job"] = "job"
    job: str  # job name (must match a key in teleclaude.yml jobs)
    when: JobWhenConfig | None = None  # schedule (subscription jobs only)

class YoutubeSubscription(Subscription):
    type: Literal["youtube"] = "youtube"
    source: str  # csv path
    tags: list[str] = []

SubscriptionEntry = Annotated[
    JobSubscription | YoutubeSubscription,
    Field(discriminator="type")
]
```

**Person YAML:**

```yaml
creds:
  telegram:
    user_name: morriz
    user_id: 123456
    chat_id: '789' # moved from notifications.telegram_chat_id

subscriptions:
  # Subscription job — subscriber controls schedule
  - type: job
    job: memory-review
    when:
      at: '06:00'
    notification:
      preferred_channel: telegram
      email: true

  # Subscription job — different schedule
  - type: job
    job: log-bug-hunter
    when:
      every: '1d'
      at: '09:00'
    notification:
      preferred_channel: discord

  # System job — opt-in to results (no schedule control)
  - type: job
    job: db-cleanup
    notification:
      preferred_channel: telegram

  # Non-job subscription
  - type: youtube
    source: youtube.csv
    tags: [ai, devtools]
    notification:
      preferred_channel: telegram
```

**PersonConfig:**

```python
class PersonConfig(BaseModel):
    creds: CredsConfig = CredsConfig()
    subscriptions: list[SubscriptionEntry] = []
    interests: list[str] = []
```

### 3. Config Cleanup

| Field                                 | Action                                               |
| ------------------------------------- | ---------------------------------------------------- |
| `NotificationsConfig`                 | Deleted entirely                                     |
| `notifications.telegram_chat_id`      | Moves to `creds.telegram.chat_id`                    |
| `notifications.telegram: bool`        | Replaced by `preferred_channel` on each subscription |
| `notifications.channels: list[str]`   | Replaced by explicit subscriptions                   |
| `SubscriptionsConfig` (old key-value) | Replaced by `list[SubscriptionEntry]`                |
| `TelegramCreds`                       | Gains `chat_id: str \| None = None`                  |

### 4. Cron Runner Changes

The cron runner's job selection logic changes:

**Subscription jobs:**

1. Collect all `JobSubscription` entries across all person configs.
2. For each subscription job name that has at least one subscriber, check if
   any subscriber's `when` schedule is due.
3. Run the job if due. Mark which subscribers triggered it.

**System jobs:**

1. System jobs run on their project-level schedule (unchanged from today).
2. No subscriber check — they always run.

```python
def _collect_subscription_schedules(job_name: str) -> list[tuple[str, JobWhenConfig]]:
    """Collect all subscriber schedules for a subscription job.

    Returns (person_name, when_config) pairs.
    """
    for person_name, person_cfg in iter_person_configs():
        for sub in person_cfg.subscriptions:
            if isinstance(sub, JobSubscription) and sub.job == job_name and sub.when:
                yield (person_name, sub.when)
```

### 5. Notification Scan (Mailbox Flag Pattern)

Delivery is decoupled from job execution. A periodic scan discovers undelivered
reports and enqueues notifications.

**Mechanism:**

1. The cron runner already executes every 5 minutes via launchd.
2. After job execution, a `scan_undelivered_reports()` pass runs.
3. The scan globs `~/.teleclaude/jobs/*/runs/*.md`.
4. For each job, it compares report file timestamps against a `last_notified`
   marker in `cron_state.json`.
5. Reports newer than `last_notified` are undelivered.
6. For each undelivered report, discovery determines recipients:
   - **Subscription jobs**: all people with a matching `JobSubscription`.
   - **System jobs**: all admins (via `PersonEntry.role == "admin"`) plus
     anyone with a matching `JobSubscription`.
7. For each recipient, one notification outbox row is enqueued per delivery
   channel (preferred_channel + email if enabled).
8. The `last_notified` marker advances to the newest delivered report timestamp.

**State extension:**

```json
{
  "jobs": {
    "memory-review": {
      "last_run": "2026-02-20T11:19:17+00:00",
      "last_status": "success",
      "last_error": null,
      "last_notified": "2026-02-20T11:19:17+00:00"
    }
  }
}
```

**Properties:**

- Works for both script and agent jobs — the scan doesn't care who wrote the report.
- If delivery fails, the outbox handles retry with exponential backoff (existing).
- If the scan fails, `last_notified` doesn't advance — next run retries naturally.
- No sidecar files, no new state file — one timestamp field per job.

### 6. Subscriber Discovery (replaces hardcoded mapping)

`_notification_channel_for_job()` and its hardcoded mapping are deleted. Discovery
becomes:

```python
def discover_job_recipients(
    job_name: str, job_category: str
) -> list[tuple[PersonCreds, SubscriptionNotification]]:
    """Find all people who should receive a job's report."""
    recipients = []

    for person_name, person_cfg, person_entry in iter_people():
        # System jobs: all admins get results automatically
        if job_category == "system" and person_entry.role == "admin":
            # Use admin's default notification prefs (from creds or fallback)
            recipients.append((person_cfg.creds, SubscriptionNotification()))

        # Any job type: explicit subscribers get results
        for sub in person_cfg.subscriptions:
            if isinstance(sub, JobSubscription) and sub.job == job_name:
                recipients.append((person_cfg.creds, sub.notification))
                break  # avoid duplicate if admin also subscribed

    return recipients
```

The notification worker uses `creds` to resolve delivery addresses
(`creds.telegram.chat_id` or `creds.discord.user_id`) and
`notification.preferred_channel` to select the backend.

### 7. Notification Worker Routing

The existing `NotificationOutboxWorker` is extended to dispatch based on channel:

| `preferred_channel` | Backend              | Status                      |
| ------------------- | -------------------- | --------------------------- |
| `telegram`          | `send_telegram_dm()` | Exists                      |
| `discord`           | `send_discord_dm()`  | Extension point (not in V1) |
| `email`             | `send_email()`       | Extension point (not in V1) |

V1 implements Telegram delivery end-to-end. Discord and email are documented
extension points — the schema supports them, the worker has the routing branch,
but the actual senders are stubbed.

The `notification_outbox` table gains a `delivery_channel` column (replacing the
implicit Telegram assumption) so the worker knows which backend to use per row.

### 8. Report Convention

No changes to the existing convention:

```
~/.teleclaude/jobs/{job_name}/runs/{YYMMDD-HHMMSS}.md
```

Reports are self-contained markdown. The notification scan sends the report content
as the message body and attaches the `.md` file. The `agent-job-hygiene` procedure
already defines the report format.

## What Dies

- `NotificationsConfig` class
- `SubscriptionsConfig` class (old key-value model)
- `notifications.telegram_chat_id`, `notifications.telegram`, `notifications.channels`
- `_notification_channel_for_job()` hardcoded mapping
- `_notification_message_for_job_result()` (replaced by report content)
- `NotificationRecipient` dataclass (replaced by creds + subscription notification)
- `build_notification_subscriptions()` and `discover_notification_recipients_for_channel()`

## What Stays

- `notification_outbox` table (extended with `delivery_channel`)
- `NotificationOutboxWorker` (extended with channel routing)
- `send_telegram_dm()` (existing backend)
- `CronState` (extended with `last_notified`)
- Run report convention and `agent-job-hygiene` procedure

## Scope

**In scope (V1):**

- Job category distinction (subscription vs system) on `JobScheduleConfig`
- Subscription model + person config schema change
- Config cleanup (move `telegram_chat_id` to creds)
- Subscription-driven job execution in cron runner
- Notification scan (mailbox flag pattern)
- Subscriber + admin discovery for job reports
- Telegram delivery (already works)
- Migration of existing person configs

**Extension points (not V1):**

- Discord DM delivery backend
- Email delivery backend
- Delivery intervals / daily digest
- Channel subscriptions (Redis streams as subscription source)
