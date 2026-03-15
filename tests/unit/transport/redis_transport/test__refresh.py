"""Characterization tests for teleclaude.transport.redis_transport._refresh."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestRefreshKey:
    @pytest.mark.unit
    def test_sessions_always_returns_global_key(self, transport: RedisTransport) -> None:
        key = transport._refresh_key("any-computer", "sessions", None)
        assert key == "sessions:global"

    @pytest.mark.unit
    def test_sessions_with_project_path_still_returns_global(self, transport: RedisTransport) -> None:
        key = transport._refresh_key("any-computer", "sessions", "/repo/project")
        assert key == "sessions:global"

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
    def test_sessions_returns_pull_interested_sessions_coro(self, transport: RedisTransport) -> None:
        transport.pull_interested_sessions = AsyncMock()
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


class TestRecordPeerDigest:
    @pytest.mark.unit
    def test_stores_digest_for_computer(self, transport: RedisTransport) -> None:
        transport._record_peer_digest("some-computer", "digest-abc")
        assert transport._peer_digests["some-computer"] == "digest-abc"

    @pytest.mark.unit
    def test_overwrites_previous_digest(self, transport: RedisTransport) -> None:
        transport._peer_digests["comp"] = "old-digest"
        transport._record_peer_digest("comp", "new-digest")
        assert transport._peer_digests["comp"] == "new-digest"


class TestScheduleRefresh:
    @pytest.mark.unit
    def test_returns_false_for_disallowed_reason(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(computer="remote", data_type="projects", reason="unauthorized")
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_local_computer(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(computer="local", data_type="projects", reason="startup")
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_self_computer(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(computer=transport.computer_name, data_type="projects", reason="startup")
        assert result is False

    @pytest.mark.unit
    def test_returns_false_for_unknown_data_type(self, transport: RedisTransport) -> None:
        result = transport._schedule_refresh(computer="remote-host", data_type="unknown", reason="startup")
        assert result is False

    @pytest.mark.unit
    def test_schedules_task_for_valid_request(self, transport: RedisTransport) -> None:
        transport.pull_remote_projects_with_todos = AsyncMock()
        transport.task_registry = None
        with patch("teleclaude.transport.redis_transport._refresh.asyncio.create_task") as mock_ct:
            mock_ct.return_value = MagicMock(done=MagicMock(return_value=True))
            result = transport._schedule_refresh(computer="remote-host", data_type="projects", reason="startup")
        assert result is True


class TestRequestRefresh:
    @pytest.mark.unit
    def test_delegates_to_schedule_refresh(self, transport: RedisTransport) -> None:
        transport._schedule_refresh = MagicMock(return_value=True)
        result = transport.request_refresh("remote", "projects", reason="startup")
        transport._schedule_refresh.assert_called_once_with(
            computer="remote",
            data_type="projects",
            reason="startup",
            project_path=None,
            force=False,
        )
        assert result is True
