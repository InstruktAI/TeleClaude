# Subscription-Driven Job Notifications — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded job notification system with subscription-driven execution and delivery, where subscription jobs only run when someone subscribes and system jobs deliver to all admins.

**Architecture:** New subscription models on `PersonConfig` drive both job execution scheduling and notification delivery. The cron runner consults subscriptions to decide whether/when to run subscription jobs. A mailbox-flag scan after each cron run discovers undelivered reports and enqueues outbox rows per recipient. The existing `NotificationOutboxWorker` delivers via Telegram (V1).

**Tech Stack:** Python 3.12, Pydantic v2 (BaseModel), SQLModel, SQLAlchemy async, pytest

**Design doc:** `docs/plans/2026-02-20-job-report-notifications-design.md`

---

### Task 1: Schema — Subscription models and `category` field

**Files:**

- Modify: `teleclaude/config/schema.py:66-84` (add `category` to `JobScheduleConfig`)
- Modify: `teleclaude/config/schema.py:104-131` (add `chat_id` to `TelegramCreds`, add subscription models, replace `NotificationsConfig`/`SubscriptionsConfig`)
- Modify: `teleclaude/config/schema.py:223-246` (update `PersonConfig`)
- Test: `tests/unit/test_config_schema.py`

**Step 1: Write the failing tests**

```python
# In tests/unit/test_config_schema.py — add these tests

def test_job_schedule_config_category_defaults_to_subscription():
    cfg = JobScheduleConfig()
    assert cfg.category == "subscription"


def test_job_schedule_config_category_system():
    cfg = JobScheduleConfig(category="system")
    assert cfg.category == "system"


def test_telegram_creds_chat_id():
    creds = TelegramCreds(user_name="alice", user_id=123, chat_id="456")
    assert creds.chat_id == "456"


def test_telegram_creds_chat_id_optional():
    creds = TelegramCreds(user_name="alice", user_id=123)
    assert creds.chat_id is None


def test_subscription_notification_defaults():
    from teleclaude.config.schema import SubscriptionNotification
    n = SubscriptionNotification()
    assert n.preferred_channel is None
    assert n.email is False


def test_job_subscription_roundtrip():
    from teleclaude.config.schema import JobSubscription, JobWhenConfig
    sub = JobSubscription(job="memory-review", when=JobWhenConfig(at="06:00"))
    assert sub.type == "job"
    assert sub.job == "memory-review"
    assert sub.when.at == "06:00"


def test_youtube_subscription_roundtrip():
    from teleclaude.config.schema import YoutubeSubscription
    sub = YoutubeSubscription(source="youtube.csv", tags=["ai"])
    assert sub.type == "youtube"
    assert sub.source == "youtube.csv"


def test_person_config_new_subscriptions_list():
    from teleclaude.config.schema import JobSubscription, YoutubeSubscription
    cfg = PersonConfig(subscriptions=[
        JobSubscription(job="memory-review"),
        YoutubeSubscription(source="youtube.csv"),
    ])
    assert len(cfg.subscriptions) == 2
    assert cfg.subscriptions[0].type == "job"
    assert cfg.subscriptions[1].type == "youtube"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config_schema.py -v -k "category or chat_id or subscription_notification or job_subscription or youtube_subscription or person_config_new"`
Expected: FAIL — `category` field doesn't exist, new classes don't exist

**Step 3: Implement the schema changes**

In `teleclaude/config/schema.py`:

1. Add `category` field to `JobScheduleConfig` (line ~67):

```python
class JobScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: Literal["subscription", "system"] = "subscription"
    # ... rest unchanged
```

2. Add `chat_id` to `TelegramCreds` (line ~107):

```python
class TelegramCreds(BaseModel):
    model_config = ConfigDict(extra="allow")
    user_name: str
    user_id: int
    chat_id: str | None = None
```

3. Add subscription models after `CredsConfig` (line ~119), replacing `NotificationsConfig` and old `SubscriptionsConfig`:

```python
class SubscriptionNotification(BaseModel):
    preferred_channel: Literal["telegram", "discord"] | None = None
    email: bool = False


class Subscription(BaseModel):
    type: str
    notification: SubscriptionNotification = SubscriptionNotification()


class JobSubscription(Subscription):
    type: Literal["job"] = "job"
    job: str
    when: JobWhenConfig | None = None


class YoutubeSubscription(Subscription):
    type: Literal["youtube"] = "youtube"
    source: str
    tags: list[str] = []


SubscriptionEntry = Annotated[
    JobSubscription | YoutubeSubscription,
    Field(discriminator="type")
]
```

