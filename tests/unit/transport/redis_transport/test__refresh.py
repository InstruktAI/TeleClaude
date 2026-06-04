"""Characterization tests for teleclaude.transport.redis_transport._refresh."""

from __future__ import annotations

import json
import time
from collections.abc import Coroutine, Generator
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._refresh import _RefreshRequest
from teleclaude.transport.redis_transport._transport import RedisTransport


class NoopAwaitable:
    def __await__(self) -> Generator[None, None, None]:
        if False:
            yield None
        return None


class _HeartbeatPayload(TypedDict, total=False):
    computer_name: str
    user: str
    host: str
    role: str
    system_stats: None


def _heartbeat_payload(computer_name: str, *, user: str = "user") -> bytes:
    payload = _HeartbeatPayload(
        computer_name=computer_name,
        user=user,
        host="host",
        role="worker",
        system_stats=None,
    )
    return json.dumps(payload).encode()


async def _drive_heartbeat_refresh(
    transport: RedisTransport,
    computer_name: str,
    *,
    user: str = "user",
) -> None:
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_heartbeat_payload(computer_name, user=user))
    transport._get_redis = AsyncMock(return_value=mock_redis)
    transport._cache = MagicMock()
    with patch(
        "teleclaude.transport.redis_transport._refresh.scan_keys",
        AsyncMock(return_value=[f"computer:{computer_name}:heartbeat".encode()]),
    ):
        await transport.refresh_peers_from_heartbeats()


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestRefreshKey:
    @pytest.mark.unit
    def test_sessions_keyed_per_computer(self, transport: RedisTransport) -> None:
        """Sessions are now pulled per peer (was: global) so coalescing must key per peer too."""
        key = transport._refresh_key("any-computer", "sessions", None)
        assert key == "any-computer:sessions"

    @pytest.mark.unit
    def test_projects_without_path_returns_computer_datatype(self, transport: RedisTransport) -> None:
        key = transport._refresh_key("remote-host", "projects", None)
        assert key == "remote-host:projects"

    @pytest.mark.unit
    def test_projects_with_path_includes_path(self, transport: RedisTransport) -> None:
        key = transport._refresh_key("remote-host", "projects", "/repo/myproject")
        assert key == "remote-host:projects:/repo/myproject"


class TestCanScheduleRefresh:
    @pytest.mark.unit
    def test_allows_refresh_when_no_prior_record(self, transport: RedisTransport) -> None:
        assert transport._can_schedule_refresh("new-key", force=False) is True

    @pytest.mark.unit
    def test_blocks_refresh_within_cooldown_window(self, transport: RedisTransport) -> None:
        transport._refresh_last["existing-key"] = time.monotonic()
        assert transport._can_schedule_refresh("existing-key", force=False) is False

    @pytest.mark.unit
    def test_allows_refresh_after_cooldown_expires(self, transport: RedisTransport) -> None:
        transport._refresh_last["old-key"] = time.monotonic() - (transport._refresh_cooldown_seconds + 1)
        assert transport._can_schedule_refresh("old-key", force=False) is True

    @pytest.mark.unit
    def test_force_bypasses_cooldown(self, transport: RedisTransport) -> None:
        transport._refresh_last["recent-key"] = time.monotonic()
        assert transport._can_schedule_refresh("recent-key", force=True) is True

    @pytest.mark.unit
    def test_blocks_when_task_still_running(self, transport: RedisTransport) -> None:
        running_task = MagicMock()
        running_task.done.return_value = False
        transport._refresh_tasks["active-key"] = running_task
        assert transport._can_schedule_refresh("active-key", force=True) is False


class TestBuildRefreshCoro:
    @pytest.mark.unit
    def test_projects_returns_pull_projects_with_todos_coro(self, transport: RedisTransport) -> None:
        transport.pull_remote_projects_with_todos = AsyncMock()
        coro = transport._build_refresh_coro("remote", "projects", None)
        assert coro is not None
        coro.close()

    @pytest.mark.unit
    def test_todos_returns_pull_projects_with_todos_coro(self, transport: RedisTransport) -> None:
        transport.pull_remote_projects_with_todos = AsyncMock()
        coro = transport._build_refresh_coro("remote", "todos", None)
        assert coro is not None
        coro.close()

    @pytest.mark.unit
    def test_sessions_returns_pull_remote_sessions_coro(self, transport: RedisTransport) -> None:
        transport.pull_remote_sessions = AsyncMock()
        coro = transport._build_refresh_coro("remote", "sessions", None)
        assert coro is not None
        coro.close()

    @pytest.mark.unit
    def test_unknown_data_type_returns_none(self, transport: RedisTransport) -> None:
        coro = transport._build_refresh_coro("remote", "unknown_type", None)
        assert coro is None

    @pytest.mark.unit
    def test_preparation_maps_to_projects_with_todos(self, transport: RedisTransport) -> None:
        transport.pull_remote_projects_with_todos = AsyncMock()
        coro = transport._build_refresh_coro("remote", "preparation", None)
        assert coro is not None
        coro.close()


