"""Characterization tests for teleclaude.daemon."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import teleclaude.daemon as daemon


class NetworkError(Exception):
    """Synthetic exception with a retryable type name."""


def _make_lock_only_daemon(pid_file):
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance.pid_file = pid_file
    daemon_instance.pid_file_handle = None
    return daemon_instance


def test_is_retryable_startup_error_recognizes_type_name_and_message() -> None:
    assert daemon._is_retryable_startup_error(NetworkError("dns failed")) is True
    assert daemon._is_retryable_startup_error(RuntimeError("Temporary failure in name resolution")) is True
    assert daemon._is_retryable_startup_error(ValueError("bad credentials")) is False


def test_acquire_and_release_lock_writes_pid_and_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registered: list[object] = []
    daemon_instance = _make_lock_only_daemon(tmp_path / "teleclaude.pid")
    monkeypatch.setattr(daemon.atexit, "register", registered.append)

    daemon_instance._acquire_lock()

    assert daemon_instance.pid_file.read_text(encoding="utf-8") == str(os.getpid())
    assert daemon_instance.pid_file_handle is not None
    assert registered == [daemon_instance._release_lock]

    daemon_instance._release_lock()

    assert daemon_instance.pid_file_handle is None
    assert not daemon_instance.pid_file.exists()


def test_acquire_lock_raises_when_another_handle_already_holds_it(tmp_path: Path) -> None:
    pid_file = tmp_path / "teleclaude.pid"
    first = _make_lock_only_daemon(pid_file)
    second = _make_lock_only_daemon(pid_file)
    first._acquire_lock()

    try:
        with pytest.raises(daemon.DaemonLockError, match="already running"):
            second._acquire_lock()
    finally:
        first._release_lock()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_awaits_webhook_delivery_task_gracefully() -> None:
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance._stop_sandbox_manager = AsyncMock()
    daemon_instance._cancel_task_attr = AsyncMock()
    daemon_instance._await_task_attr = AsyncMock()
    daemon_instance._stop_session_outbox_workers = AsyncMock()
    daemon_instance._event_pipeline = SimpleNamespace(shutdown=AsyncMock())
    daemon_instance._signal_ai_client = SimpleNamespace(close=AsyncMock())
    daemon_instance._release_lock = MagicMock()
    daemon_instance.lifecycle = SimpleNamespace(shutdown=AsyncMock())
    daemon_instance.task_registry = SimpleNamespace(shutdown=AsyncMock())
    daemon_instance._event_db = None
    daemon_instance.webhook_delivery_task = asyncio.create_task(asyncio.sleep(0), name="webhook-delivery")

    daemon_instance.cleanup_task = None
    daemon_instance.poller_watch_task = None
    daemon_instance.hook_outbox_task = None
    daemon_instance.mirror_worker_task = None
    daemon_instance.channel_subscription_worker_task = None
    daemon_instance.resource_monitor_task = None
    daemon_instance._wal_checkpoint_task = None
    daemon_instance.launchd_watch_task = None
    daemon_instance._deployment_fanout_task = None
    daemon_instance._contract_sweep_task = None
    daemon_instance._ingest_scheduler_task = None
    daemon_instance._event_processor_task = None

    await daemon_instance.stop()

    daemon_instance._await_task_attr.assert_any_await(
        "webhook_delivery_task",
        "Webhook delivery worker stopped",
        timeout=5.0,
    )
    daemon_instance._await_task_attr.assert_any_await(
        "channel_subscription_worker_task",
        "Channel subscription worker stopped",
        timeout=5.0,
    )
    daemon_instance._await_task_attr.assert_any_await(
        "_deployment_fanout_task",
        "Deployment fanout stopped",
        timeout=5.0,
    )
    daemon_instance._await_task_attr.assert_any_await(
        "_ingest_scheduler_task",
        "IngestScheduler stopped",
        timeout=5.0,
    )
    daemon_instance._await_task_attr.assert_any_await(
        "_event_processor_task",
        "EventProcessor stopped",
        timeout=5.0,
    )
    daemon_instance._event_pipeline.shutdown.assert_awaited_once_with(timeout=5.0)
    daemon_instance._signal_ai_client.close.assert_awaited_once_with()