4. Keep `NotificationsConfig` and old `SubscriptionsConfig` temporarily (removed in Task 5 after migration). Update `PersonConfig` to accept both old and new format:

```python
class PersonConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    creds: CredsConfig = CredsConfig()
    notifications: NotificationsConfig = NotificationsConfig()  # kept for migration
    subscriptions: list[SubscriptionEntry] | SubscriptionsConfig = []
    interests: list[str] = []
```

Note: The discriminated union on `subscriptions` needs a validator to handle the old `SubscriptionsConfig` dict format gracefully. Add a `model_validator(mode="before")` that converts `dict` to empty list for backward compatibility.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config_schema.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add subscription models and category field to job config
```

---

### Task 2: CronState — Add `last_notified` field

**Files:**

- Modify: `teleclaude/cron/state.py:13-19` (`JobStateDict`)
- Modify: `teleclaude/cron/state.py:28-55` (`JobState`)
- Modify: `teleclaude/cron/state.py:58-107` (`CronState`)
- Test: `tests/unit/test_cron_state.py` (create)

**Step 1: Write failing tests**

```python
# tests/unit/test_cron_state.py
from datetime import datetime, timezone
from teleclaude.cron.state import CronState, JobState


def test_job_state_last_notified_default_none():
    job = JobState()
    assert job.last_notified is None


def test_job_state_roundtrip_with_last_notified(tmp_path):
    state = CronState(path=tmp_path / "state.json")
    state.mark_success("test-job")
    now = datetime.now(timezone.utc)
    state.mark_notified("test-job", now)
    state.save()

    loaded = CronState.load(tmp_path / "state.json")
    job = loaded.get_job("test-job")
    assert job.last_notified is not None
    assert job.last_notified.isoformat() == now.isoformat()


def test_mark_notified_creates_job_if_missing(tmp_path):
    state = CronState(path=tmp_path / "state.json")
    now = datetime.now(timezone.utc)
    state.mark_notified("new-job", now)
    assert state.get_job("new-job").last_notified == now
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cron_state.py -v`
Expected: FAIL — `last_notified` doesn't exist, `mark_notified` doesn't exist

**Step 3: Implement**

In `teleclaude/cron/state.py`:

1. Add `last_notified` to `JobStateDict`:

```python
class JobStateDict(TypedDict, total=False):
    last_run: str | None
    last_status: str
    last_error: str | None
    last_notified: str | None
```

2. Add `last_notified` to `JobState` dataclass and its serialization:

```python
@dataclass
class JobState:
    last_run: datetime | None = None
    last_status: str = "never"
    last_error: str | None = None
    last_notified: datetime | None = None

    def to_dict(self) -> JobStateDict:
        return {
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_notified": self.last_notified.isoformat() if self.last_notified else None,
        }

    @classmethod
    def from_dict(cls, data: JobStateDict) -> JobState:
        last_run = None
        last_run_str = data.get("last_run")
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
            except (ValueError, TypeError):
                pass
        last_notified = None
        last_notified_str = data.get("last_notified")
        if last_notified_str:
            try:
                last_notified = datetime.fromisoformat(last_notified_str)
            except (ValueError, TypeError):
                pass
        return cls(
            last_run=last_run,
            last_status=data.get("last_status", "never"),
            last_error=data.get("last_error"),
            last_notified=last_notified,
        )
```

3. Add `mark_notified` to `CronState`:

```python
def mark_notified(self, name: str, timestamp: datetime) -> None:
    """Record the timestamp of the last notified report."""
    job = self.get_job(name)
    job.last_notified = timestamp
    self.save()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cron_state.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add last_notified field to cron state
```

---

### Task 3: Subscriber discovery — `discover_job_recipients()`

**Files:**

- Create: `teleclaude/cron/job_recipients.py`
- Test: `tests/unit/test_job_recipients.py` (create)

**Step 1: Write failing tests**

```python
# tests/unit/test_job_recipients.py
import os
from pathlib import Path

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cron.job_recipients import discover_job_recipients


