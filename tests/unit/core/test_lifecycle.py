"""Unit tests for daemon lifecycle startup ordering."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.lifecycle import DaemonLifecycle


@pytest.mark.asyncio
async def test_startup_binds_api_before_project_warm_and_adapter_start():
    """The API socket must come up before slower cache/adaptor startup work."""
    client = MagicMock()
    cache = MagicMock()
    shutdown_event = asyncio.Event()
    task_registry = MagicMock()
    init_voice_handler = MagicMock()
    api_server = MagicMock()
    api_server.start = AsyncMock()
    operations_service = MagicMock()
    operations_service.start = AsyncMock()

    order: list[str] = []

    async def warm_sessions() -> None:
        order.append("warm_sessions")

    async def warm_projects() -> None:
        order.append("warm_projects")

    async def start_api() -> None:
        order.append("api_start")

    async def start_client() -> None:
        order.append("client_start")

    async def start_inbound_queue() -> None:
        order.append("inbound_queue")

    api_server.start.side_effect = start_api
    client.start = AsyncMock(side_effect=start_client)
    client.reconcile_outstanding_final_outputs = AsyncMock(return_value=0)

    lifecycle = DaemonLifecycle(
        client=client,
        cache=cache,
        shutdown_event=shutdown_event,
        task_registry=task_registry,
        runtime_settings=None,
        log_background_task_exception=lambda _name: lambda _task: None,
        init_voice_handler=init_voice_handler,
        api_restart_max=5,
        api_restart_window_s=60.0,
        api_restart_backoff_s=1.0,
    )
    lifecycle._warm_local_sessions_cache = warm_sessions
    lifecycle._warm_local_projects_cache = warm_projects

    inbound_queue_manager = MagicMock()
    inbound_queue_manager.startup = AsyncMock(side_effect=start_inbound_queue)

    with (
        patch("teleclaude.core.lifecycle.db.initialize", AsyncMock()),
        patch("teleclaude.core.lifecycle.db.set_client"),
        patch("teleclaude.core.lifecycle.OperationsService", return_value=operations_service),
        patch("teleclaude.core.lifecycle.set_operations_service"),
        patch("teleclaude.core.lifecycle.APIServer", return_value=api_server),
        patch("teleclaude.core.inbound_queue.get_inbound_queue_manager", return_value=inbound_queue_manager),
        patch("teleclaude.core.lifecycle.get_command_service", return_value=MagicMock()),
        patch(
            "teleclaude.core.lifecycle.reconcile_outstanding_conversation_deliveries",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        await lifecycle.startup()

    assert order == ["warm_sessions", "api_start", "warm_projects", "client_start", "inbound_queue"]
    api_server.set_on_server_exit.assert_called_once_with(lifecycle.handle_api_server_exit)
    init_voice_handler.assert_called_once_with()


@pytest.mark.asyncio
async def test_startup_repairs_outstanding_final_output_after_adapter_start():
    client = MagicMock()
    client.start = AsyncMock()
    client.reconcile_outstanding_final_outputs = AsyncMock(return_value=1)
    cache = MagicMock()
    shutdown_event = asyncio.Event()
    task_registry = MagicMock()
    init_voice_handler = MagicMock()
    api_server = MagicMock()
    api_server.start = AsyncMock()
    operations_service = MagicMock()
    operations_service.start = AsyncMock()

    lifecycle = DaemonLifecycle(
        client=client,
        cache=cache,
        shutdown_event=shutdown_event,
        task_registry=task_registry,
        runtime_settings=None,
        log_background_task_exception=lambda _name: lambda _task: None,
        init_voice_handler=init_voice_handler,
        api_restart_max=5,
        api_restart_window_s=60.0,
        api_restart_backoff_s=1.0,
    )
    lifecycle._warm_local_sessions_cache = AsyncMock()
    lifecycle._warm_local_projects_cache = AsyncMock()

    inbound_queue_manager = MagicMock()
    inbound_queue_manager.startup = AsyncMock()

    with (
        patch("teleclaude.core.lifecycle.db.initialize", AsyncMock()),
        patch("teleclaude.core.lifecycle.db.set_client"),
        patch("teleclaude.core.lifecycle.OperationsService", return_value=operations_service),
        patch("teleclaude.core.lifecycle.set_operations_service"),
        patch("teleclaude.core.lifecycle.APIServer", return_value=api_server),
        patch("teleclaude.core.inbound_queue.get_inbound_queue_manager", return_value=inbound_queue_manager),
        patch("teleclaude.core.lifecycle.get_command_service", return_value=MagicMock()),
        patch(
            "teleclaude.core.lifecycle.reconcile_outstanding_conversation_deliveries",
            new_callable=AsyncMock,
            return_value=0,
        ) as reconcile_conversations,
    ):
        await lifecycle.startup()

    client.reconcile_outstanding_final_outputs.assert_awaited_once()
    reconcile_conversations.assert_awaited_once()
    reconcile_args = reconcile_conversations.await_args
    assert reconcile_args is not None
    assert reconcile_args.args[0] == "unknown"
    assert reconcile_args.kwargs["client"] is client
    assert reconcile_args.kwargs["command_service"] is not None
