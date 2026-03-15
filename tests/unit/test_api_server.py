"""Characterization tests for teleclaude.api_server public boundaries."""

from __future__ import annotations

import sys
import types
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, WebSocket
from fastapi.testclient import TestClient

from teleclaude.api.auth import CallerIdentity
from teleclaude.core.cache import DaemonCache
from teleclaude.core.models import TodoInfo

_ROUTE_MODULE_NAMES = (
    "teleclaude.api.agents_routes",
    "teleclaude.api.chiptunes_routes",
    "teleclaude.api.computers_routes",
    "teleclaude.api.jobs_routes",
    "teleclaude.api.notifications_routes",
    "teleclaude.api.people_routes",
    "teleclaude.api.projects_routes",
    "teleclaude.api.sessions_actions_routes",
    "teleclaude.api.sessions_routes",
    "teleclaude.api.settings_routes",
    "teleclaude.memory.api_routes",
    "teleclaude.mirrors.api_routes",
    "teleclaude.hooks.api_routes",
    "teleclaude.channels.api_routes",
    "teleclaude.api.streaming",
    "teleclaude.api.data_routes",
    "teleclaude.api.operations_routes",
    "teleclaude.api.todo_routes",
    "teleclaude.api.event_routes",
)


def _make_route_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(router=APIRouter(), configure=MagicMock())


@contextmanager
def _api_server_harness(
    tmp_path: Path,
    *,
    cache: object | None = None,
) -> Generator[tuple[object, dict[str, types.SimpleNamespace]], None, None]:
    fake_modules = {name: _make_route_module() for name in _ROUTE_MODULE_NAMES}
    with (
        patch.dict(sys.modules, fake_modules),
        patch("teleclaude.api_server.event_bus.subscribe"),
    ):
        from teleclaude.api_server import APIServer

        server = APIServer(
            client=MagicMock(adapters={}),
            cache=cache,
            socket_path=str(tmp_path / "api.sock"),
        )
        yield server, fake_modules


class TestApiServerHttpRoutes:
    """Pins public HTTP and websocket route behavior."""

    @pytest.mark.unit
    def test_health_endpoint_returns_ok_status(self, tmp_path):
        with _api_server_harness(tmp_path, cache=None) as (server, _):
            client = TestClient(server.app)
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.unit
    def test_auth_whoami_returns_token_principal_when_present(self, tmp_path):
        with _api_server_harness(tmp_path, cache=None) as (server, _):
            from teleclaude.api_server import verify_caller

            server.app.dependency_overrides[verify_caller] = lambda: CallerIdentity(
                session_id="sess-001",
                system_role=None,
                human_role="member",
                tmux_session_name=None,
                principal="system:sess-001",
                principal_role="admin",
            )
            client = TestClient(server.app)
            response = client.get("/auth/whoami")

        assert response.status_code == 200
        assert response.json() == {"principal": "system:sess-001", "role": "admin"}

    @pytest.mark.unit
    def test_auth_whoami_returns_human_role_when_principal_absent(self, tmp_path):
        with _api_server_harness(tmp_path, cache=None) as (server, _):
            from teleclaude.api_server import verify_caller

            server.app.dependency_overrides[verify_caller] = lambda: CallerIdentity(
                session_id="",
                system_role=None,
                human_role="member",
                tmux_session_name=None,
                principal=None,
                principal_role=None,
            )
            client = TestClient(server.app)
            response = client.get("/auth/whoami")

        assert response.status_code == 200
        assert response.json() == {"principal": None, "role": "member"}

    @pytest.mark.unit
    def test_todos_endpoint_maps_cached_todos_to_response_dtos(self, tmp_path):
        cache = DaemonCache()
        cache.set_todos(
            "local",
            "/srv/project",
            [
                TodoInfo(
                    slug="todo-1",
                    status="pending",
                    has_requirements=True,
                    has_impl_plan=False,
                )
            ],
        )

        with _api_server_harness(tmp_path, cache=cache) as (server, _):
            client = TestClient(server.app)
            response = client.get("/todos", params={"computer": "local", "project": "/srv/project"})

        assert response.status_code == 200
        assert response.json() == [
            {
                "slug": "todo-1",
                "status": "pending",
                "description": None,
                "computer": "local",
                "project_path": "/srv/project",
                "has_requirements": True,
                "has_impl_plan": False,
                "build_status": None,
                "review_status": None,
                "dor_score": None,
                "deferrals_status": None,
                "findings_count": 0,
                "files": [],
                "after": [],
                "group": None,
                "delivered_at": None,
                "prepare_phase": None,
                "integration_phase": None,
                "finalize_status": None,
            }
        ]

    @pytest.mark.unit
    def test_todos_endpoint_falls_back_to_local_command_handler_without_cache(self, tmp_path):
        raw_todos = [TodoInfo(slug="todo-2", status="active", has_requirements=False, has_impl_plan=True)]

        with (
            _api_server_harness(tmp_path, cache=None) as (server, _),
            patch("teleclaude.api_server.command_handlers.list_todos", AsyncMock(return_value=raw_todos)) as list_todos,
        ):
            client = TestClient(server.app)
            response = client.get("/todos", params={"project": "/srv/project"})

        assert response.status_code == 200
        assert response.json()[0]["slug"] == "todo-2"
        list_todos.assert_awaited_once_with("/srv/project")

    @pytest.mark.unit
    def test_websocket_route_delegates_to_handle_websocket(self, tmp_path):
        seen: list[str] = []

        with _api_server_harness(tmp_path, cache=None) as (server, _):

            async def fake_handle_websocket(websocket: WebSocket) -> None:
                seen.append("called")
                await websocket.accept()
                await websocket.send_json({"event": "connected"})
                await websocket.close()

            server._handle_websocket = fake_handle_websocket
            client = TestClient(server.app)
            with client.websocket_connect("/ws") as websocket:
                payload = websocket.receive_json()

        assert seen == ["called"]
        assert payload == {"event": "connected"}