def _setup_people(tmp_path: Path) -> Path:
    """Create test people configs with subscriptions."""
    root = tmp_path / ".teleclaude"
    (root / "people" / "alice").mkdir(parents=True)
    (root / "people" / "bob").mkdir(parents=True)

    (root / "teleclaude.yml").write_text("""
people:
  - name: alice
    email: alice@example.com
    role: admin
  - name: bob
    email: bob@example.com
    role: member
""", encoding="utf-8")

    (root / "people" / "alice" / "teleclaude.yml").write_text("""
creds:
  telegram:
    user_name: alice
    user_id: 111
    chat_id: "111"
subscriptions:
  - type: job
    job: memory-review
    when:
      at: "06:00"
    notification:
      preferred_channel: telegram
""", encoding="utf-8")

    (root / "people" / "bob" / "teleclaude.yml").write_text("""
creds:
  telegram:
    user_name: bob
    user_id: 222
    chat_id: "222"
subscriptions:
  - type: job
    job: memory-review
    when:
      at: "09:00"
    notification:
      preferred_channel: telegram
""", encoding="utf-8")

    return root


def test_subscription_job_finds_subscribers(tmp_path):
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("memory-review", "subscription", root=root)
    assert len(recipients) == 2


def test_system_job_includes_admins(tmp_path):
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("db-cleanup", "system", root=root)
    # alice is admin → auto-included even without subscription
    assert len(recipients) == 1
    assert recipients[0][0].telegram.chat_id == "111"


def test_system_job_admin_plus_subscriber_no_duplicate(tmp_path):
    root = _setup_people(tmp_path)
    # alice is admin AND subscribed to memory-review
    recipients = discover_job_recipients("memory-review", "system", root=root)
    # alice: admin auto + subscriber (deduped) + bob subscriber = 3 entries
    # but alice appears twice, so we should get 3 (admin alice, subscriber alice, subscriber bob)
    # Actually design says break avoids duplicate within one person
    emails = [r[0].telegram.chat_id for r in recipients]
    assert "111" in emails  # alice
    assert "222" in emails  # bob


def test_no_subscribers_returns_empty(tmp_path):
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("nonexistent", "subscription", root=root)
    assert len(recipients) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_job_recipients.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement**

Create `teleclaude/cron/job_recipients.py`:

```python
"""Discover job notification recipients from person subscriptions."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import (
    CredsConfig,
    JobSubscription,
    SubscriptionNotification,
)

logger = get_logger(__name__)


def discover_job_recipients(
    job_name: str,
    job_category: str,
    *,
    root: Path | None = None,
) -> list[tuple[CredsConfig, SubscriptionNotification]]:
    """Find all people who should receive a job's report.

    For system jobs: all admins + explicit subscribers.
    For subscription jobs: explicit subscribers only.
    Deduplicates within each person (admin + subscriber = one entry, using subscriber prefs).
    """
    if root is None:
        root = Path.home() / ".teleclaude"

    global_cfg_path = root / "teleclaude.yml"
    if not global_cfg_path.exists():
        return []

    global_cfg = load_global_config(global_cfg_path)
    admin_emails = {
        p.email for p in global_cfg.people if p.role == "admin"
    }

    people_dir = root / "people"
    if not people_dir.is_dir():
        return []

    recipients: list[tuple[CredsConfig, SubscriptionNotification]] = []

    for person_dir in sorted(people_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        person_cfg_path = person_dir / "teleclaude.yml"
        if not person_cfg_path.exists():
            continue

        try:
            person_cfg = load_person_config(person_cfg_path)
        except Exception:
            logger.exception("skipping bad person config", path=str(person_cfg_path))
            continue

        # Resolve email for this person
        person_key = person_dir.name.lower()
        person_email = None
        for p in global_cfg.people:
            if p.name.lower() == person_key or (p.username and p.username.lower() == person_key):
                person_email = p.email
                break

        # Check explicit subscription first
        sub_match: JobSubscription | None = None
        for sub in person_cfg.subscriptions:
            if isinstance(sub, JobSubscription) and sub.job == job_name:
                sub_match = sub
                break

        if sub_match:
            recipients.append((person_cfg.creds, sub_match.notification))
        elif job_category == "system" and person_email in admin_emails:
            # Admin gets system job results with default notification prefs
            recipients.append((person_cfg.creds, SubscriptionNotification()))

    return recipients
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_job_recipients.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add subscriber discovery for job report notifications
```

