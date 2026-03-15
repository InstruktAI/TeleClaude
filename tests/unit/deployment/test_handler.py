"""Characterization tests for teleclaude.deployment.handler."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.deployment.executor as executor
import teleclaude.deployment.handler as handler
from teleclaude.hooks.webhook_models import HookEvent


def _project_config(channel: str, pinned_minor: str = "") -> SimpleNamespace:
    return SimpleNamespace(deployment=SimpleNamespace(channel=channel, pinned_minor=pinned_minor))


async def test_handle_deployment_event_alpha_push_publishes_fanout_and_executes_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_fanout = AsyncMock()
    execute_update = AsyncMock()
    created_tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def capture_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(handler, "_get_redis", AsyncMock(return_value=object()))
    monkeypatch.setattr(handler, "_publish_fanout", publish_fanout)
    monkeypatch.setattr(handler, "resolve_project_config_path", lambda _root: _root / "teleclaude.yml")
    monkeypatch.setattr("teleclaude.config.loader.load_project_config", lambda _path: _project_config("alpha"))
    monkeypatch.setattr(executor, "execute_update", execute_update)
    monkeypatch.setattr(handler.asyncio, "create_task", capture_task)

    event = HookEvent.now(source="github", type="push", properties={"ref": "refs/heads/main"})
    await handler.handle_deployment_event(event)
    await asyncio.gather(*created_tasks)

    publish_fanout.assert_awaited_once()
    execute_update.assert_awaited_once()
    assert execute_update.await_args.args[0] == "alpha"
    assert execute_update.await_args.args[1]["channel"] == "alpha"


async def test_handle_deployment_event_skips_stable_release_outside_pinned_minor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_fanout = AsyncMock()
    execute_update = AsyncMock()
    create_task_called = False

    def fail_if_task_created(_coro):
        nonlocal create_task_called
        create_task_called = True
        raise AssertionError("update should not be scheduled")

    monkeypatch.setattr(handler, "_get_redis", AsyncMock(return_value=object()))
    monkeypatch.setattr(handler, "_publish_fanout", publish_fanout)
    monkeypatch.setattr(handler, "resolve_project_config_path", lambda _root: _root / "teleclaude.yml")
    monkeypatch.setattr("teleclaude.config.loader.load_project_config", lambda _path: _project_config("stable", "1.2"))
    monkeypatch.setattr(executor, "execute_update", execute_update)
    monkeypatch.setattr(handler.asyncio, "create_task", fail_if_task_created)

    event = HookEvent.now(
        source="github",
        type="release",
        properties={"action": "published"},
        payload={"release": {"tag_name": "v2.0.0"}},
    )
    await handler.handle_deployment_event(event)

    assert create_task_called is False
    publish_fanout.assert_not_awaited()
    execute_update.assert_not_awaited()


async def test_handle_deployment_event_from_fanout_executes_locally_without_republishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_fanout = AsyncMock()
    execute_update = AsyncMock()
    created_tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def capture_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(handler, "_get_redis", AsyncMock(return_value=object()))
    monkeypatch.setattr(handler, "_publish_fanout", publish_fanout)
    monkeypatch.setattr(handler, "resolve_project_config_path", lambda _root: _root / "teleclaude.yml")
    monkeypatch.setattr("teleclaude.config.loader.load_project_config", lambda _path: _project_config("stable", "1.2"))
    monkeypatch.setattr(executor, "execute_update", execute_update)
    monkeypatch.setattr(handler.asyncio, "create_task", capture_task)

    event = HookEvent.now(
        source="deployment",
        type="version_available",
        properties={"channel": "stable", "version": "1.2.5", "from_version": "1.2.0"},
    )
    await handler.handle_deployment_event(event)
    await asyncio.gather(*created_tasks)

    publish_fanout.assert_not_awaited()
    execute_update.assert_awaited_once()
    assert execute_update.await_args.args[0] == "stable"
    assert execute_update.await_args.args[1]["version"] == "1.2.5"