class TestApiServerLifecycle:
    """Pins APIServer public lifecycle methods and cache property behavior."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_sets_running_and_invokes_server_startup_steps(self, tmp_path):
        with _api_server_harness(tmp_path, cache=None) as (server, _):

            async def fake_start_server() -> None:
                assert server._running is True

            with (
                patch.object(server, "_start_server", AsyncMock(side_effect=fake_start_server)) as start_server,
                patch.object(server, "_start_metrics_task") as start_metrics,
                patch.object(server, "_start_watch_task") as start_watch,
            ):
                await server.start()

        assert server._running is True
        start_server.assert_awaited_once()
        start_metrics.assert_called_once_with()
        start_watch.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_unsubscribes_cache_closes_websockets_and_stops_servers(self, tmp_path):
        cache = MagicMock()

        with _api_server_harness(tmp_path, cache=cache) as (server, _):
            websocket = MagicMock()
            websocket.close = AsyncMock()
            server._ws_clients.add(websocket)
            server._client_subscriptions[websocket] = {"local": {"sessions"}}

            async def fake_stop_metrics_task() -> None:
                assert server._running is False

            with (
                patch.object(
                    server, "_stop_metrics_task", AsyncMock(side_effect=fake_stop_metrics_task)
                ) as stop_metrics,
                patch.object(server, "_stop_watch_task", AsyncMock()) as stop_watch,
                patch.object(server, "_stop_server", AsyncMock()) as stop_server,
                patch.object(server, "_cleanup_socket") as cleanup_socket,
            ):
                await server.stop()

        stop_metrics.assert_awaited_once()
        stop_watch.assert_awaited_once()
        stop_server.assert_awaited_once()
        cleanup_socket.assert_called_once_with("stop")
        cache.unsubscribe.assert_called_once_with(server._on_cache_change)
        websocket.close.assert_awaited_once()
        assert server._ws_clients == set()
        assert server._client_subscriptions == {}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restart_server_stops_then_starts_when_shutdown_finishes(self, tmp_path):
        with _api_server_harness(tmp_path, cache=None) as (server, _):
            server.server_task = None
            with (
                patch.object(server, "_stop_server", AsyncMock()) as stop_server,
                patch.object(server, "_start_server", AsyncMock()) as start_server,
            ):
                await server.restart_server()

        stop_server.assert_awaited_once()
        start_server.assert_awaited_once()

    @pytest.mark.unit
    def test_cache_property_rewires_route_modules_and_subscriptions(self, tmp_path):
        old_cache = MagicMock()
        new_cache = MagicMock()

        with _api_server_harness(tmp_path, cache=old_cache) as (server, fake_modules):
            old_cache.subscribe.assert_called_once_with(server._on_cache_change)

            server.cache = new_cache

        old_cache.unsubscribe.assert_called_once_with(server._on_cache_change)
        new_cache.subscribe.assert_called_once_with(server._on_cache_change)
        fake_modules["teleclaude.api.sessions_routes"].configure.assert_called_with(cache=new_cache)
        fake_modules["teleclaude.api.computers_routes"].configure.assert_called_with(cache=new_cache)
        fake_modules["teleclaude.api.projects_routes"].configure.assert_called_with(cache=new_cache)