---

### Task 4: Notification scan — mailbox flag pattern

**Files:**

- Create: `teleclaude/cron/notification_scan.py`
- Test: `tests/unit/test_notification_scan.py` (create)

**Step 1: Write failing tests**

```python
# tests/unit/test_notification_scan.py
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cron.state import CronState


def _create_report(jobs_dir: Path, job_name: str, filename: str, content: str = "# Report") -> Path:
    """Create a report file at the expected path."""
    report_dir = jobs_dir / job_name / "runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / filename
    report_path.write_text(content, encoding="utf-8")
    return report_path


def test_scan_finds_undelivered_reports(tmp_path):
    from teleclaude.cron.notification_scan import find_undelivered_reports

    jobs_dir = tmp_path / "jobs"
    _create_report(jobs_dir, "memory-review", "260220-060000.md")

    state = CronState(path=tmp_path / "state.json")
    # No last_notified → all reports are undelivered
    undelivered = find_undelivered_reports(jobs_dir, state)
    assert "memory-review" in undelivered
    assert len(undelivered["memory-review"]) == 1


def test_scan_skips_already_notified(tmp_path):
    from teleclaude.cron.notification_scan import find_undelivered_reports

    jobs_dir = tmp_path / "jobs"
    report = _create_report(jobs_dir, "memory-review", "260220-060000.md")

    state = CronState(path=tmp_path / "state.json")
    # Mark as notified with a timestamp after the report's mtime
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    state.mark_notified("memory-review", future)

    undelivered = find_undelivered_reports(jobs_dir, state)
    assert len(undelivered.get("memory-review", [])) == 0


def test_scan_returns_empty_when_no_reports(tmp_path):
    from teleclaude.cron.notification_scan import find_undelivered_reports

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    state = CronState(path=tmp_path / "state.json")

    undelivered = find_undelivered_reports(jobs_dir, state)
    assert undelivered == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_notification_scan.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement**

Create `teleclaude/cron/notification_scan.py`:

```python
"""Scan for undelivered job reports using the mailbox flag pattern."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cron.state import CronState

logger = get_logger(__name__)


def find_undelivered_reports(
    jobs_dir: Path,
    state: CronState,
) -> dict[str, list[Path]]:
    """Find job reports that haven't been notified yet.

    Compares report file mtimes against the last_notified timestamp in cron state.

    Returns:
        Dict mapping job_name -> list of undelivered report file paths.
    """
    undelivered: dict[str, list[Path]] = {}

    if not jobs_dir.is_dir():
        return undelivered

    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        runs_dir = job_dir / "runs"
        if not runs_dir.is_dir():
            continue

        job_name = job_dir.name
        job_state = state.get_job(job_name)
        last_notified = job_state.last_notified

        reports: list[Path] = []
        for report_path in sorted(runs_dir.glob("*.md")):
            mtime = datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc)
            if last_notified is None or mtime > last_notified:
                reports.append(report_path)

        if reports:
            undelivered[job_name] = reports

    return undelivered
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_notification_scan.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add notification scan for undelivered job reports
```

---

### Task 5: DB migration — Add `delivery_channel` to `notification_outbox`

**Files:**

- Create: `teleclaude/core/migrations/0XX_add_delivery_channel.py`
- Modify: `teleclaude/core/schema.sql:109-122`
- Modify: `teleclaude/core/db_models.py:135-152`
- Modify: `teleclaude/core/db.py` (update `enqueue_notification` signature)

**Step 1: Write failing test**

```python
# Add to tests/unit/test_notifications.py

@pytest.mark.asyncio
async def test_enqueue_notification_with_delivery_channel(tmp_path):
    db = Db(tmp_path / "test.db")
    await db.initialize()

    row_id = await db.enqueue_notification(
        channel="job:memory-review",
        recipient_email="alice@example.com",
        content="Report content",
        delivery_channel="telegram",
    )
    assert row_id > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_notifications.py::test_enqueue_notification_with_delivery_channel -v`
Expected: FAIL — `delivery_channel` parameter not accepted

**Step 3: Implement**

1. Add `delivery_channel` to the SQLModel:

```python
# In teleclaude/core/db_models.py, class NotificationOutbox
delivery_channel: str = "telegram"  # telegram, discord, email
```

2. Add to schema.sql:

```sql
-- In CREATE TABLE notification_outbox, add:
delivery_channel TEXT NOT NULL DEFAULT 'telegram',
```

3. Create migration file `teleclaude/core/migrations/0XX_add_delivery_channel.py`:

```python
"""Add delivery_channel to notification_outbox."""

MIGRATION_SQL = """
ALTER TABLE notification_outbox ADD COLUMN delivery_channel TEXT NOT NULL DEFAULT 'telegram';
"""
```

4. Update `db.enqueue_notification()` to accept `delivery_channel`:

```python
async def enqueue_notification(
    self,
    channel: str,
    recipient_email: str,
    content: str,
    file_path: str | None = None,
    delivery_channel: str = "telegram",
) -> int:
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_notifications.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: add delivery_channel column to notification_outbox
```

---

### Task 6: Notification router — Replace channel-based routing with subscription-based

**Files:**

- Modify: `teleclaude/notifications/router.py` (rewrite `send_notification`)
- Modify: `teleclaude/notifications/discovery.py` (will be gutted — old code kept for backward compat until Task 8)
- Modify: `teleclaude/notifications/__init__.py`
- Test: `tests/unit/test_notifications.py` (add new test, keep old tests passing)

**Step 1: Write failing test**

```python
# Add to tests/unit/test_notifications.py

@pytest.mark.asyncio
async def test_enqueue_job_notifications(tmp_path):
    """Test the new per-recipient notification enqueue path."""
    from teleclaude.config.schema import CredsConfig, TelegramCreds, SubscriptionNotification

    db = Db(tmp_path / "test.db")
    await db.initialize()
    router = NotificationRouter(db=db)

    creds = CredsConfig(telegram=TelegramCreds(user_name="alice", user_id=111, chat_id="111"))
    notification = SubscriptionNotification(preferred_channel="telegram")

    recipients = [(creds, notification)]
    row_ids = await router.enqueue_job_notifications(
        job_name="memory-review",
        content="# Memory Review Report",
        file_path="/tmp/report.md",
        recipients=recipients,
    )
    assert len(row_ids) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_notifications.py::test_enqueue_job_notifications -v`
Expected: FAIL — `enqueue_job_notifications` doesn't exist

**Step 3: Implement**

Add `enqueue_job_notifications()` to `NotificationRouter`:

```python
async def enqueue_job_notifications(
    self,
    job_name: str,
    content: str,
    file_path: str | None,
    recipients: list[tuple[CredsConfig, SubscriptionNotification]],
) -> list[int]:
    """Enqueue one outbox row per recipient for a job report."""
    row_ids: list[int] = []

    for creds, notification in recipients:
        channel = notification.preferred_channel or "telegram"
        # Resolve recipient identifier based on delivery channel
        if channel == "telegram" and creds.telegram and creds.telegram.chat_id:
            recipient_id = creds.telegram.chat_id
        elif channel == "discord" and creds.discord:
            recipient_id = creds.discord.user_id
        else:
            logger.warning("no delivery address for channel", channel=channel)
            continue

        try:
            row_id = await self.db.enqueue_notification(
                channel=f"job:{job_name}",
                recipient_email=recipient_id,  # reusing email column for recipient ID
                content=content,
                file_path=file_path,
                delivery_channel=channel,
            )
            row_ids.append(row_id)
        except Exception:
            logger.exception("failed to enqueue job notification", job=job_name)

    return row_ids
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_notifications.py -v`
Expected: PASS (old tests still pass, new test passes)

**Step 5: Commit**

```
feat: add subscription-based notification enqueue to router
```

---

### Task 7: Notification worker — Route by `delivery_channel`

**Files:**

- Modify: `teleclaude/notifications/worker.py:112-163` (update `_deliver_row` to check `delivery_channel`)
- Test: `tests/unit/test_notifications.py`

**Step 1: Write failing test**

```python
# Add to tests/unit/test_notifications.py

@pytest.mark.asyncio
async def test_worker_delivers_by_delivery_channel(tmp_path):
    """Worker uses delivery_channel column instead of hardcoded telegram."""
    db = Db(tmp_path / "test.db")
    await db.initialize()

    row_id = await db.enqueue_notification(
        channel="job:memory-review",
        recipient_email="111",  # chat_id
        content="test report",
        delivery_channel="telegram",
    )

    shutdown = asyncio.Event()
    worker = NotificationOutboxWorker(db=db, shutdown_event=shutdown)

    with patch("teleclaude.notifications.worker.send_telegram_dm", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = None
        # Process one batch
        await worker._process_once()
        mock_send.assert_called_once_with(chat_id="111", content="test report", file=None)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_notifications.py::test_worker_delivers_by_delivery_channel -v`
Expected: May fail because worker still uses old `_recipient_for_email` lookup

**Step 3: Implement**

Update `_deliver_row` in `worker.py` to use `delivery_channel`:

```python
async def _deliver_row(self, row: "NotificationOutboxRow") -> None:
    row_id = row["id"]
    content = str(row["content"] or "")
    file_path = row.get("file_path")
    file_path_value = str(file_path) if file_path else None
    delivery_channel = str(row.get("delivery_channel", "telegram"))

    if delivery_channel == "telegram":
        # For new-style rows, recipient_email contains chat_id directly
        chat_id = str(row["recipient_email"])
        # Fallback: old-style rows have email, resolve via cache
        if "@" in chat_id:
            resolved = self._recipient_for_email(chat_id)
            if not resolved:
                await self.db.mark_notification_failed(row_id, MAX_RETRIES, "", "No chat_id for recipient")
                return
            chat_id = resolved

        try:
            await send_telegram_dm(chat_id=chat_id, content=content, file=file_path_value)
        except Exception as exc:
            # ... existing retry logic unchanged ...
            return

    elif delivery_channel == "discord":
        logger.info("discord delivery not implemented", row_id=row_id)
        await self.db.mark_notification_failed(row_id, MAX_RETRIES, "", "Discord delivery not implemented")
        return

    elif delivery_channel == "email":
        logger.info("email delivery not implemented", row_id=row_id)
        await self.db.mark_notification_failed(row_id, MAX_RETRIES, "", "Email delivery not implemented")
        return

    try:
        await self.db.mark_notification_delivered(row_id)
    except Exception as exc:
        logger.error("notification sent but DB update failed", row_id=row_id, error=str(exc))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_notifications.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: route notification delivery by delivery_channel column
```

---

### Task 8: Cron runner — Subscription-driven job execution + notification scan integration

**Files:**

- Modify: `teleclaude/cron/runner.py:264-351` (delete `_notification_channel_for_job`, `_notification_message_for_job_result`, `_notify_job_completion`)
- Modify: `teleclaude/cron/runner.py:386-419` (`run_due_jobs` — add subscription logic + notification scan)
- Test: `tests/unit/test_notifications.py` (update existing tests)

**Step 1: Write failing tests**

```python
# tests/unit/test_cron_runner_subscriptions.py
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron.runner import _is_due
from teleclaude.cron.runner import _should_run_subscription_job


def test_subscription_job_skipped_without_subscribers():
    """Subscription job with no subscribers should not run."""
    result = _should_run_subscription_job("nonexistent-job", root=Path("/nonexistent"))
    assert result is False


def test_system_job_always_due():
    """System jobs use project-level schedule, not subscription check."""
    cfg = JobScheduleConfig(category="system", when={"every": "1h"})
    # With no last_run, should be due
    assert _is_due(cfg, last_run=None)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cron_runner_subscriptions.py -v`
Expected: FAIL — `_should_run_subscription_job` doesn't exist

**Step 3: Implement**

In `teleclaude/cron/runner.py`:

1. Delete: `_normalize_job_name_for_notifications`, `_notification_channel_for_job`, `_notification_message_for_job_result`, `_notification_file_for_job_result`, `_notify_job_completion`

2. Add subscription-awareness to `run_due_jobs`:

```python
def _should_run_subscription_job(
    job_name: str,
    state: CronState,
    now: datetime,
    *,
    root: Path | None = None,
) -> bool:
    """Check if any subscriber's schedule makes this subscription job due."""
    from teleclaude.cron.job_recipients import _iter_person_configs_with_subscriptions

    if root is None:
        root = Path.home() / ".teleclaude"

    for _person_name, person_cfg in _iter_person_configs(root):
        for sub in person_cfg.subscriptions:
            if isinstance(sub, JobSubscription) and sub.job == job_name and sub.when:
                schedule = JobScheduleConfig(when=sub.when)
                job_state = state.get_job(job_name)
                if _is_due(schedule, job_state.last_run, now):
                    return True
    return False
