"""Characterization tests for teleclaude.transport.redis_transport._pull."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


@pytest.fixture
def transport_with_cache(transport: RedisTransport) -> RedisTransport:
    mock_cache = MagicMock()
    mock_cache.get_interested_computers.return_value = []
    mock_cache.get_computers.return_value = []
    transport._cache = mock_cache
    return transport


class TestPullInitialSessions:
    @pytest.mark.unit
    async def test_does_nothing_when_cache_unavailable(self, transport: RedisTransport) -> None:
        transport._cache = None
        # Must not raise
        await transport._pull_initial_sessions()

    @pytest.mark.unit
    async def test_does_nothing_when_no_interested_computers(self, transport_with_cache: RedisTransport) -> None:
        transport_with_cache._cache.get_interested_computers.return_value = []
        transport_with_cache.send_request = AsyncMock()
        await transport_with_cache._pull_initial_sessions()
        transport_with_cache.send_request.assert_not_called()

    @pytest.mark.unit
    async def test_skips_computer_not_in_heartbeat_cache(self, transport_with_cache: RedisTransport) -> None:
        cache = transport_with_cache._cache
        cache.get_interested_computers.return_value = ["unknown-computer"]
        cache.get_computers.return_value = []
        transport_with_cache.send_request = AsyncMock()
        await transport_with_cache._pull_initial_sessions()
        transport_with_cache.send_request.assert_not_called()

    @pytest.mark.unit
    async def test_populates_cache_with_remote_sessions(self, transport_with_cache: RedisTransport) -> None:
        cache = transport_with_cache._cache
        remote = MagicMock()
        remote.name = "remote-machine"
        cache.get_interested_computers.return_value = ["remote-machine"]
        cache.get_computers.return_value = [remote]

        session_data = {
            "session_id": "sess-1",
            "title": "Test Session",
            "status": "active",
            "last_input_origin": None,
            "thinking_mode": None,
            "active_agent": None,
        }
        response = json.dumps({"status": "success", "data": [session_data]})
        transport_with_cache.send_request = AsyncMock(return_value="msg-1")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache._pull_initial_sessions()
        cache.update_session.assert_called_once()


class TestPullInterestedSessions:
    @pytest.mark.unit
    async def test_delegates_to_pull_initial_sessions(self, transport: RedisTransport) -> None:
        transport._pull_initial_sessions = AsyncMock()
        await transport.pull_interested_sessions()
        transport._pull_initial_sessions.assert_called_once()


class TestPullRemoteProjects:
    @pytest.mark.unit
    async def test_does_nothing_when_cache_unavailable(self, transport: RedisTransport) -> None:
        transport._cache = None
        await transport.pull_remote_projects("some-computer")

    @pytest.mark.unit
    async def test_stores_projects_in_cache_on_success(self, transport_with_cache: RedisTransport) -> None:
        project_data = {"path": "/repo/project", "name": "myproject"}
        response = json.dumps({"status": "success", "data": [project_data]})
        transport_with_cache.send_request = AsyncMock(return_value="msg-id")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache.pull_remote_projects("remote-machine")
        transport_with_cache._cache.apply_projects_snapshot.assert_called_once()

    @pytest.mark.unit
    async def test_skips_on_error_response(self, transport_with_cache: RedisTransport) -> None:
        response = json.dumps({"status": "error", "error": "not found"})
        transport_with_cache.send_request = AsyncMock(return_value="msg-id")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache.pull_remote_projects("remote-machine")
        transport_with_cache._cache.apply_projects_snapshot.assert_not_called()

    @pytest.mark.unit
    async def test_sets_computer_name_on_each_project(self, transport_with_cache: RedisTransport) -> None:
        project_data = {"path": "/repo/project", "name": "myproject"}
        response = json.dumps({"status": "success", "data": [project_data]})
        transport_with_cache.send_request = AsyncMock(return_value="msg-id")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache.pull_remote_projects("remote-machine")
        call_args = transport_with_cache._cache.apply_projects_snapshot.call_args
        computer, projects = call_args[0]
        assert computer == "remote-machine"
        assert all(p.computer == "remote-machine" for p in projects)


class TestPullRemoteProjectsWithTodos:
    @pytest.mark.unit
    async def test_does_nothing_when_cache_unavailable(self, transport: RedisTransport) -> None:
        transport._cache = None
        await transport.pull_remote_projects_with_todos("some-computer")

    @pytest.mark.unit
    async def test_populates_both_projects_and_todos(self, transport_with_cache: RedisTransport) -> None:
        project_data = {
            "path": "/repo/project",
            "name": "myproject",
            "todos": [{"slug": "my-todo", "title": "My Todo", "status": "pending"}],
        }
        response = json.dumps({"status": "success", "data": [project_data]})
        transport_with_cache.send_request = AsyncMock(return_value="msg-id")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache.pull_remote_projects_with_todos("remote-machine")
        transport_with_cache._cache.apply_projects_snapshot.assert_called_once()
        transport_with_cache._cache.apply_todos_snapshot.assert_called_once()


class TestPullRemoteTodos:
    @pytest.mark.unit
    async def test_does_nothing_when_cache_unavailable(self, transport: RedisTransport) -> None:
        transport._cache = None
        await transport.pull_remote_todos("some-computer", "/some/path")

    @pytest.mark.unit
    async def test_filters_to_requested_project_path(self, transport_with_cache: RedisTransport) -> None:
        project_data = [
            {
                "path": "/repo/target",
                "name": "target",
                "todos": [{"slug": "t-todo", "title": "T Todo", "status": "pending"}],
            },
            {
                "path": "/repo/other",
                "name": "other",
                "todos": [{"slug": "o-todo", "title": "O Todo", "status": "pending"}],
            },
        ]
        response = json.dumps({"status": "success", "data": project_data})
        transport_with_cache.send_request = AsyncMock(return_value="msg-id")
        transport_with_cache.client.read_response = AsyncMock(return_value=response)

        await transport_with_cache.pull_remote_todos("remote-machine", "/repo/target")
        call_args = transport_with_cache._cache.set_todos.call_args
        _, _, todos = call_args[0]
        assert len(todos) == 1
        assert todos[0].slug == "t-todo"