class TestScheduleRefresh:
    @pytest.mark.unit
    def test_returns_false_for_disallowed_reason(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(
            _RefreshRequest(computer="remote", data_type="projects", reason="unauthorized")
        )
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_local_computer(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(_RefreshRequest(computer="local", data_type="projects", reason="startup"))
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_self_computer(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(
            _RefreshRequest(computer=transport.computer_name, data_type="projects", reason="startup")
        )
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_unknown_data_type(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(
            _RefreshRequest(computer="remote-host", data_type="unknown", reason="startup")
        )
        assert result is False

    @pytest.mark.unit
    def test_schedules_task_for_valid_request(self, transport: RedisTransport) -> None:
        transport.pull_remote_projects_with_todos = MagicMock(return_value=NoopAwaitable())
        transport.task_registry = None

        def create_task(coro: Coroutine[object, object, None], *, name: str) -> MagicMock:
            _ = name
            coro.close()
            return MagicMock(done=MagicMock(return_value=True))

        with patch("teleclaude.transport.redis_transport._refresh.asyncio.create_task") as mock_ct:
            mock_ct.side_effect = create_task
            result = transport._schedule_refresh(
                _RefreshRequest(computer="remote-host", data_type="projects", reason="startup")
            )
        assert result is True


class TestRequestRefresh:
    @pytest.mark.unit
    def test_delegates_to_schedule_refresh(self, transport: RedisTransport) -> None:
        transport._schedule_refresh = MagicMock(return_value=True)
        result = transport.request_refresh("remote", "projects", reason="startup")
        transport._schedule_refresh.assert_called_once_with(
            _RefreshRequest(computer="remote", data_type="projects", reason="startup", project_path=None, force=False)
        )
        assert result is True


class TestFirstHeartbeatBootstrap:
    @pytest.mark.unit
    async def test_first_heartbeat_schedules_project_and_session_pulls(self, transport: RedisTransport) -> None:
        schedule_refresh = MagicMock(return_value=True)
        transport._schedule_refresh = schedule_refresh

        await _drive_heartbeat_refresh(transport, "PeerA")

        requests = [call.args[0] for call in schedule_refresh.call_args_list]
        assert [(r.computer, r.data_type, r.reason, r.force) for r in requests] == [
            ("PeerA", "projects", "first_heartbeat", True),
            ("PeerA", "sessions", "first_heartbeat", True),
        ]

    @pytest.mark.unit
    async def test_invalid_heartbeat_identity_is_not_cached_or_scheduled(self, transport: RedisTransport) -> None:
        schedule_refresh = MagicMock(return_value=True)
        transport._schedule_refresh = schedule_refresh

        await _drive_heartbeat_refresh(transport, "PeerA", user="peer;bad")

        transport._cache.update_computer.assert_not_called()
        schedule_refresh.assert_not_called()

    @pytest.mark.unit
    async def test_second_heartbeat_after_success_schedules_nothing(self, transport: RedisTransport) -> None:
        def schedule_success(_request: _RefreshRequest, *, on_success: object | None = None) -> bool:
            if callable(on_success):
                on_success()
            return True

        schedule_refresh = MagicMock(side_effect=schedule_success)
        transport._schedule_refresh = schedule_refresh

        await _drive_heartbeat_refresh(transport, "PeerA")
        assert transport._bootstrapped == {("PeerA", "projects"), ("PeerA", "sessions")}

        schedule_refresh.reset_mock()
        await _drive_heartbeat_refresh(transport, "PeerA")

        schedule_refresh.assert_not_called()

    @pytest.mark.unit
    async def test_different_peer_schedules_independently(self, transport: RedisTransport) -> None:
        transport._bootstrapped = {("PeerA", "projects"), ("PeerA", "sessions")}
        schedule_refresh = MagicMock(return_value=True)
        transport._schedule_refresh = schedule_refresh

        await _drive_heartbeat_refresh(transport, "PeerB")

        requests = [call.args[0] for call in schedule_refresh.call_args_list]
        assert [(r.computer, r.data_type) for r in requests] == [
            ("PeerB", "projects"),
            ("PeerB", "sessions"),
        ]


class TestRefreshSuccessGating:
    """on_success (which records a peer as bootstrapped) must fire only when the
    pull genuinely answered, so a failed first heartbeat retries on the next one
    instead of being permanently recorded as warmed."""

    @pytest.mark.unit
    async def test_failed_pull_does_not_fire_on_success(self, transport: RedisTransport) -> None:
        transport.task_registry = None
        transport.pull_remote_sessions = AsyncMock(return_value=False)
        marked: list[str] = []

        scheduled = transport._schedule_refresh(
            _RefreshRequest("PeerA", "sessions", "first_heartbeat", force=True),
            on_success=lambda: marked.append("sessions"),
        )
        assert scheduled is True
        task = transport._refresh_tasks.get("PeerA:sessions")
        assert task is not None
        await task

        assert marked == []

    @pytest.mark.unit
    async def test_successful_pull_fires_on_success(self, transport: RedisTransport) -> None:
        transport.task_registry = None
        transport.pull_remote_sessions = AsyncMock(return_value=True)
        marked: list[str] = []

        transport._schedule_refresh(
            _RefreshRequest("PeerA", "sessions", "first_heartbeat", force=True),
            on_success=lambda: marked.append("sessions"),
        )
        task = transport._refresh_tasks.get("PeerA:sessions")
        assert task is not None
        await task

        assert marked == ["sessions"]