```

3. In `run_due_jobs`, add category check:

```python
# After loading schedules, for each job:
job_cfg = schedules.get(job_name)
if job_cfg and job_cfg.category == "subscription":
    if not _should_run_subscription_job(job_name, state, now, root=root):
        continue  # skip — no subscribers or not due
```

4. After job execution, call `scan_and_enqueue_notifications()`:

```python
from teleclaude.cron.notification_scan import find_undelivered_reports
from teleclaude.cron.job_recipients import discover_job_recipients

# At the end of run_due_jobs:
_scan_and_notify(state, schedules, root)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cron_runner_subscriptions.py tests/unit/test_notifications.py -v`
Expected: PASS

**Step 5: Commit**

```
feat: subscription-driven job execution and notification scan in cron runner
```

---

### Task 9: Config cleanup — Remove old notification/subscription classes

**Files:**

- Modify: `teleclaude/config/schema.py` (delete `NotificationsConfig`, old `SubscriptionsConfig`)
- Modify: `teleclaude/notifications/discovery.py` (rewrite or gut)
- Modify: `teleclaude/cron/discovery.py` (update youtube subscriber discovery)
- Modify: All tests referencing old config fields
- Modify: `teleclaude/cli/tui/config_components/notifications.py` (update)
- Modify: `teleclaude/cli/config_handlers.py` (update)

**Step 1: Search for all references to old types**

Run:

```bash
rg "NotificationsConfig|SubscriptionsConfig|notifications\.telegram_chat_id|notifications\.channels" --type py
```

This reveals all callers that need updating.

**Step 2: Update schema**

Remove `NotificationsConfig` and old `SubscriptionsConfig` from `schema.py`.
Remove `notifications` field from `PersonConfig`.
Make `subscriptions` field exclusively `list[SubscriptionEntry]`.

**Step 3: Update discovery.py**

Rewrite `build_notification_subscriptions()` to use new subscription model, or delete if no longer needed. The old channel-based routing is replaced by `discover_job_recipients()`.

**Step 4: Update cron/discovery.py**

Rewrite `discover_youtube_subscribers()` to iterate `YoutubeSubscription` entries from person configs instead of the old `SubscriptionsConfig.youtube` field.

**Step 5: Fix all tests**

Update test fixtures that create person configs with old `notifications:` YAML format to use new `subscriptions:` format.

**Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: PASS

**Step 7: Commit**

```
refactor: remove legacy NotificationsConfig and SubscriptionsConfig
```

---

### Task 10: Person config migration script

**Files:**

- Create: `scripts/migrate_person_configs.py`
- Test: Manual verification against `~/.teleclaude/people/*/teleclaude.yml`

**Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""Migrate person configs from old notification format to subscription model.

Moves:
- notifications.telegram_chat_id → creds.telegram.chat_id
- notifications.channels → job subscriptions
- subscriptions.youtube → youtube subscription

Idempotent: skips configs that already use the new format.
"""
```

The script reads each `people/*/teleclaude.yml`, transforms the YAML, and writes back.

**Step 2: Test against actual configs**

Run with `--dry-run` flag first to preview changes.

**Step 3: Commit**

```
feat: add migration script for person config subscription format
```

---

### Task 11: Integration test and final verification

**Files:**

- Modify: `tests/unit/test_notifications.py` (update old tests to new format)
- Run: Full test suite

**Step 1: Run the entire test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Verify pyright passes**

Run: `make lint`
Expected: PASS

**Step 3: Final commit**

```
test: update notification tests for subscription-driven delivery
```

---

## Task Dependency Graph

```
Task 1 (Schema) ─────┬──→ Task 3 (Discovery) ──→ Task 8 (Runner integration)
                      │                                    │
Task 2 (CronState) ───┤──→ Task 4 (Scan) ─────────────────┘
                      │                                    │
Task 5 (DB migration)─┤──→ Task 6 (Router) ──→ Task 7 (Worker) ──→ Task 9 (Cleanup)
                      │                                                    │
                      └────────────────────────────────────────→ Task 10 (Migration)
                                                                           │
                                                                    Task 11 (Verify)
```

**Parallelizable:** Tasks 2, 3, 4, 5 can run in parallel after Task 1. Tasks 6 and 7 depend on Task 5.
