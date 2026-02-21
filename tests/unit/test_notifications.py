"""Unit tests for role-based notification outbox and routing."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.core.db import Db
from teleclaude.cron import runner
from teleclaude.notifications import NotificationOutboxWorker
from teleclaude.notifications.discovery import build_notification_subscriptions
from teleclaude.notifications.router import NotificationRouter


def _people_root(tmp_path: Path) -> Path:
    """Create a deterministic ~/.teleclaude directory with people subscriptions."""
    root = tmp_path / ".teleclaude"
    (root / "people" / "alice").mkdir(parents=True)
    (root / "people" / "bob").mkdir(parents=True)

    (root / "teleclaude.yml").write_text(
        """
people:
  - name: alice
    email: alice@example.com
  - name: bob
    email: bob@example.com
""",
        encoding="utf-8",
    )

    (root / "people" / "alice" / "teleclaude.yml").write_text(
        """
notifications:
  telegram_chat_id: "111"
  channels:
    - idea-miner-reports
    - maintenance-alerts
""",
        encoding="utf-8",
    )
    (root / "people" / "bob" / "teleclaude.yml").write_text(
        """
notifications:
  telegram_chat_id: "222"
  channels:
    - maintenance-alerts
""",
        encoding="utf-8",
    )
    return root


@pytest.mark.asyncio
async def test_notification_outbox_lifecycle(tmp_path: Path) -> None:
    """Test enqueue, claim, fail, and deliver lifecycle for notification rows."""
    db = Db(str(tmp_path / "teleclaude.db"))
    await db.initialize()

    row_id = await db.enqueue_notification("idea-miner-reports", "alice@example.com", "hello")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lock_cutoff = (now - timedelta(seconds=1)).isoformat()

    rows = await db.fetch_notification_batch(now_iso, 10, lock_cutoff)
    assert len(rows) == 1
    assert rows[0]["id"] == row_id

    claimed = await db.claim_notification(row_id, now_iso, lock_cutoff)
    assert claimed is True

    next_attempt = (now + timedelta(seconds=30)).isoformat()
    await db.mark_notification_failed(row_id, 1, next_attempt, "boom")

    rows = await db.fetch_notification_batch(now_iso, 10, lock_cutoff)
    assert rows == []

    await db.mark_notification_delivered(row_id)

    rows = await db.fetch_notification_batch(now_iso, 10, lock_cutoff)
    assert rows == []

    await db.close()


@pytest.mark.asyncio
async def test_notification_outbox_batch_excludes_max_attempt_rows(tmp_path: Path) -> None:
    """Rows that reached max attempts should not be selected again."""
    db = Db(str(tmp_path / "teleclaude.db"))
    await db.initialize()

    row_id = await db.enqueue_notification("idea-miner-reports", "alice@example.com", "hello")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lock_cutoff = (now - timedelta(seconds=1)).isoformat()

    await db.mark_notification_failed(row_id, 10, "", "permanent failure")

    rows = await db.fetch_notification_batch(now_iso, 10, lock_cutoff, max_attempts=10)
    assert rows == []

    await db.close()


@pytest.mark.asyncio
async def test_notification_router_enqueues_only_matching_subscribers(tmp_path: Path) -> None:
    """Router writes outbox rows only for subscribers of the requested channel."""
    root = _people_root(tmp_path)
    db = AsyncMock()
    db.enqueue_notification = AsyncMock(side_effect=[123])

    router = NotificationRouter(db=db, root=root)
    rows = await router.send_notification("idea-miner-reports", "report is ready")

    assert rows == [123]
    db.enqueue_notification.assert_awaited_once_with(
        channel="idea-miner-reports",
        recipient_email="alice@example.com",
        content="report is ready",
        file_path=None,
    )

    db.enqueue_notification.reset_mock()
    rows = await router.send_notification("unknown", "no one should get this")
    assert rows == []
    db.enqueue_notification.assert_not_awaited()


@pytest.mark.unit
def test_notification_router_includes_only_subscriber_channel_membership(tmp_path: Path) -> None:
    """Bob should not receive idea-miner notifications when only maintenance channel is configured."""
    root = _people_root(tmp_path)
    people = build_notification_subscriptions(root)
    assert [recipient.email for recipient in people.for_channel("idea-miner-reports")] == ["alice@example.com"]
    assert {recipient.email for recipient in people.for_channel("maintenance-alerts")} == {
        "alice@example.com",
        "bob@example.com",
    }


@pytest.mark.asyncio
async def test_notification_worker_delivers_batch_with_isolated_failures(monkeypatch, tmp_path: Path) -> None:
    """A failure in one row should not prevent later rows from being processed."""
    root = _people_root(tmp_path)

    db = AsyncMock()
    db.fetch_notification_batch = AsyncMock(
        return_value=[
            {
                "id": 1,
                "channel": "idea-miner-reports",
                "recipient_email": "alice@example.com",
                "content": "all good",
                "file_path": None,
                "status": "pending",
                "attempt_count": 0,
            },
            {
                "id": 2,
                "channel": "idea-miner-reports",
                "recipient_email": "bob@example.com",
                "content": "this fails",
                "file_path": None,
                "status": "pending",
                "attempt_count": 0,
            },
        ]
    )
    db.claim_notification = AsyncMock(side_effect=[True, True])
    db.mark_notification_delivered = AsyncMock()
    db.mark_notification_failed = AsyncMock()

    async def fake_send_telegram_dm(chat_id: str, content: str, file: str | None = None) -> str:
        if content == "this fails":
            raise RuntimeError("downstream error")
        return "ok"

    monkeypatch.setattr(
        "teleclaude.notifications.worker.send_telegram_dm",
        AsyncMock(side_effect=fake_send_telegram_dm),
    )

    worker = NotificationOutboxWorker(
        db=db,
        shutdown_event=asyncio.Event(),
        batch_size=10,
        root=root,
    )
    await worker._process_once()

    db.mark_notification_delivered.assert_awaited_once_with(1)
    assert db.mark_notification_failed.await_count == 1
    failed_call = db.mark_notification_failed.await_args_list[0].args
    assert failed_call[0] == 2
    assert failed_call[1] == 1
    assert failed_call[3] == "downstream error"


@pytest.mark.unit
def test_notification_channel_mapping() -> None:
    """Known job names must map to their notification channels."""
    assert runner._notification_channel_for_job("idea-miner") == "idea-miner-reports"
    assert runner._notification_channel_for_job("github-maintenance-runner") == "maintenance-alerts"
    assert runner._notification_channel_for_job("unmapped-job") is None


@pytest.mark.unit
def test_run_due_jobs_dispatches_mapped_jobs(monkeypatch) -> None:
    """run_due_jobs should enqueue completion notifications for mapped job names."""

    class _State:
        def get_job(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(last_run=None)

        def mark_success(self, _name: str) -> None:
            return None

        def mark_failed(self, _name: str, _error: str) -> None:
            return None

    class _FakeStateHolder:
        @staticmethod
        def load() -> _State:
            return _State()

    class _PythonJob:
        def __init__(self, name: str, message: str, processed: int) -> None:
            self.name = name
            self._message = message
            self._processed = processed

        def run(self) -> SimpleNamespace:
            return SimpleNamespace(
                success=True,
                message=self._message,
                items_processed=self._processed,
                errors=None,
            )

    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda config_path=None: {
            "idea_miner": JobScheduleConfig(schedule="hourly"),
            "maintenance": JobScheduleConfig(type="agent", job="maintenance"),
            "ignored_job": JobScheduleConfig(schedule="hourly"),
        },
    )
    monkeypatch.setattr(
        runner,
        "discover_jobs",
        lambda: [
            _PythonJob("idea_miner", "reports generated", 12),
            _PythonJob("ignored_job", "noop", 0),
        ],
    )
    monkeypatch.setattr(runner, "_run_agent_job", lambda _name, _cfg: True)
    monkeypatch.setattr(runner, "CronState", _FakeStateHolder)

    notified: list[tuple[str, bool]] = []

    def fake_notify(
        job_name: str,
        *,
        success: bool,
        message: str,
        items_processed: int = 0,
        file_path: str | None = None,
    ) -> None:
        if runner._notification_channel_for_job(job_name):
            notified.append((job_name, success))

    monkeypatch.setattr(runner, "_notify_job_completion", fake_notify)

    results = runner.run_due_jobs()

    assert results == {
        "idea_miner": True,
        "maintenance": True,
        "ignored_job": True,
    }
    assert set(notified) == {("idea_miner", True), ("maintenance", True)}


@pytest.mark.asyncio
async def test_enqueue_job_notifications_creates_rows_with_delivery_channel(tmp_path: Path) -> None:
    """enqueue_job_notifications should create outbox rows with correct delivery_channel and recipient."""
    from teleclaude.config.schema import CredsConfig, SubscriptionNotification, TelegramCreds

    db = AsyncMock()
    db.enqueue_notification = AsyncMock(side_effect=[10, 11])

    router = NotificationRouter(db=db, root=tmp_path)

    recipients = [
        (
            CredsConfig(telegram=TelegramCreds(user_name="alice", user_id=1, chat_id="111")),
            SubscriptionNotification(preferred_channel="telegram"),
        ),
        (
            CredsConfig(telegram=TelegramCreds(user_name="bob", user_id=2, chat_id="222")),
            SubscriptionNotification(preferred_channel="telegram"),
        ),
    ]

    row_ids = await router.enqueue_job_notifications(
        job_name="idea-miner",
        content="New report ready",
        file_path="/reports/2026-02-20.md",
        recipients=recipients,
    )

    assert row_ids == [10, 11]
    assert db.enqueue_notification.await_count == 2

    calls = db.enqueue_notification.await_args_list
    assert calls[0].kwargs == {
        "channel": "idea-miner",
        "recipient_email": "111",
        "content": "New report ready",
        "file_path": "/reports/2026-02-20.md",
        "delivery_channel": "telegram",
    }
    assert calls[1].kwargs == {
        "channel": "idea-miner",
        "recipient_email": "222",
        "content": "New report ready",
        "file_path": "/reports/2026-02-20.md",
        "delivery_channel": "telegram",
    }


@pytest.mark.asyncio
async def test_enqueue_job_notifications_skips_recipient_without_address(tmp_path: Path) -> None:
    """Recipients with no resolvable address should be skipped."""
    from teleclaude.config.schema import CredsConfig, SubscriptionNotification

    db = AsyncMock()
    db.enqueue_notification = AsyncMock()

    router = NotificationRouter(db=db, root=tmp_path)

    # No telegram creds, no email — no address
    recipients = [
        (CredsConfig(), SubscriptionNotification()),
    ]

    row_ids = await router.enqueue_job_notifications(
        job_name="idea-miner",
        content="Report",
        file_path=None,
        recipients=recipients,
    )

    assert row_ids == []
    db.enqueue_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_delivers_via_telegram_with_chat_id_directly(monkeypatch, tmp_path: Path) -> None:
    """Worker should use recipient as chat_id directly when delivery_channel is telegram and no '@' in recipient."""
    db = AsyncMock()
    db.fetch_notification_batch = AsyncMock(
        return_value=[
            {
                "id": 42,
                "channel": "idea-miner",
                "recipient_email": "111",
                "content": "report ready",
                "file_path": None,
                "status": "pending",
                "attempt_count": 0,
                "delivery_channel": "telegram",
            },
        ]
    )
    db.claim_notification = AsyncMock(return_value=True)
    db.mark_notification_delivered = AsyncMock()
    db.mark_notification_failed = AsyncMock()

    send_mock = AsyncMock(return_value="ok")
    monkeypatch.setattr("teleclaude.notifications.worker.send_telegram_dm", send_mock)

    worker = NotificationOutboxWorker(
        db=db,
        shutdown_event=asyncio.Event(),
        batch_size=10,
        root=tmp_path,
    )
    await worker._process_once()

    send_mock.assert_awaited_once_with(chat_id="111", content="report ready", file=None)
    db.mark_notification_delivered.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_worker_marks_unsupported_channel_as_failed(tmp_path: Path) -> None:
    """Worker should mark rows with unsupported delivery_channel as permanently failed."""
    db = AsyncMock()
    db.fetch_notification_batch = AsyncMock(
        return_value=[
            {
                "id": 99,
                "channel": "idea-miner",
                "recipient_email": "user@example.com",
                "content": "test",
                "file_path": None,
                "status": "pending",
                "attempt_count": 0,
                "delivery_channel": "discord",
            },
        ]
    )
    db.claim_notification = AsyncMock(return_value=True)
    db.mark_notification_delivered = AsyncMock()
    db.mark_notification_failed = AsyncMock()

    worker = NotificationOutboxWorker(
        db=db,
        shutdown_event=asyncio.Event(),
        batch_size=10,
        root=tmp_path,
    )
    await worker._process_once()

    db.mark_notification_delivered.assert_not_awaited()
    db.mark_notification_failed.assert_awaited_once()
    fail_args = db.mark_notification_failed.await_args.args
    assert fail_args[0] == 99
    assert "not implemented" in fail_args[3]
