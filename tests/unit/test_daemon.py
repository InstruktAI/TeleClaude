"""Characterization tests for teleclaude.daemon."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import teleclaude.daemon as daemon
from teleclaude.core.todos_db import TodosDb, _instances, get_todos_db, set_todos_mutation_hook

_EVENT_NAME = "domain.software-development.planning.todo_finalize_ready"
_SLUG = "phase-hook-slug"
_PRIOR_PHASE = "review_approved"
_FINALIZE_READY = "finalize_ready"
_BUILD_PHASE = "build"
_SHA = "abc123"
_WORKER_SESSION_ID = "sess-123"
_READY_AT = "2026-05-20T00:00:00+00:00"
_PROJECT_PATH = "/repo/project"
_OLD_SLUG = "old-slug"
_NEW_SLUG = "new-slug"


async def _get_hooked_todos_db(tmp_path: Path) -> TodosDb:
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance._loop = asyncio.get_running_loop()
    daemon_instance.cache = SimpleNamespace(refresh_local_todos=AsyncMock())
    daemon_instance._register_todos_mutation_hook()
    return await get_todos_db(tmp_path)


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
def test_dispatch_workflow_todo_renamed_invalidates_and_broadcasts_typed_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance.cache = MagicMock()
    api_server = SimpleNamespace(_broadcast_payload=MagicMock())
    daemon_instance.lifecycle = SimpleNamespace(api_server=api_server)
    monkeypatch.setattr(daemon.config, "computer", SimpleNamespace(name="fallback-computer"))
    envelope = daemon.WorkflowEnvelope(
        channel="workflow.todo.renamed",
        idempotency_key="rename-key",
        emitted_at="2026-05-21T10:00:00Z",
        principal=None,
        payload={
            "old_slug": _OLD_SLUG,
            "new_slug": _NEW_SLUG,
            "project_path": _PROJECT_PATH,
        },
    )

    daemon_instance._dispatch_workflow_event(envelope)

    daemon_instance.cache.publish_workflow_change.assert_called_once_with(
        "todos",
        computer="fallback-computer",
        project_path=_PROJECT_PATH,
    )
    api_server._broadcast_payload.assert_called_once_with(
        "todo_renamed",
        {
            "event": "todo_renamed",
            "data": {
                "old_slug": _OLD_SLUG,
                "new_slug": _NEW_SLUG,
                "project_path": _PROJECT_PATH,
            },
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_awaits_webhook_delivery_task_gracefully() -> None:
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance._stop_sandbox_manager = AsyncMock()
    daemon_instance._cancel_task_attr = AsyncMock()
    daemon_instance._await_task_attr = AsyncMock()
    daemon_instance._stop_session_outbox_workers = AsyncMock()
    daemon_instance._event_pipeline = None
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
    daemon_instance._signal_ai_client.close.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_todos_phase_transition_hook_emits_finalize_ready_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / ".teleclaude" / "todos.db")
    _instances.pop(db_path, None)
    emit_event = AsyncMock()
    monkeypatch.setattr(daemon, "emit_event", emit_event, raising=False)

    todos_db = None
    try:
        todos_db = await _get_hooked_todos_db(tmp_path)
        todos_db.notify_phase_transition(
            _SLUG,
            _PRIOR_PHASE,
            _FINALIZE_READY,
            {
                "finalize": {
                    "branch": _SLUG,
                    "sha": _SHA,
                    "worker_session_id": _WORKER_SESSION_ID,
                    "ready_at": _READY_AT,
                },
            },
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        emit_event.assert_awaited_once()
        kwargs = emit_event.await_args.kwargs
        assert kwargs["event"] == _EVENT_NAME
        assert kwargs["entity"] == _SLUG
        assert kwargs["payload"] == {
            "slug": _SLUG,
            "branch": _SLUG,
            "sha": _SHA,
            "worker_session_id": _WORKER_SESSION_ID,
            "ready_at": _READY_AT,
        }
    finally:
        set_todos_mutation_hook(None)
        _instances.pop(db_path, None)
        if todos_db is not None:
            await todos_db.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_todos_phase_transition_hook_ignores_non_finalize_ready_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / ".teleclaude" / "todos.db")
    _instances.pop(db_path, None)
    emit_event = AsyncMock()
    monkeypatch.setattr(daemon, "emit_event", emit_event, raising=False)

    todos_db = None
    try:
        todos_db = await _get_hooked_todos_db(tmp_path)
        todos_db.notify_phase_transition(_SLUG, _PRIOR_PHASE, _BUILD_PHASE, {})
        await asyncio.sleep(0)

        emit_event.assert_not_awaited()
    finally:
        set_todos_mutation_hook(None)
        _instances.pop(db_path, None)
        if todos_db is not None:
            await todos_db.close()
