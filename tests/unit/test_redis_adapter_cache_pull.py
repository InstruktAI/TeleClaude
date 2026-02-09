"""Unit tests for Redis adapter cache pull methods."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.models import (
    ComputerInfo,
    MessageMetadata,
    ProjectInfo,
    SessionSummary,
    TodoInfo,
)


@pytest.fixture(autouse=True)
def setup_test_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Setup test config for all tests in this module."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
computer:
  name: TestComputer
database:
  path: ${WORKING_DIR}/teleclaude.db
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))


@pytest.mark.unit
@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_happy_path():
    """Test _pull_initial_sessions successfully pulls sessions from remote computers."""
    from teleclaude.transport.redis_transport import RedisTransport

    # Setup
    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock cache
    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
        ComputerInfo(name="RemotePC2", status="online", is_local=False),
    ]
    # Register interest in sessions for both computers (required for per-computer pulls)
    mock_cache.get_interested_computers.return_value = ["RemotePC1", "RemotePC2"]
    adapter.cache = mock_cache

    # Mock send_request
    adapter.send_request = AsyncMock(return_value="msg-123")

    # Mock client.read_response with valid session data
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "session_id": "sess-1",
                        "last_input_origin": "telegram",
                        "computer": "RemotePC1",
                        "status": "active",
                        "title": "Test Session",
                        "project_path": "/home/user/project",
                        "thinking_mode": "slow",
                        "active_agent": "claude",
                        "tmux_session_name": "tmux-sess-1",
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        )
    )

    updated: list[tuple[str, str]] = []

    def record_update(session: SessionSummary) -> None:
        updated.append((session.session_id, session.computer))

    mock_cache.update_session = record_update

    # Execute
    await adapter._pull_initial_sessions()

    # Verify cache was populated for each computer
    assert len(updated) == 2
    assert ("sess-1", "RemotePC1") in updated
    assert ("sess-1", "RemotePC2") in updated


@pytest.mark.unit
@pytest.mark.asyncio
async def test_populate_initial_cache_pulls_projects_with_todos():
    """Startup cache population should pull projects-with-todos for all peers."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    adapter.cache = MagicMock()
    adapter.discover_peers = AsyncMock(
        return_value=[
            SimpleNamespace(
                name="RemotePC1",
                last_seen="now",
                user="user1",
                host="host1",
                role="worker",
                system_stats=None,
            ),
            SimpleNamespace(
                name="RemotePC2",
                last_seen="now",
                user="user2",
                host="host2",
                role="worker",
                system_stats=None,
            ),
        ]
    )
    scheduled: list[tuple[str, str, str, bool]] = []

    def record_schedule(*, computer: str, data_type: str, reason: str, force: bool, **_kwargs) -> bool:
        scheduled.append((computer, data_type, reason, force))
        return True

    adapter._schedule_refresh = record_schedule

    await adapter._populate_initial_cache()

    assert scheduled == [
        ("RemotePC1", "projects", "startup", True),
        ("RemotePC2", "projects", "startup", True),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_no_cache():
    """Test _pull_initial_sessions skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter._pull_initial_sessions()

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_timeout_continues_to_next():
    """Test _pull_initial_sessions continues to next computer on timeout."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
        ComputerInfo(name="RemotePC2", status="online", is_local=False),
    ]
    # Register interest for both computers
    mock_cache.get_interested_computers.return_value = ["RemotePC1", "RemotePC2"]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")

    # First call times out, second succeeds
    mock_client.read_response = AsyncMock(
        side_effect=[
            TimeoutError("timeout"),
            json.dumps({"status": "success", "data": []}),
        ]
    )

    calls: list[str] = []

    async def record_send_request(computer_name: str, command: str, metadata, **_kwargs):
        _ = (command, metadata)
        calls.append(computer_name)
        return "msg-123"

    adapter.send_request = record_send_request

    # Execute
    await adapter._pull_initial_sessions()

    # Verify both computers were attempted
    assert calls == ["RemotePC1", "RemotePC2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_malformed_response_skips():
    """Test _pull_initial_sessions skips malformed responses and continues."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
    ]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")
    mock_client.read_response = AsyncMock(return_value="not valid json {{{")

    # Execute (should not crash)
    await adapter._pull_initial_sessions()

    # Verify update_session was never called
    mock_cache.update_session.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_error_status_skips():
    """Test _pull_initial_sessions skips when remote returns error status."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
    ]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")
    mock_client.read_response = AsyncMock(return_value=json.dumps({"status": "error", "error": "Something went wrong"}))

    # Execute
    await adapter._pull_initial_sessions()

    # Verify update_session was never called
    mock_cache.update_session.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_empty_computers():
    """Test _pull_initial_sessions handles empty computer list."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = []
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock()

    # Execute
    await adapter._pull_initial_sessions()

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_happy_path():
    """Test pull_remote_projects successfully pulls projects from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-456")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {"name": "ProjectA", "path": "/home/user/projectA", "desc": "Project A"},
                    {"name": "ProjectB", "path": "/home/user/projectB", "desc": "Project B"},
                ],
            }
        )
    )

    captured: list[tuple[str, list[ProjectInfo]]] = []

    def record_snapshot(computer: str, projects: list[ProjectInfo]) -> bool:
        captured.append((computer, projects))
        return True

    mock_cache.apply_projects_snapshot = record_snapshot

    # Execute
    await adapter.pull_remote_projects("RemotePC")

    # Verify cache was populated
    assert len(captured) == 1
    assert captured[0][0] == "RemotePC"
    assert len(captured[0][1]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_no_cache():
    """Test pull_remote_projects skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter.pull_remote_projects("RemotePC")

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_timeout():
    """Test pull_remote_projects handles timeout gracefully."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-456")
    mock_client.read_response = AsyncMock(side_effect=TimeoutError("timeout"))

    # Execute (should not crash)
    await adapter.pull_remote_projects("RemotePC")

    # Verify cache was not populated
    mock_cache.set_projects.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_todos_happy_path():
    """Test pull_remote_todos successfully pulls todos from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-789")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "name": "ProjectA",
                        "path": "/home/user/projectA",
                        "todos": [
                            {"slug": "todo-1", "title": "Todo 1", "status": "pending"},
                            {"slug": "todo-2", "title": "Todo 2", "status": "complete"},
                        ],
                    },
                ],
            }
        )
    )

    captured: list[tuple[str, str, list[TodoInfo]]] = []

    def record_todos(computer: str, project_path: str, todos: list[TodoInfo]) -> None:
        captured.append((computer, project_path, todos))

    mock_cache.set_todos = record_todos

    # Execute
    await adapter.pull_remote_todos("RemotePC", "/home/user/projectA")

    # Verify cache was populated
    assert len(captured) == 1
    assert captured[0][0] == "RemotePC"
    assert captured[0][1] == "/home/user/projectA"
    assert len(captured[0][2]) == 2
    adapter.send_request.assert_awaited_once_with("RemotePC", "list_projects_with_todos", MessageMetadata())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_todos_no_cache():
    """Test pull_remote_todos skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter.pull_remote_todos("RemotePC", "/home/user/project")

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_happy_path():
    """Test pull_remote_projects_with_todos pulls projects and todos from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-900")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "name": "ProjectA",
                        "path": "/home/user/projectA",
                        "desc": "Project A",
                        "todos": [
                            {"slug": "todo-1", "title": "Todo 1", "status": "pending"},
                        ],
                    },
                    {
                        "name": "ProjectB",
                        "path": "/home/user/projectB",
                        "desc": "Project B",
                        "todos": [],
                    },
                ],
            }
        )
    )

    captured_projects: list[tuple[str, list[ProjectInfo]]] = []
    captured_todos: list[tuple[str, dict[str, list[TodoInfo]]]] = []

    def record_projects(computer: str, projects: list[ProjectInfo]) -> bool:
        captured_projects.append((computer, projects))
        return True

    def record_todos_snapshot(computer: str, todos_by_project: dict[str, list[TodoInfo]]) -> None:
        captured_todos.append((computer, todos_by_project))

    mock_cache.apply_projects_snapshot = record_projects
    mock_cache.apply_todos_snapshot = record_todos_snapshot

    await adapter.pull_remote_projects_with_todos("RemotePC")

    assert len(captured_projects) == 1
    assert captured_projects[0][0] == "RemotePC"
    assert len(captured_todos) == 1
    assert captured_todos[0][0] == "RemotePC"
    todos_by_project = captured_todos[0][1]
    assert "/home/user/projectA" in todos_by_project
    assert "/home/user/projectB" in todos_by_project


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_no_cache():
    """Test pull_remote_projects_with_todos skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    await adapter.pull_remote_projects_with_todos("RemotePC")

    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_fallbacks_to_projects():
    """Fallback to list_projects when projects-with-todos is unsupported."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = MagicMock()

    adapter.send_request = AsyncMock(return_value="msg-901")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "error",
                "error": "No handler registered for event: list_projects_with_todos",
            }
        )
    )
    pulled = []

    async def record_pull(computer: str) -> None:
        pulled.append(computer)

    adapter.pull_remote_projects = record_pull

    await adapter.pull_remote_projects_with_todos("RemotePC")

    assert pulled == ["RemotePC"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_populates_cache():
    """Test that heartbeat processing populates cache with computer info."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    # Mock Redis heartbeat scan
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(return_value=(0, [b"computer:RemotePC:heartbeat"]))
    mock_redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "computer_name": "RemotePC",
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "interested_in": [],
            }
        ).encode("utf-8")
    )
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    captured: list[ComputerInfo] = []

    def record_computer(info: ComputerInfo) -> None:
        captured.append(info)

    mock_cache.update_computer = record_computer

    # Execute
    await adapter.refresh_peers_from_heartbeats()

    # Verify cache was updated
    assert len(captured) == 1
    assert captured[0].name == "RemotePC"
    assert captured[0].status == "online"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_refresh_coalesces_in_flight_tasks():
    """request_refresh should coalesce concurrent refreshes per peer+data type."""
    from teleclaude.transport.redis_transport import RedisTransport

    adapter = RedisTransport(MagicMock())
    adapter._refresh_cooldown_seconds = 0

    blocker = asyncio.Event()

    async def _blocked(*_args, **_kwargs):
        await blocker.wait()

    adapter.pull_remote_projects_with_todos = AsyncMock(side_effect=_blocked)

    scheduled = adapter.request_refresh("RemotePC", "projects", reason="interest")
    assert scheduled is True

    scheduled_again = adapter.request_refresh("RemotePC", "projects", reason="interest")
    assert scheduled_again is False

    blocker.set()
    await asyncio.sleep(0)

    scheduled_after = adapter.request_refresh("RemotePC", "projects", reason="interest")
    assert scheduled_after is True
